"""DarGlobal adapter (darglobal.co.uk).

Discovery: the sitemap at /sitemap.xml is served without challenge, so it is
fetched with plain HTTP. It yields three useful groups:
  * branded development pages  -> single-segment slugs (curated + heuristic)
  * project category pages     -> /projects/properties-in-<country>[/type]
  * informational pages        -> /about, /faq, /why-invest, blog, insights, press

Extraction (browser-rendered HTML): schema.org JSON-LD @graph when present, plus
visible main-content text. A branded development page becomes one ``development``
property record; category and informational pages become documents + passages only.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

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
from app.scrapers.normalize import (
    chunk_passages,
    clean_text,
    content_hash,
    make_id,
    parse_area,
    parse_bedrooms,
    parse_price,
    slugify,
)

SITEMAP_URL = "https://darglobal.co.uk/sitemap.xml"
BASE = "https://darglobal.co.uk"

# Curated branded-development pages, checked to render real project "key facts".
# Tried first so a short crawl still lands the actual projects rather than
# marketing/landing pages that share the single-slug URL shape.
_KNOWN_DEVELOPMENTS = [
    "trump-tower-jeddah", "the-astera", "tierra-viva", "marea", "neptune",
    "urban-oasis-by-missoni", "w-residences", "les-vagues", "davinci-tower-by-pagani",
    "sea-la-vie", "the-mulliner", "marriott-residences-aida-oman", "aida-trump-villas",
    "aida-coastal-investment-villas", "fairway-villas-aida-oman", "d-villas-at-jge",
    "aida-trump-international-hotel", "aida-trump-international-apartments",
    "aida-trump-international-cliff-villas", "sunrise-haven-luxury-villas",
    "trump-international-hotel-and-tower-dubai", "trump-international-resort-maldives",
    "amour-sans-detour", "amour-sans-detour-2", "the-great-escape-1-aida-oman",
    "the-great-escape-2-aida-oman",
]

# Slugs that are definitely not developments (marketing / utility / editorial).
_NON_PROJECT_SLUGS = {
    "about", "faq", "why-invest", "careers", "internships", "internship-application",
    "get-in-touch", "become-a-broker", "become-an-agent", "privacy-policy",
    "terms-conditions", "terms-of-uses", "terms-of-use", "pay-online", "thank-you",
    "success", "bookyourunit", "tokenization", "investor", "commercial", "hospitality",
    "development-management", "dg-circle", "exclusive-membership", "insignia",
    "partners", "one-of-one", "insights", "blog", "press", "campaigns", "landing-page",
    "landingpage", "new-home-page", "live-all-in", "win-a-trip-to-dubai", "dg1",
    "aida-360", "aston-martin-media", "sohar-islamic", "luxury-golf-communities",
    "pre-launch-trump-jeddah-tower", "exclusive-plots", "invest-crypto", "invest-in-aida",
    "tokenization", "dg-insignia-card", "darglobal-insignia-card",
    "darglobal-exclusive-off-plan-investment-catalogue", "the-great-escape-1-aida-oman-terms",
    "broker-contest-terms-conditions", "win-a-trip-to-dubai", "internships",
}

_INFO_SLUGS = ["about", "faq", "why-invest", "development-management", "hospitality"]

# Ordered most-specific first: a city keyword names a place unambiguously; a
# bare country keyword is the fallback. "london"/"uk" sit last on purpose — the
# DarGlobal HQ address makes "London" appear in every page's boilerplate, so it
# must never outrank a real location keyword found earlier in the text.
_COUNTRY_BY_KEYWORD = {
    "dubai": ("United Arab Emirates", "Dubai"),
    "abu-dhabi": ("United Arab Emirates", "Abu Dhabi"),
    "abu dhabi": ("United Arab Emirates", "Abu Dhabi"),
    "ras al khaimah": ("United Arab Emirates", "Ras Al Khaimah"),
    "al marjan": ("United Arab Emirates", "Ras Al Khaimah"),
    "jeddah": ("Saudi Arabia", "Jeddah"),
    "riyadh": ("Saudi Arabia", "Riyadh"),
    "muscat": ("Oman", "Muscat"),
    "aida": ("Oman", "Muscat"),
    "doha": ("Qatar", "Doha"),
    "marbella": ("Spain", "Marbella"),
    "benahavis": ("Spain", "Benahavís"),
    "benahavís": ("Spain", "Benahavís"),
    "costa del sol": ("Spain", None),
    "estepona": ("Spain", "Estepona"),
    "maldives": ("Maldives", None),
    "uae": ("United Arab Emirates", None),
    "saudi-arabia": ("Saudi Arabia", None),
    "saudi arabia": ("Saudi Arabia", None),
    "qatar": ("Qatar", "Doha"),
    "oman": ("Oman", None),
    "spain": ("Spain", None),
    "london": ("United Kingdom", "London"),
    "united kingdom": ("United Kingdom", "London"),
}

_PROPERTY_TYPE_KEYWORDS = ("villa", "apartment", "penthouse", "townhouse", "mansion", "hotel room")

# Labels DarGlobal uses in its project "key facts" strip. Order-independent; each
# value runs until the next known label.
_DG_FACT_LABELS = [
    "Property Type",
    "Unit Type",
    "Units",
    "Status",
    "Expected Completion Date",
    "Completion Date",
    "Handover",
    "Number of Floors",
    "Area (Sqm)",
    "Area (sqm)",
    "Location",
    "Developer",
    "Starting Price",
    "Price",
]


def _parse_dg_facts(text: str) -> dict[str, str]:
    labels = sorted(_DG_FACT_LABELS, key=len, reverse=True)
    label_re = "|".join(re.escape(x) for x in labels)
    facts: dict[str, str] = {}
    for m in re.finditer(rf"({label_re})\s+(.+?)(?=\s+(?:{label_re})\s|\s*$)", text[:4000]):
        key = m.group(1).lower().strip()
        val = " ".join(m.group(2).split())[:160]
        if val and key not in facts:
            facts[key] = val
    return facts


def _bedrooms_from_unit_text(text: str) -> int | None:
    """DarGlobal quotes ranges like '1 to 3-bedroom' — take the low end as a hint."""
    m = re.search(r"(\d+)\s*(?:to|-|–)\s*\d+\s*-?\s*bedroom", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*-?\s*bedroom", text, re.I)
    return int(m.group(1)) if m else None


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


async def discover(client: httpx.AsyncClient, limit: int = 80) -> list[str]:
    """Return crawl targets. ``limit <= 0`` means the full public sitemap + curated."""
    resp = await client.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()
    locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)

    known: list[str] = [f"{BASE}/{slug}" for slug in _KNOWN_DEVELOPMENTS]

    heuristic_devs: list[str] = []
    categories: list[str] = []
    informational: list[str] = []
    other: list[str] = []
    for url in locs:
        if not url.startswith(BASE):
            continue
        path = url[len(BASE):].strip("/")
        if not path:
            other.append(url.rstrip("/") or BASE)
            continue
        segments = path.split("/")
        first = segments[0].lower()
        if first == "projects" and len(segments) >= 2:
            categories.append(url)
        elif len(segments) == 1 and first not in _NON_PROJECT_SLUGS and first not in _KNOWN_DEVELOPMENTS:
            heuristic_devs.append(url)
        elif first in ("blog", "insights", "press") and len(segments) >= 2:
            informational.append(url)
        elif first in _INFO_SLUGS or first in _NON_PROJECT_SLUGS:
            informational.append(url)
        else:
            other.append(url)

    for slug in reversed(_INFO_SLUGS):
        informational.insert(0, f"{BASE}/{slug}")

    if limit <= 0:
        ordered = known + heuristic_devs + categories + informational + other
    else:
        ordered = known + categories[:6] + heuristic_devs + informational[: max(6, limit // 5)]
    seen: set[str] = set()
    deduped = [u for u in ordered if not (u in seen or seen.add(u))]
    return deduped if limit <= 0 else deduped[:limit]


def _match_location(hay: str) -> tuple[str | None, str | None]:
    """First keyword hit within ``hay`` in most-specific-first priority order."""
    for kw, (country, city) in _COUNTRY_BY_KEYWORD.items():
        if re.search(rf"\b{re.escape(kw)}\b", hay):
            return country, city
    return None, None


def _country_city_from_text(
    text: str, url: str, *, primary: str = "", title: str = ""
) -> tuple[str | None, str | None]:
    """Resolve country/city, trusting the authoritative signals first.

    ``primary`` is the DarGlobal "Location" key-fact and ``title`` the page
    title — either names the real location. The page body is only consulted for
    its lead paragraph (before the repeated footer/HQ boilerplate that would
    otherwise pull every record to London).
    """
    for strong in (primary, title, url, text[:700]):
        if strong:
            hit = _match_location(strong.lower())
            if hit[0]:
                return hit
    return None, None


def _property_type_from_text(text: str) -> str | None:
    low = text[:3000].lower()
    for pt in _PROPERTY_TYPE_KEYWORDS:
        if pt in low:
            return pt
    return None


def _is_development_page(url: str) -> bool:
    path = url[len(BASE):].strip("/") if url.startswith(BASE) else url
    return "/" not in path and path.lower() not in _NON_PROJECT_SLUGS


def extract(
    url: str, final_url: str, html: str, status_code: int, browser_title: str = ""
) -> ExtractedPage:
    now = datetime.now(timezone.utc)
    soup = H.make_soup(html)
    ld = H.json_ld_blocks(soup)

    title = (browser_title or "").strip() or H.page_title(soup) or _slug(url).replace("-", " ").title()
    text_raw = H.visible_text(soup)
    cleaned = clean_text(text_raw)
    lang = "en"

    extraction_status = ExtractionStatus.OK if len(cleaned) > 400 else ExtractionStatus.PARTIAL
    doc_id = make_id_doc(url)
    document = Document(
        id=doc_id,
        source=Source.DARGLOBAL,
        canonical_url=final_url or url,
        title=title,
        cleaned_text=cleaned,
        fetched_at=now,
        content_hash=content_hash(cleaned),
        extraction_method=ExtractionMethod.JSON_LD if ld else ExtractionMethod.CRAWL4AI,
        extraction_status=extraction_status,
        language=lang,
        http_status=status_code,
    )

    passages: list[Passage] = []
    for idx, (heading, body) in enumerate(chunk_passages(cleaned)):
        passages.append(
            Passage(
                id=f"{doc_id}#p{idx}",
                document_id=doc_id,
                source=Source.DARGLOBAL,
                canonical_url=final_url or url,
                page_title=title,
                section_heading=heading,
                text=body,
                collected_at=now,
                content_hash=content_hash(body),
                language=lang,
            )
        )

    properties: list[Property] = []
    if _is_development_page(url) and cleaned:
        prop = _build_development(url, final_url, title, cleaned, soup, passages, now, html)
        if prop:
            properties.append(prop)
            for p in passages:
                p.property_id = prop.id

    return ExtractedPage(document=document, passages=passages, properties=properties)


def make_id_doc(url: str) -> str:
    path = url[len(BASE):].strip("/") if url.startswith(BASE) else url
    return f"darglobal:doc:{slugify(path or 'home', 100)}"


def _gallery_for_dev(soup, html: str) -> list[str]:
    cover = H.og_image(soup, html)
    rest = H.content_images(html, limit=40)
    seen: set[str] = set()
    out: list[str] = []
    for u in ([cover] if cover else []) + rest:
        if not u:
            continue
        key = u.split("?")[0].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def _build_development(
    url: str,
    final_url: str,
    title: str,
    cleaned: str,
    soup,
    passages: list[Passage],
    now: datetime,
    html: str = "",
) -> Property | None:
    facts = _parse_dg_facts(cleaned)

    price_text = facts.get("starting price") or facts.get("price") or H.guess_price_text(cleaned)
    amount, currency, basis, original_price = parse_price(price_text)
    if amount is not None and basis == PriceBasis.UNSPECIFIED:
        basis = PriceBasis.STARTING  # DarGlobal quotes "starting from" prices

    loc_text = facts.get("location", "")
    country, city = _country_city_from_text(cleaned, url, primary=loc_text, title=title)

    area_text = facts.get("area (sqm)") or facts.get("area (sqm)".lower())
    if area_text:
        area_value, area_unit, original_area = parse_area(f"{area_text} sqm")
        original_area = area_text
    else:
        area_value, area_unit, original_area = parse_area(cleaned)

    bedrooms = _bedrooms_from_unit_text(
        facts.get("unit type", "") + " " + facts.get("units", "")
    ) or parse_bedrooms(cleaned)

    amenities = H.collect_amenities(soup)
    handover = (
        facts.get("expected completion date")
        or facts.get("completion date")
        or facts.get("handover")
    )
    if not handover:
        m = re.search(r"(handover|completion)[^.\n]{0,60}(20\d\d|Q[1-4]\s*20\d\d)", cleaned, re.I)
        if m:
            handover = m.group(0).strip()[:160]

    description = None
    md = H.meta(soup, "description") or H.meta(soup, "og:description")
    if md:
        description = md[:1200]
    elif passages:
        description = passages[0].text[:1200]

    gallery = _gallery_for_dev(soup, html)
    slug = _slug(url)
    prop_id = make_id(Source.DARGLOBAL.value, RecordType.DEVELOPMENT.value, slug)
    evidence = [
        EvidenceRef(passage_id=p.id, document_id=p.document_id, canonical_url=p.canonical_url)
        for p in passages[:4]
    ]
    return Property(
        id=prop_id,
        source=Source.DARGLOBAL,
        source_record_id=slug,
        record_type=RecordType.DEVELOPMENT,
        title=title,
        country=country,
        city=city,
        district=None,
        property_type=(facts.get("property type") or _property_type_from_text(cleaned) or None),
        transaction_type=TransactionType.SALE,
        price_amount=amount,
        price_currency=currency,
        price_basis=basis,
        original_price_text=original_price,
        bedrooms=bedrooms,
        bathrooms=None,
        area_value=area_value,
        area_unit=area_unit,
        original_area_text=original_area,
        amenities=amenities,
        description=description,
        developer="DarGlobal",
        completion_or_handover_text=handover,
        image_url=gallery[0] if gallery else None,
        image_urls=gallery,
        source_url=final_url or url,
        scraped_at=now,
        content_hash=content_hash(cleaned),
        evidence=evidence,
    )
