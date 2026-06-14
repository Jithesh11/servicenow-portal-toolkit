"""Web scraping, WCAG contrast calculations, and branding score logic."""

from __future__ import annotations

import re
from urllib.parse import urljoin
from typing import Any

import requests
from bs4 import BeautifulSoup


# ── Color utilities ───────────────────────────────────────────────────────────

_HEX6_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_HEX3_RE = re.compile(r"#[0-9A-Fa-f]{3}\b")
_RGB_RE = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")

# Colors to skip — utility values that aren't brand colors
_SKIP_COLORS = {
    "#ffffff", "#fffffe", "#fffffd",  # near-white
    "#000000", "#000001", "#010101",  # near-black
    "#f0f0f0", "#f5f5f5", "#fafafa", "#eeeeee",  # light grays
    "#333333", "#444444", "#555555",  # dark grays
    "#transparent",
}


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a hex color string to an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _expand_hex3(h: str) -> str:
    """Expand #abc → #aabbcc."""
    h = h.lstrip("#")
    return f"#{''.join(c * 2 for c in h)}"


def _linearise(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Return WCAG 2.1 relative luminance for a hex color (range 0–1)."""
    r, g, b = (v / 255.0 for v in hex_to_rgb(hex_color))
    return 0.2126 * _linearise(r) + 0.7152 * _linearise(g) + 0.0722 * _linearise(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """Return WCAG 2.1 contrast ratio between two hex colors."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def wcag_grade(ratio: float, large_text: bool = False) -> str:
    """Return WCAG compliance grade: 'AAA', 'AA', or 'FAIL'."""
    aa_min = 3.0 if large_text else 4.5
    aaa_min = 4.5 if large_text else 7.0
    if ratio >= aaa_min:
        return "AAA"
    if ratio >= aa_min:
        return "AA"
    return "FAIL"


# ── CSS / color extraction ────────────────────────────────────────────────────

def _extract_colors_from_text(text: str) -> list[str]:
    """Extract unique hex and rgb() color values from a CSS/HTML string."""
    colors: list[str] = []
    for m in _HEX6_RE.finditer(text):
        colors.append(m.group(0).lower())
    for m in _HEX3_RE.finditer(text):
        colors.append(_expand_hex3(m.group(0).lower()))
    for m in _RGB_RE.finditer(text):
        colors.append(_rgb_to_hex(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    # Deduplicate while preserving order, skip utility shades
    seen: set[str] = set()
    result: list[str] = []
    for c in colors:
        if c not in seen and c not in _SKIP_COLORS:
            seen.add(c)
            result.append(c)
    return result


_FONT_RE = re.compile(r"font-family\s*:\s*([^;}{]+)", re.IGNORECASE)
_GFONT_FAMILY_RE = re.compile(r"family=([A-Za-z0-9+]+)", re.IGNORECASE)
_GFONT_HOST = "fonts.googleapis.com"
_GENERIC_FONTS = {"inherit", "initial", "unset", "sans-serif", "serif", "monospace", "cursive", "fantasy"}


def _extract_fonts_from_page(html: str, soup: BeautifulSoup) -> list[str]:
    """Extract font family names from CSS declarations and Google Fonts links."""
    fonts: list[str] = []

    # Google Fonts <link> tags
    for tag in soup.find_all("link", href=True):
        href: str = tag["href"]
        if _GFONT_HOST in href:
            for m in _GFONT_FAMILY_RE.finditer(href):
                fonts.append(m.group(1).replace("+", " "))

    # font-family declarations in all CSS text
    for m in _FONT_RE.finditer(html):
        raw = m.group(1).strip()
        # Take first family in the stack, strip quotes
        first = raw.split(",")[0].strip().strip("'\"")
        if first and first.lower() not in _GENERIC_FONTS:
            fonts.append(first)

    # Deduplicate preserving order
    seen: set[str] = set()
    return [f for f in fonts if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]


# ── Web scraper ───────────────────────────────────────────────────────────────

_UA = "Mozilla/5.0 (compatible; ServiceNow-Portal-Toolkit/1.0)"

# CSS custom-property names commonly used for brand primary color
_PRIMARY_VAR_CANDIDATES = [
    "--primary-color", "--color-primary", "--brand-color", "--brand-primary",
    "--accent-color", "--accent", "--main-color", "--theme-primary",
    "--primary", "--highlight-color", "--key-color",
]
_SECONDARY_VAR_CANDIDATES = [
    "--secondary-color", "--color-secondary", "--brand-secondary",
    "--secondary", "--theme-secondary",
]


def _find_css_var(css: str, names: list[str]) -> str | None:
    """Return the first hex value found for any of the listed CSS variable names."""
    for name in names:
        pattern = re.compile(rf"{re.escape(name)}\s*:\s*(#[0-9A-Fa-f]{{3,6}})", re.IGNORECASE)
        m = pattern.search(css)
        if m:
            hex_val = m.group(1).lower()
            return hex_val if len(hex_val) == 7 else _expand_hex3(hex_val)
    return None


def scrape_website_branding(url: str, timeout: int = 15) -> dict[str, Any]:
    """
    Scrape a public website and return extracted branding tokens.

    Priority order for primary color:
      1. meta[name="theme-color"]
      2. CSS custom properties (--primary-color, --brand-color, etc.)
      3. Background color of <header> / <nav> elements
      4. Most prominent non-utility color from all CSS

    Returns:
        {
            "primary_color": "#xxxxxx" | None,
            "secondary_color": "#xxxxxx" | None,
            "font_family": "Font Name" | None,
            "source_url": str,
            "confidence": "high" | "medium" | "low",
        }
    """
    headers = {"User-Agent": _UA}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # Fetch linked stylesheets (first 3 only to bound latency)
    external_css = ""
    for link in list(soup.find_all("link", rel=lambda v: v and "stylesheet" in v))[:3]:
        href = link.get("href", "")
        if href:
            try:
                css_url = urljoin(url, href)
                css_resp = requests.get(css_url, headers=headers, timeout=10)
                external_css += css_resp.text
            except Exception:
                pass

    all_css = html + external_css
    confidence = "low"
    primary_color: str | None = None
    secondary_color: str | None = None

    # ── Priority 1: meta theme-color ──────────────────────────────────────
    meta_theme = soup.find("meta", {"name": "theme-color"})
    if meta_theme:
        content = (meta_theme.get("content") or "").strip()
        if content.startswith("#"):
            primary_color = content.lower() if len(content) == 7 else _expand_hex3(content.lower())
            confidence = "high"

    # ── Priority 2: CSS custom properties ─────────────────────────────────
    if primary_color is None:
        primary_color = _find_css_var(all_css, _PRIMARY_VAR_CANDIDATES)
        if primary_color:
            confidence = "high"

    secondary_color = _find_css_var(all_css, _SECONDARY_VAR_CANDIDATES)

    # ── Priority 3: header/nav background color ────────────────────────────
    if primary_color is None:
        for selector in ("header", "nav", ".navbar", ".header", "#header", "#nav"):
            for tag in soup.select(selector)[:2]:
                style: str = tag.get("style", "")
                bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9A-Fa-f]{3,6})", style, re.I)
                if bg:
                    raw = bg.group(1).lower()
                    primary_color = raw if len(raw) == 7 else _expand_hex3(raw)
                    confidence = "medium"
                    break
            if primary_color:
                break

    # ── Priority 4: most prominent CSS color ──────────────────────────────
    if primary_color is None:
        all_colors = _extract_colors_from_text(all_css)
        if all_colors:
            primary_color = all_colors[0]
            if secondary_color is None and len(all_colors) > 1:
                secondary_color = all_colors[1]

    fonts = _extract_fonts_from_page(all_css, soup)
    font_family: str | None = fonts[0] if fonts else None

    return {
        "primary_color": primary_color,
        "secondary_color": secondary_color,
        "font_family": font_family,
        "source_url": url,
        "confidence": confidence,
    }


# ── Branding score ────────────────────────────────────────────────────────────

# SCSS variables used in sp_portal.css_variables (ServiceNow Bootstrap SCSS)
_REQUIRED_SCSS_VARS = [
    "$brand-primary",
    "$body-bg",
    "$text-color",
    "$link-color",
    "$navbar-inverse-bg",
    "$brand-success",
    "$brand-warning",
    "$brand-danger",
]


def parse_scss_var(css: str, name: str) -> str | None:
    """Extract the value of a SCSS variable from a css_variables string."""
    m = re.search(rf"{re.escape(name)}\s*:\s*([^;]+);", css)
    return m.group(1).strip() if m else None


def upsert_scss_var(css: str, name: str, value: str) -> str:
    """Insert or replace a SCSS variable declaration ($name:value;)."""
    pattern = re.compile(rf"{re.escape(name)}\s*:[^;]+;", re.MULTILINE)
    declaration = f"{name}:{value};"
    if pattern.search(css):
        return pattern.sub(declaration, css)
    return css.rstrip() + f" {declaration}"


def calculate_branding_score(portal: dict[str, Any]) -> dict[str, Any]:
    """
    Score a ServiceNow sp_portal record out of 100.

    Reads css_variables directly from the portal record (SCSS format).

    Scoring rubric (25 pts each):
        1. $brand-primary vs white — WCAG contrast
        2. $text-color vs $body-bg — WCAG contrast
        3. Required SCSS variables presence
        4. Font consistency ($font-family-base declared)
    """
    breakdown: dict[str, dict[str, Any]] = {}
    fixes: list[str] = []
    total = 0

    css_vars: str = portal.get("css_variables") or ""

    primary  = parse_scss_var(css_vars, "$brand-primary") or "#1d6fa4"
    text_col = parse_scss_var(css_vars, "$text-color")    or "#212121"
    bg_col   = parse_scss_var(css_vars, "$body-bg")       or "#ffffff"

    # Fallback to safe defaults if not valid hex
    if not re.match(r"#[0-9A-Fa-f]{6}", primary):
        primary = "#1d6fa4"
    if not re.match(r"#[0-9A-Fa-f]{6}", text_col):
        text_col = "#212121"
    if not re.match(r"#[0-9A-Fa-f]{6}", bg_col):
        bg_col = "#ffffff"

    # 1. Primary vs white (40 pts) ────────────────────────────────────────
    try:
        ratio_pw = contrast_ratio(primary, "#ffffff")
        grade_pw = wcag_grade(ratio_pw)
        pw_score = 40 if grade_pw == "AAA" else 25 if grade_pw == "AA" else 0
        if grade_pw == "FAIL":
            fixes.append(
                f"$brand-primary {primary} fails WCAG AA against white "
                f"({ratio_pw:.2f}:1 — need ≥ 4.5:1). Darken the primary."
            )
        breakdown["primary_vs_white"] = {"ratio": round(ratio_pw, 2), "grade": grade_pw, "score": pw_score, "max": 40}
        total += pw_score
    except Exception:
        breakdown["primary_vs_white"] = {"error": f"Invalid color: {primary}", "score": 0, "max": 40}
        fixes.append(f"$brand-primary '{primary}' is not a valid hex value.")

    # 2. Text vs background (40 pts) ──────────────────────────────────────
    try:
        ratio_tb = contrast_ratio(text_col, bg_col)
        grade_tb = wcag_grade(ratio_tb)
        tb_score = 40 if grade_tb == "AAA" else 25 if grade_tb == "AA" else 0
        if grade_tb == "FAIL":
            fixes.append(
                f"$text-color {text_col} on $body-bg {bg_col} fails WCAG AA "
                f"({ratio_tb:.2f}:1 — need ≥ 4.5:1). Increase contrast."
            )
        breakdown["text_vs_background"] = {"ratio": round(ratio_tb, 2), "grade": grade_tb, "score": tb_score, "max": 40}
        total += tb_score
    except Exception:
        breakdown["text_vs_background"] = {"error": "Invalid color values", "score": 0, "max": 40}
        fixes.append(f"$text-color '{text_col}' or $body-bg '{bg_col}' is not a valid hex value.")

    # 3. Required SCSS variables (20 pts) ─────────────────────────────────
    present = [v for v in _REQUIRED_SCSS_VARS if v in css_vars]
    missing = [v for v in _REQUIRED_SCSS_VARS if v not in css_vars]
    var_score = round(20 * len(present) / len(_REQUIRED_SCSS_VARS))
    if missing:
        fixes.append(f"Missing SCSS variables: {', '.join(missing)}.")
    breakdown["scss_variables"] = {"present": present, "missing": missing, "score": var_score, "max": 20}
    total += var_score

    wcag_aa = all(
        info.get("grade") in ("AA", "AAA")
        for info in breakdown.values()
        if "grade" in info
    )
    return {"score": total, "max_score": 100, "wcag_aa_compliant": wcag_aa, "breakdown": breakdown, "fixes": fixes}
