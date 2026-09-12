"""Property explorer + details endpoints. All filters are allow-listed."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import OperationFailure

from app.config import get_settings
from app.db import repo
from app.models.api import PropertyListResponse
from app.models.property import Property
from app.retrieval.filters import PropertyFilter, build_mongo_filter

router = APIRouter(prefix="/properties", tags=["properties"])


@router.get("", response_model=PropertyListResponse)
async def list_properties(
    text: Annotated[str | None, Query(max_length=200)] = None,
    source: Annotated[str | None, Query()] = None,
    record_type: Annotated[str | None, Query()] = None,
    city: Annotated[str | None, Query(max_length=80)] = None,
    country: Annotated[str | None, Query(max_length=80)] = None,
    district: Annotated[str | None, Query(max_length=80)] = None,
    transaction_type: Annotated[str | None, Query()] = None,
    property_type: Annotated[str | None, Query(max_length=80)] = None,
    bedrooms: Annotated[int | None, Query(ge=0, le=50)] = None,
    bedrooms_min: Annotated[int | None, Query(ge=0, le=50)] = None,
    budget_min: Annotated[float | None, Query(ge=0)] = None,
    budget_max: Annotated[float | None, Query(ge=0)] = None,
    currency: Annotated[str | None, Query(max_length=8)] = None,
    price_basis: Annotated[str | None, Query()] = None,
    sort: Annotated[str, Query()] = "relevance",
    page: Annotated[int, Query(ge=1, le=200)] = 1,
    page_size: Annotated[int, Query(ge=1, le=48)] = 12,
) -> PropertyListResponse:
    settings = get_settings()
    page_size = min(page_size, settings.properties_page_size_max)

    try:
        parsed = PropertyFilter.model_validate(
            {
                "text": text,
                "source": source,
                "record_type": record_type,
                "city": city,
                "country": country,
                "district": district,
                "transaction_type": transaction_type,
                "property_type": property_type,
                "bedrooms": bedrooms,
                "bedrooms_min": bedrooms_min,
                "budget_min": budget_min,
                "budget_max": budget_max,
                "currency": currency,
                "price_basis": price_basis,
                "sort": sort,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid filter: {exc}") from exc

    mongo_filter, sort_spec, _notes = build_mongo_filter(parsed)
    if "$text" in mongo_filter and sort_spec is None:
        sort_spec = [("_id", 1)]  # text index needs a deterministic tiebreak with skip/limit
    try:
        items, total = await repo.query_properties(
            mongo_filter, page=page, page_size=page_size, sort=sort_spec
        )
    except OperationFailure as exc:
        # Text index not built yet (e.g. right after a fresh deploy) — fall back
        # to a safe case-insensitive substring match on title/description.
        if "$text" not in mongo_filter or "text index" not in str(exc).lower():
            raise
        term = mongo_filter.pop("$text")["$search"]
        rx = {"$regex": re.escape(term), "$options": "i"}
        mongo_filter["$or"] = [{"title": rx}, {"description": rx}, {"district": rx}]
        items, total = await repo.query_properties(
            mongo_filter, page=page, page_size=page_size,
            sort=None if sort_spec == [("_id", 1)] else sort_spec,
        )
    facets = await repo.property_facets()
    return PropertyListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
        facets=facets,
    )


@router.get("/{property_id}", response_model=Property)
async def get_property(property_id: str) -> Property:
    if len(property_id) > 200:
        raise HTTPException(status_code=422, detail="id too long")
    prop = await repo.get_property(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


_ALLOWED_IMAGE_HOSTS = (
    "imagedelivery.net",
    "cdn.darglobal.co.uk",
    "cdn.wasalt.sa",
    "cdn.wasalt.com",
    "assets.wasalt.com",
)


def _safe_image_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    if "undefined" in url or "/null/" in url:
        return None
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return None
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_IMAGE_HOSTS):
        return None
    return url


@router.get("/{property_id}/image")
async def property_image(property_id: str):
    """Same-origin photo for cards. Looks up the live DB URL so chat history
    from before image backfill still renders, and proxies bytes so CDN / referrer
    quirks cannot blank the thumbnails.

    When no usable cover exists, return a tiny SVG placeholder (200) instead of
    404 so list views don't spam the logs with missing-photo noise.
    """
    from fastapi.responses import Response
    import httpx

    if len(property_id) > 200:
        raise HTTPException(status_code=422, detail="id too long")
    prop = await repo.get_property(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    def _placeholder() -> Response:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0%" stop-color="#e8ebe6"/><stop offset="100%" stop-color="#dde3dc"/>'
            "</linearGradient></defs>"
            '<rect width="640" height="400" fill="url(#g)"/>'
            '<text x="320" y="210" text-anchor="middle" fill="#8a9488" '
            'font-family="system-ui,sans-serif" font-size="18">No photo</text>'
            "</svg>"
        )
        return Response(
            content=svg.encode("utf-8"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    url = _safe_image_url(prop.image_url)
    if not url and prop.image_urls:
        for candidate in prop.image_urls:
            url = _safe_image_url(candidate)
            if url:
                break
    if not url:
        return _placeholder()

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
            upstream = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
    except Exception:  # noqa: BLE001
        return _placeholder()

    if upstream.status_code != 200 or not upstream.content:
        return _placeholder()

    ctype = upstream.headers.get("content-type", "image/jpeg")
    if not ctype.startswith("image/"):
        return _placeholder()

    return Response(
        content=upstream.content,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )
