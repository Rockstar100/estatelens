"""Shared HTML -> structured data helpers (BeautifulSoup + JSON-LD)."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

_STRIP_TAGS = ("script", "style", "noscript", "svg", "template", "iframe")
_NAV_ROLES = {"navigation", "banner", "contentinfo", "search"}


def make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def json_ld_blocks(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # some sites concatenate multiple objects
            try:
                data = json.loads(f"[{raw}]")
            except json.JSONDecodeError:
                continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                out.extend(d for d in data["@graph"] if isinstance(d, dict))
            else:
                out.append(data)
    return out


def find_ld_of_type(blocks: list[dict], *types: str) -> dict | None:
    wanted = {t.lower() for t in types}
    for b in blocks:
        t = b.get("@type")
        names = {t.lower()} if isinstance(t, str) else {x.lower() for x in (t or [])}
        if names & wanted:
            return b
    return None


def json_object_containing(html: str, key: str) -> dict | None:
    """Extract the smallest well-formed JSON object in ``html`` that contains
    ``key`` (given as a quoted string like '"propertyInfo"'). Handles the case
    where framework payloads embed the object inside escaped strings by trying
    an unescaped copy too."""
    for source in (html, html.replace('\\"', '"')):
        idx = source.find(key)
        while idx != -1:
            start = source.rfind("{", 0, idx)
            if start == -1:
                break
            depth = 0
            in_str = False
            esc = False
            for j in range(start, min(len(source), start + 60_000)):
                ch = source[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        frag = source[start : j + 1]
                        try:
                            obj = json.loads(frag)
                            if isinstance(obj, dict) and key.strip('"') in obj:
                                return obj
                        except json.JSONDecodeError:
                            pass
                        break
            idx = source.find(key, idx + 1)
    return None


def next_data(soup: BeautifulSoup) -> dict | None:
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except json.JSONDecodeError:
            return None
    return None


def meta(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return tag.get("content").strip() if tag and tag.get("content") else None


def page_title(soup: BeautifulSoup) -> str | None:
    for getter in (
        lambda: meta(soup, "og:title"),
        lambda: soup.title.get_text(strip=True) if soup.title else None,
        lambda: soup.find("h1").get_text(strip=True) if soup.find("h1") else None,
    ):
        val = getter()
        if val:
            return val[:200]
    return None


def og_image(soup: BeautifulSoup) -> str | None:
    return meta(soup, "og:image")


def visible_text(soup: BeautifulSoup) -> str:
    """Main-content text with nav/header/footer removed."""
    body = soup.body or soup
    for tag in body.find_all(_STRIP_TAGS):
        tag.decompose()
    for tag in body.find_all(["nav", "header", "footer"]):
        tag.decompose()
    for tag in body.find_all(attrs={"role": lambda v: v in _NAV_ROLES if v else False}):
        tag.decompose()
    for tag in body.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    main = body.find("main") or body.find(attrs={"role": "main"}) or body
    lines: list[str] = []
    for el in main.find_all(
        ["h1", "h2", "h3", "h4", "li", "p", "td", "th", "figcaption", "blockquote", "dd", "dt"]
    ):
        txt = " ".join(el.get_text(" ", strip=True).split())
        if txt and len(txt) > 1:
            lines.append(txt)
    if not lines:  # SPA fallback
        lines = [" ".join(main.get_text(" ", strip=True).split())]
    # de-dupe consecutive
    deduped: list[str] = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    return "\n".join(deduped)


def collect_amenities(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for ul in soup.find_all(["ul", "ol"]):
        cls = " ".join(ul.get("class") or []).lower()
        near = (ul.find_previous(["h2", "h3", "h4"]) or ul).get_text(" ", strip=True).lower()
        if any(k in cls or k in near for k in ("amenit", "facilit", "feature", "highlight")):
            for li in ul.find_all("li"):
                t = " ".join(li.get_text(" ", strip=True).split())
                if 2 <= len(t) <= 80:
                    out.append(t)
    # de-dupe, cap
    seen: set[str] = set()
    return [a for a in out if not (a.lower() in seen or seen.add(a.lower()))][:40]


_PRICE_NEAR_RE = re.compile(
    r"(?:price|starting|from|priced?\s+at)[^.\n]{0,40}?"
    r"((?:AED|SAR|USD|GBP|EUR|QAR|\$|£|€)\s?[\d][\d,\.]*\s?(?:k|m|mn|million|billion)?)",
    re.I,
)


def guess_price_text(text: str) -> str | None:
    m = _PRICE_NEAR_RE.search(text)
    if m:
        return m.group(0)[:160]
    m2 = re.search(
        r"(?:AED|SAR|USD|GBP|EUR|QAR)\s?[\d][\d,\.]*\s?(?:k|m|mn|million|billion)?", text, re.I
    )
    return m2.group(0) if m2 else None
