"""Wasalt adapter (wasalt.sa, English site).

Discovery: the real sitemaps are gzipped XML on ``cdn.wasalt.sa`` (listed in
``/robots.txt``) and are fetched with plain HTTP:
  * ``product_sitemap_en_sa``  -> /en/property/{sale|rent}/<slug>-<id>  (PDP)
  * ``category_sitemap_en_sa`` -> /en/properties-for-sale-in-<city>...   (SRP)
  * ``static_sitemap_en_sa``   -> /en/s/<page>
We never request ``/search`` (disallowed for generic bots in robots.txt).

Extraction: a property detail page is backed by Wasalt's own unauthenticated
public JSON API (``api.wasalt.com/misc/v3/properties/<id>``, the endpoint the
public page itself calls). Sending ``locale: en`` returns English fields. This is
simpler and gentler than rendering a 250 KB page behind Cloudflare, and gives
exact numbers. Informational pages (home, /s/*) are browser-rendered and mined
for their FAQ / "about" passages. Missing prices stay ``None``.
"""

from __future__ import annotations

import gzip
import re
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.models.document import Document, ExtractionMethod, ExtractionStatus, Passage
from app.models.property import (
    EvidenceRef,
    PriceBasis,
    Property,
    RecordType,
    Source,
    TransactionType,
)
from app.scrapers import htmlparse as H
from app.scrapers.model import ExtractedPage
from app.scrapers.normalize import chunk_passages, clean_text, content_hash, make_id, slugify

BASE = "https://wasalt.sa"
API_BASE = "https://api.wasalt.com/misc/v3/properties"
CDN_SITEMAPS = {
    "product": "https://cdn.wasalt.sa/sitemap/product_sitemap_en_sa.xml.gz",
    "category": "https://cdn.wasalt.sa/sitemap/category_sitemap_en_sa.xml.gz",
    "static": "https://cdn.wasalt.sa/sitemap/static_sitemap_en_sa.xml.gz",
}
HOME_AND_INFO = [
    "https://wasalt.sa/en",
    "https://wasalt.sa/en/s/masterplan",
]
API_HEADERS = {
    "locale": "en",
    "accept-language": "en-US,en;q=0.9",
    "accept": "application/json",
    "referer": "https://wasalt.sa/",
    "origin": "https://wasalt.sa",
    # api.wasalt.com rejects non-browser User-Agents, so the API path always
    # presents a standard browser UA (it is the site's own public endpoint).
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

_ID_RE = re.compile(r"-(\d+)/?$")
_TYPE_TOKENS = ("apartment", "villa", "land", "townhouse", "penthouse", "floor", "building",
                "chalet", "duplex", "studio", "office", "warehouse", "farm", "rest-house")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def _fetch_sitemap_locs(client: httpx.AsyncClient, url: str) -> list[str]:
    resp = await client.get(url, timeout=45)
    resp.raise_for_status()
    try:
        xml = gzip.decompress(resp.content).decode("utf-8", "replace")
    except (OSError, EOFError):
        xml = resp.text
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def _stride(seq: list[str], want: int) -> list[str]:
    if not seq or want <= 0:
        return []
    step = max(1, len(seq) // want)
    return seq[::step][:want]


async def discover(client: httpx.AsyncClient, limit: int = 60) -> list[str]:
    """Return crawl targets. ``limit <= 0`` means the full product/category/static sitemaps."""
    product = await _fetch_sitemap_locs(client, CDN_SITEMAPS["product"])
    category = await _fetch_sitemap_locs(client, CDN_SITEMAPS["category"])
    try:
        static = await _fetch_sitemap_locs(client, CDN_SITEMAPS["static"])
    except Exception:  # noqa: BLE001
        static = []

    sale = [u for u in product if "/property/sale/" in u]
    rent = [u for u in product if "/property/rent/" in u]
    cats = [u for u in category if "properties-for-sale-in" in u or "properties-for-rent-in" in u]

    if limit <= 0:
        picked = list(HOME_AND_INFO) + static + sale + rent + category
    else:
        n_sale = max(8, int(limit * 0.6))
        n_rent = max(4, int(limit * 0.22))
        n_cat = max(3, int(limit * 0.1))
        picked = list(HOME_AND_INFO)
        picked += _stride(sale, n_sale)
        picked += _stride(rent, n_rent)
        picked += _stride(cats, n_cat)

    seen: set[str] = set()
    deduped = [u for u in picked if u.startswith(BASE) and not (u in seen or seen.add(u))]
    return deduped if limit <= 0 else deduped[:limit]


def is_pdp(url: str) -> bool:
    return "/property/sale/" in url or "/property/rent/" in url


def property_id_from_url(url: str) -> str | None:
    m = _ID_RE.search(url.split("?")[0])
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# API path (property detail pages)
# ---------------------------------------------------------------------------


async def fetch_api(client: httpx.AsyncClient, property_id: str) -> dict | None:
    resp = await client.get(
        f"{API_BASE}/{property_id}",
        params={"view": "DETAIL_PAGE_MOBILE"},
        headers=API_HEADERS,
        timeout=25,
    )
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or "propertyInfo" not in data:
        return None  # expired / redirected listing
    return data


# Cloudflare Images account used by Wasalt's public PDP og:image URLs.
_WASALT_IMAGE_HOST = "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w"


def _images_from_api_payload(data: dict) -> list[str]:
    """All gallery URLs from DETAIL_PAGE_MOBILE (cover / facade first)."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None) -> None:
        if not url or not isinstance(url, str) or not url.startswith("http"):
            return
        if "undefined" in url or "ad_qr" in url.lower():
            return
        key = url.split("?")[0].lower()
        if key in seen:
            return
        seen.add(key)
        out.append(url)

    for img_key in ("coverImage", "image", "thumbnail", "mainImage", "defaultImage"):
        v = data.get(img_key)
        if isinstance(v, str):
            _add(v)
        elif isinstance(v, dict):
            for nested in ("url", "src", "path", "imageUrl"):
                nv = v.get(nested)
                if isinstance(nv, str):
                    _add(nv)

    for key in ("media", "images", "propertyImages", "photos", "gallery"):
        media = data.get(key)
        if not isinstance(media, list):
            continue
        for item in media:
            if isinstance(item, str):
                _add(item)
            elif isinstance(item, dict):
                for nested in ("url", "src", "path", "imageUrl", "original", "large"):
                    nv = item.get(nested)
                    if isinstance(nv, str):
                        _add(nv)

    pid = str(data.get("id") or "").strip()
    classified = data.get("classificationData") or []
    if pid and isinstance(classified, list):
        facade: list[str] = []
        other: list[str] = []
        plans: list[str] = []
        for row in classified:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not isinstance(name, str):
                continue
            name = name.strip()
            if name.lower() in {"undefined", "null", "none", ""}:
                continue
            if not name.endswith((".webp", ".jpg", ".jpeg", ".png")):
                continue
            low_name = name.lower()
            if any(bad in low_name for bad in ("ad_qr", "qr-code", "qr_code", "watermark", "logo")):
                continue
            label = str(row.get("classificationName") or "").lower()
            if label in {"empty_room", "plan", "floor_plan", "map"}:
                plans.append(name)
            elif label in {"facade", "exterior", "front", "building"}:
                facade.append(name)
            else:
                other.append(name)
        for name in facade + other + plans:
            _add(
                f"{_WASALT_IMAGE_HOST}/production/properties/{pid}/images/"
                f"{name}/quality=60,format=auto,width=1200"
            )
    return out


def _image_from_api_payload(data: dict) -> str | None:
    imgs = _images_from_api_payload(data)
    return imgs[0] if imgs else None


async def fetch_listing_image(client: httpx.AsyncClient, url: str) -> str | None:
    """PDP HTML carries og:image (Cloudflare imagedelivery) even when the JSON API does not.

    Wasalt's HTML edge often 403s httpx but accepts stdlib urllib with the same
    browser UA, so we fetch via a thread rather than the shared httpx client.
    Prefer this over classificationData when available — og:image is the real cover.
    """
    import asyncio
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    def _fetch() -> str | None:
        req = Request(url, headers=API_HEADERS)
        try:
            with urlopen(req, timeout=25) as resp:
                html = resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError, OSError):
            return None
        img = H.og_image_from_html(html)
        if img and "undefined" not in img and "ad_qr" not in img.lower():
            return img
        return None

    return await asyncio.to_thread(_fetch)


async def attach_listing_image(client: httpx.AsyncClient, page: ExtractedPage) -> None:
    """Fill cover from HTML only when the API gallery is empty."""
    for prop in page.properties:
        if prop.image_urls:
            if not prop.image_url:
                prop.image_url = prop.image_urls[0]
            continue
        html_img = await fetch_listing_image(client, prop.source_url)
        if html_img:
            prop.image_url = html_img
            prop.image_urls = [html_img]
        elif prop.image_url and (
            "undefined" in prop.image_url or "ad_qr" in prop.image_url.lower()
        ):
            prop.image_url = None


def _num(value) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    try:
        d = Decimal(str(value).replace(",", ""))
        return d if d > 0 else None
    except Exception:  # noqa: BLE001
        return None


def _int(value) -> int | None:
    try:
        n = int(float(str(value)))
        return n if 0 <= n <= 60 else None
    except (TypeError, ValueError):
        return None


def _attr(data: dict, key: str):
    for a in data.get("attributes", []) or []:
        if a.get("key") == key:
            return a.get("value")
    for a in data.get("additionalAttributes", []) or []:
        if a.get("key") == key:
            return a.get("value")
    return None


# Wasalt's API returns raw transliterations for smaller cities; map them to the
# names people actually type.
_CITY_CANON = {
    "aldammam": "Dammam",
    "alttayif": "Taif",
    "alttaif": "Taif",
    "almuzahimih": "Al Muzahimiyah",
    "almuzahimiyah": "Al Muzahimiyah",
    "bariduh": "Buraydah",
    "buraidah": "Buraydah",
    "tbwk": "Tabuk",
    "makkah al mukarramah": "Makkah",
    "makkah al-mukarramah": "Makkah",
    "al madinah al munawwarah": "Madinah",
    "almadinah": "Madinah",
    "alkhobar": "Khobar",
    "al khobar": "Khobar",
    "jazan": "Jazan",
    "jizan": "Jazan",
}


def _canonical_city(city: str | None) -> str | None:
    if not city:
        return city
    key = " ".join(city.split()).lower()
    if key in _CITY_CANON:
        return _CITY_CANON[key]
    # "Abu Arish - 'Abu Earish" style — take the cleaner half.
    if " - " in city:
        left = city.split(" - ")[0].strip().strip("'").strip()
        return _CITY_CANON.get(left.lower(), left or city)
    return city


def build_from_api(url: str, data: dict) -> ExtractedPage:
    now = datetime.now(timezone.utc)
    info = data.get("propertyInfo", {}) or {}
    pid = str(data.get("id") or property_id_from_url(url) or "")

    transaction = TransactionType.RENT if info.get("propertyFor") == "rent" else TransactionType.SALE
    title = info.get("title") or info.get("propertyName") or f"Wasalt property {pid}"
    subtype = (info.get("propertySubType") or info.get("propertySubTypeSlug") or "").strip().lower() or None
    if subtype and not subtype.isascii():
        subtype = (info.get("propertySubTypeSlug") or "").strip().lower() or None

    city = info.get("city") if (info.get("city") or "").isascii() else None
    city = _canonical_city(city)
    district = info.get("district") if (info.get("district") or "").isascii() else info.get("zone")
    district = district if (district or "").isascii() else None
    country = info.get("country") if (info.get("country") or "").isascii() else "Saudi Arabia"

    currency = "SAR"  # Wasalt is Saudi-only; API gives the symbol "ر.س"
    if transaction == TransactionType.RENT:
        # `expectedRent` is the real figure; `conversionPrice` mirrors it for rentals.
        price = _num(info.get("expectedRent")) or _num(info.get("conversionPrice"))
        period = str(info.get("expectedRentType") or "").lower()
        basis = PriceBasis.MONTHLY_RENT if "شهر" in period or "month" in period else PriceBasis.ANNUAL_RENT
        if price is None:
            basis = PriceBasis.UNSPECIFIED
    else:
        # Only trust the explicit `salePrice`. `conversionPrice` is a
        # display-currency helper that is unreliable for sale listings (it can
        # carry a token value), so a missing sale price stays unknown.
        price = _num(info.get("salePrice"))
        basis = PriceBasis.TOTAL if price is not None else PriceBasis.UNSPECIFIED

    bedrooms = _int(_attr(data, "noOfBedrooms"))
    if bedrooms is None and (subtype == "studio" or "studio" in url.lower()):
        bedrooms = 0
    bathrooms = _int(_attr(data, "noOfBathrooms"))

    area_raw = _attr(data, "builtUpArea") or _attr(data, "carpetArea") or _attr(data, "landArea")
    area_value = _num(area_raw)
    area_unit = "sqm" if area_value is not None else None
    # Wasalt sometimes reports the plot/building footprint in `builtUpArea` for a
    # flat ("Apartment 2483 SQM"). Over ~1500 sqm it is not a unit area — drop it
    # rather than let it distort a "largest apartment" query. Raw stays in
    # original_area_text.
    if (
        area_value is not None
        and area_value > Decimal(1500)
        and (subtype in ("apartment", "studio", "flat") or "apartment" in url.lower())
    ):
        area_value = None
        area_unit = None

    # --- sale-price sanity ------------------------------------------------
    # Wasalt's bulk catalogue carries broker data-entry errors: token prices
    # ("SAR 42,000" for an 830 sqm flat) and mis-keyed figures. We never invent a
    # value, but a price that is internally impossible is dropped (raw text kept
    # in original_price_text) so it can't rank as "the cheapest".
    if transaction == TransactionType.SALE and price is not None:
        is_land = (subtype in ("land", "plot")) or "/land" in url.lower() or "land-" in url.lower()
        min_total = Decimal(15_000) if is_land else Decimal(120_000)
        if price < min_total:
            price = None
        elif (
            not is_land
            and area_value
            and area_value > 0
            and (price / area_value) < Decimal(200)  # SAR/sqm floor for a real sale
        ):
            price = None
        if price is None:
            basis = PriceBasis.UNSPECIFIED

    # --- rent-price sanity --------------------------------------------
    # Same broker data-entry problem on the rent side: "SAR 350/year" for an
    # apartment, or "SAR 1,700/year" for a 730 sqm flat. A real Saudi rental
    # floor is roughly SAR 5,000/year (well under any genuine studio).
    if transaction == TransactionType.RENT and price is not None:
        monthly = basis == PriceBasis.MONTHLY_RENT
        min_rent = Decimal(500) if monthly else Decimal(5_000)
        if price < min_rent:
            price = None
            basis = PriceBasis.UNSPECIFIED

    # A property's own bedroom count over ~15 is a mis-keyed attribute (area or
    # price landing in noOfBedrooms), not a real single unit.
    if bedrooms is not None and bedrooms > 15:
        bedrooms = None

    # description: strip HTML; keep full text (Arabic + English) for retrieval
    raw_desc = re.sub(r"<[^>]+>", " ", info.get("description") or "")
    raw_desc = " ".join(raw_desc.split())
    description = raw_desc[:4000] if raw_desc else None

    amenities: list[str] = []
    for a in data.get("attributes", []) or []:
        name = a.get("name")
        if isinstance(name, str) and a.get("key") not in (
            "noOfBedrooms", "noOfBathrooms", "builtUpArea", "carpetArea", "landArea",
        ):
            amenities.append(name.strip())
    for a in data.get("additionalAttributes", []) or []:
        name = a.get("name")
        if isinstance(name, str) and name.strip() and name.strip() not in amenities:
            amenities.append(name.strip())

    gallery = _images_from_api_payload(data)
    image_url = gallery[0] if gallery else None

    doc_id = f"wasalt:doc:{slugify(url[len(BASE):].strip('/') or pid, 100)}"
    facts = [
        f"{title}.",
        f"Listed for {transaction.value} on Wasalt.",
        f"Location: {', '.join(x for x in [district, city, country] if x)}." if (city or district) else "",
        f"Price: {currency} {price} ({basis.value.replace('_', ' ')})." if price is not None else "Price: not listed in the collected source.",
        f"Bedrooms: {bedrooms}." if bedrooms is not None else "",
        f"Bathrooms: {bathrooms}." if bathrooms is not None else "",
        f"Area: {area_value} sqm." if area_value is not None else "",
        f"Property type: {subtype}." if subtype else "",
        f"Amenities: {', '.join(amenities)}." if amenities else "",
        description or "",
    ]
    cleaned = clean_text("\n".join(f for f in facts if f))

    document = Document(
        id=doc_id,
        source=Source.WASALT,
        canonical_url=url,
        title=title,
        cleaned_text=cleaned,
        fetched_at=now,
        content_hash=content_hash(cleaned),
        extraction_method=ExtractionMethod.JSON_LD,
        extraction_status=ExtractionStatus.OK,
        language="en",
        http_status=200,
    )
    passages = [
        Passage(
            id=f"{doc_id}#p{i}",
            document_id=doc_id,
            source=Source.WASALT,
            canonical_url=url,
            page_title=title,
            section_heading=None,
            text=body,
            collected_at=now,
            content_hash=content_hash(body),
            language="en",
        )
        for i, (_, body) in enumerate(chunk_passages(cleaned))
    ] or [
        Passage(
            id=f"{doc_id}#p0",
            document_id=doc_id,
            source=Source.WASALT,
            canonical_url=url,
            page_title=title,
            section_heading=None,
            text=cleaned,
            collected_at=now,
            content_hash=content_hash(cleaned),
            language="en",
        )
    ]

    prop = Property(
        id=make_id(Source.WASALT.value, RecordType.LISTING.value, _ID_RE.sub("", url.rsplit("/", 1)[-1]) + f"-{pid}"),
        source=Source.WASALT,
        source_record_id=pid,
        record_type=RecordType.LISTING,
        title=title,
        country=country,
        city=city,
        district=district,
        property_type=subtype,
        transaction_type=transaction,
        price_amount=price,
        price_currency=currency if price is not None else None,
        price_basis=basis,
        original_price_text=(info.get("conversionPrice") and f"{info.get('conversionPrice')} {info.get('conversionUnit','')}".strip()) or None,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        area_value=area_value,
        area_unit=area_unit,
        original_area_text=(f"{area_raw} sqm" if area_raw else None),
        amenities=amenities[:80],
        description=description,
        developer=info.get("projectName") or None,
        completion_or_handover_text=info.get("possessionType") if (info.get("possessionType") or "").isascii() else None,
        image_url=image_url,
        image_urls=gallery,
        source_url=url,
        scraped_at=now,
        content_hash=content_hash(cleaned),
        evidence=[
            EvidenceRef(passage_id=p.id, document_id=doc_id, canonical_url=url) for p in passages[:4]
        ],
    )
    for p in passages:
        p.property_id = prop.id
    return ExtractedPage(document=document, passages=passages, properties=[prop])


# ---------------------------------------------------------------------------
# Browser path (informational pages: home FAQ, /s/*)
# ---------------------------------------------------------------------------


def _slug_of(url: str) -> str:
    return url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def extract(
    url: str, final_url: str, html: str, status_code: int, browser_title: str = ""
) -> ExtractedPage:
    """Used only for non-PDP Wasalt pages (the pipeline routes PDPs to the API)."""
    now = datetime.now(timezone.utc)
    soup = H.make_soup(html)
    ld = H.json_ld_blocks(soup)
    title = (browser_title or "").strip() or H.page_title(soup) or _slug_of(url).replace("-", " ").title()
    cleaned = clean_text(H.visible_text(soup))
    doc_id = f"wasalt:doc:{slugify(url[len(BASE):].strip('/') or 'home', 100)}"

    document = Document(
        id=doc_id,
        source=Source.WASALT,
        canonical_url=final_url or url,
        title=title,
        cleaned_text=cleaned,
        fetched_at=now,
        content_hash=content_hash(cleaned),
        extraction_method=ExtractionMethod.JSON_LD if ld else ExtractionMethod.CRAWL4AI,
        extraction_status=ExtractionStatus.OK if len(cleaned) > 300 else ExtractionStatus.PARTIAL,
        language="en",
        http_status=status_code,
    )

    passages: list[Passage] = []
    for idx, (heading, body) in enumerate(chunk_passages(cleaned)):
        passages.append(
            Passage(
                id=f"{doc_id}#p{idx}",
                document_id=doc_id,
                source=Source.WASALT,
                canonical_url=final_url or url,
                page_title=title,
                section_heading=heading,
                text=body,
                collected_at=now,
                content_hash=content_hash(body),
                language="en",
            )
        )

    faq = H.find_ld_of_type(ld, "FAQPage")
    if faq:
        for i, qa in enumerate(faq.get("mainEntity", []) or []):
            q = (qa.get("name") or "").strip()
            a = ((qa.get("acceptedAnswer") or {}).get("text") or "").strip()
            if q and a:
                passages.append(
                    Passage(
                        id=f"{doc_id}#faq{i}",
                        document_id=doc_id,
                        source=Source.WASALT,
                        canonical_url=final_url or url,
                        page_title=title,
                        section_heading=q,
                        text=f"Q: {q}\nA: {a}",
                        collected_at=now,
                        content_hash=content_hash(q + a),
                        language="en",
                    )
                )

    return ExtractedPage(document=document, passages=passages, properties=[])
