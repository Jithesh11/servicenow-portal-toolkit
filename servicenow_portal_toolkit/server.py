"""FastMCP server — exposes all four ServiceNow Portal tools."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

from .branding import (
    calculate_branding_score,
    contrast_ratio,
    scrape_website_branding,
    upsert_scss_var,
    parse_scss_var,
    wcag_grade,
)
from .analytics import get_portal_analytics_data

# Load credentials: ~/.servicenow-portal-toolkit/.env takes precedence over cwd .env
_CFG_ENV = Path.home() / ".servicenow-portal-toolkit" / ".env"
load_dotenv(_CFG_ENV)
load_dotenv()

mcp = FastMCP(
    "servicenow-portal-toolkit",
    instructions=(
        "Tools for ServiceNow Service Portal administration. "
        "Use list_portals to discover portals, apply_branding to push a new theme "
        "(with automatic WCAG contrast checks and a before-snapshot), "
        "branding_score to audit the current theme, and portal_analytics for UX insights."
    ),
)


# ── ServiceNow API helpers ────────────────────────────────────────────────────

def _creds() -> tuple[str, str, str]:
    inst = os.getenv("SNOW_INSTANCE", "").strip()
    user = os.getenv("SNOW_USER", "").strip()
    pwd = os.getenv("SNOW_PASS", "").strip()
    if not (inst and user and pwd):
        raise RuntimeError(
            "ServiceNow credentials not configured. "
            "Run `servicenow-portal-toolkit setup` to set SNOW_INSTANCE, SNOW_USER, SNOW_PASS."
        )
    return inst, user, pwd


def _snow_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inst, user, pwd = _creds()
    url = f"https://{inst}.service-now.com/api/now/{path}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    resp = requests.request(
        method, url,
        auth=(user, pwd),
        headers=headers,
        params=params,
        json=body,
        timeout=30,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("detail", "")
        except Exception:
            pass
        raise RuntimeError(
            f"ServiceNow API {resp.status_code}: {exc}. {detail}"
        ) from exc
    return resp.json()  # type: ignore[no-any-return]


def _snow_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _snow_request("GET", path, params=params)


def _snow_patch(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _snow_request("PATCH", path, body=body)


def _resolve_portal(url_suffix: str) -> tuple[str, str]:
    """Return (portal_name, portal_sys_id) or raise."""
    data = _snow_get("table/sp_portal", {
        "sysparm_query": f"url_suffix={url_suffix}",
        "sysparm_fields": "title,name,sys_id",
        "sysparm_limit": 1,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
    })
    results = data.get("result", [])
    if not results:
        raise ValueError(f"No portal found with URL suffix '{url_suffix}'.")

    portal = results[0]
    portal_name: str = portal.get("title") or portal.get("name") or url_suffix
    portal_sys_id: str = portal.get("sys_id", "")
    return portal_name, portal_sys_id


# ── Tool 1: list_portals ──────────────────────────────────────────────────────

@mcp.tool()
def list_portals(active_only: bool = True) -> str:
    """
    Fetch all Service Portals from the sp_portal table.

    Returns name, URL suffix, linked theme, and active status for each portal.

    Args:
        active_only: When True (default), return only active portals.
    """
    params: dict[str, Any] = {
        "sysparm_fields": "title,url_suffix,theme,inactive,sys_id,description",
        "sysparm_limit": 200,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
        "sysparm_suppress_pagination_header": "true",
        "sysparm_query": "inactive=false^ORDERBYtitle" if active_only else "ORDERBYtitle",
    }

    data = _snow_get("table/sp_portal", params)
    portals = data.get("result", [])

    if not portals:
        return "No portals found (try active_only=False to include inactive portals)."

    lines: list[str] = [f"## Service Portals — {len(portals)} found\n"]
    for p in portals:
        theme = p.get("theme", "")
        theme_label = theme.get("display_value", "None") if isinstance(theme, dict) else (theme or "None")
        is_active = str(p.get("inactive", "")).lower() in ("false", "1")
        status = "Active" if is_active else "Inactive"
        lines.append(
            f"### {p.get('title') or p.get('name') or 'Unnamed Portal'}\n"
            f"- **URL Suffix** : `/{p.get('url_suffix', '')}`\n"
            f"- **Theme**      : {theme_label}\n"
            f"- **Status**     : {status}\n"
        )
        desc = (p.get("description") or "").strip()
        if desc:
            lines.append(f"- **Description**: {desc}\n")

    return "\n".join(lines)


# ── Tool 2: apply_branding ────────────────────────────────────────────────────

@mcp.tool()
def apply_branding(
    portal_url_suffix: str,
    source_url: Optional[str] = None,
    # Brand colors
    primary_color: Optional[str] = None,
    secondary_color: Optional[str] = None,
    success_color: Optional[str] = None,
    warning_color: Optional[str] = None,
    danger_color: Optional[str] = None,
    info_color: Optional[str] = None,
    # Background colors
    background_color: Optional[str] = None,
    homepage_bg: Optional[str] = None,
    panel_bg: Optional[str] = None,
    btn_default_bg: Optional[str] = None,
    # Navbar
    header_bg_color: Optional[str] = None,
    navbar_link_color: Optional[str] = None,
    navbar_link_hover_color: Optional[str] = None,
    navbar_divider_color: Optional[str] = None,
    # Text colors
    text_color: Optional[str] = None,
    text_muted: Optional[str] = None,
    link_color: Optional[str] = None,
    tagline_color: Optional[str] = None,
    state_success_text: Optional[str] = None,
    # Flags
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """
    Apply SCSS branding variables to a ServiceNow portal's css_variables field.

    Mode A — Auto (provide source_url): scrapes URL to extract primary color,
    secondary color, then applies them.

    Mode B — Manual: supply any combination of the parameters below.

    WCAG 2.1 AA contrast is checked before writing (primary vs white, text vs bg).

    Args:
        portal_url_suffix:      URL suffix of the target portal (e.g. "sp").
        source_url:             Public URL to scrape for branding tokens (Mode A).
        primary_color:          $brand-primary — main brand color.
        secondary_color:        $brand-secondary — secondary brand color.
        success_color:          $brand-success — success state color.
        warning_color:          $brand-warning — warning state color.
        danger_color:           $brand-danger — danger/error state color.
        info_color:             $brand-info — info state color.
        background_color:       $body-bg — page background color.
        homepage_bg:            $sp-homepage-bg — homepage background.
        panel_bg:               $panel-bg — card/panel background.
        btn_default_bg:         $btn-default-bg — default button background.
        header_bg_color:        $navbar-inverse-bg — navbar background.
        navbar_link_color:      $navbar-inverse-link-color — navbar link color.
        navbar_link_hover_color: $navbar-inverse-link-hover-color — navbar link hover.
        navbar_divider_color:   $sp-navbar-divider-color — navbar divider color.
        text_color:             $text-color — body text color.
        text_muted:             $text-muted — muted/secondary text color.
        link_color:             $link-color — hyperlink color.
        tagline_color:          $sp-tagline-color — portal tagline text color.
        state_success_text:     $state-success-text — success message text color.
        dry_run:                Report what would change without writing to ServiceNow.
        force:                  Skip WCAG block and apply even if contrast checks fail (a warning is shown).
    """
    lines: list[str] = []

    # ── 1. Resolve portal ─────────────────────────────────────────────────
    try:
        portal_name, portal_sys_id = _resolve_portal(portal_url_suffix)
    except ValueError as exc:
        return str(exc)

    lines.append(f"## Branding Update — {portal_name} (`/{portal_url_suffix}`)\n")

    # ── 2. Snapshot current css_variables from sp_portal ─────────────────
    portal_data = _snow_get(f"table/sp_portal/{portal_sys_id}", {
        "sysparm_fields": "css_variables,title",
    })
    current = portal_data.get("result", {})
    existing_vars: str = current.get("css_variables") or ""
    snapshot = {
        "$brand-primary":     parse_scss_var(existing_vars, "$brand-primary"),
        "$body-bg":           parse_scss_var(existing_vars, "$body-bg"),
        "$text-color":        parse_scss_var(existing_vars, "$text-color"),
        "$navbar-inverse-bg": parse_scss_var(existing_vars, "$navbar-inverse-bg"),
        "$link-color":        parse_scss_var(existing_vars, "$link-color"),
        "css_variables_preview": existing_vars[:400],
    }
    lines.append("### Snapshot (before)\n```json\n" + json.dumps(snapshot, indent=2) + "\n```\n")

    # ── 3. Resolve branding tokens ────────────────────────────────────────
    if source_url:
        lines.append(f"Scraping `{source_url}` for branding tokens…\n")
        try:
            scraped = scrape_website_branding(source_url)
        except Exception as exc:
            return "\n".join(lines) + f"\nFailed to scrape {source_url}: {exc}"

        lines.append(
            f"**Extraction confidence**: {scraped['confidence']}\n"
            f"- Primary color  : `{scraped.get('primary_color') or 'not detected'}`\n"
            f"- Secondary color: `{scraped.get('secondary_color') or 'not detected'}`\n"
            f"- Font family    : `{scraped.get('font_family') or 'not detected'}`\n"
        )
        if scraped.get("primary_color") and not primary_color:
            primary_color = scraped["primary_color"]
        if scraped.get("secondary_color") and not secondary_color:
            secondary_color = scraped["secondary_color"]

    if not primary_color:
        return "\n".join(lines) + "\nNo primary color provided or extracted. " \
               "Provide source_url or primary_color and retry."

    # ── 4. WCAG contrast checks ───────────────────────────────────────────
    _bg = background_color or "#ffffff"
    _text = text_color or "#212121"
    lines.append("### WCAG 2.1 Contrast Checks\n")
    all_pass = True
    checks: list[tuple[str, str, str]] = [
        (primary_color, "#ffffff", "Primary on White"),
        (primary_color, _bg, "Primary on Page Background"),
        (_text, _bg, "Body Text on Background"),
    ]
    if header_bg_color:
        checks.append(("#ffffff", header_bg_color, "White Text on Header BG"))

    for fg, bg, label in checks:
        try:
            ratio = contrast_ratio(fg, bg)
            grade = wcag_grade(ratio)
            icon = "✓" if grade != "FAIL" else "✗"
            lines.append(f"- {icon} **{label}**: {ratio:.2f}:1 — WCAG {grade}")
            if grade == "FAIL":
                all_pass = False
        except Exception as exc:
            lines.append(f"- ? **{label}**: calculation error ({exc})")
            all_pass = False

    lines.append("")
    if not all_pass:
        if force:
            lines.append(
                "> **Warning**: One or more color pairs fail WCAG AA. "
                "Applying anyway because `force=True`.\n"
            )
        else:
            lines.append(
                "> **Blocked**: One or more color pairs fail WCAG AA. "
                "No changes were written. Adjust colors, set `dry_run=True` to preview, "
                "or set `force=True` to apply anyway.\n"
            )
            return "\n".join(lines)

    # ── 5. Build updated css_variables (SCSS format) ──────────────────────
    # Map: parameter → SCSS variable name
    var_map: list[tuple[Optional[str], str]] = [
        (primary_color,           "$brand-primary"),
        (secondary_color,         "$brand-secondary"),
        (success_color,           "$brand-success"),
        (warning_color,           "$brand-warning"),
        (danger_color,            "$brand-danger"),
        (info_color,              "$brand-info"),
        (background_color,        "$body-bg"),
        (homepage_bg,             "$sp-homepage-bg"),
        (panel_bg,                "$panel-bg"),
        (btn_default_bg,          "$btn-default-bg"),
        (header_bg_color,         "$navbar-inverse-bg"),
        (navbar_link_color,       "$navbar-inverse-link-color"),
        (navbar_link_hover_color, "$navbar-inverse-link-hover-color"),
        (navbar_divider_color,    "$sp-navbar-divider-color"),
        (text_color,              "$text-color"),
        (text_muted,              "$text-muted"),
        (link_color,              "$link-color"),
        (tagline_color,           "$sp-tagline-color"),
        (state_success_text,      "$state-success-text"),
    ]

    new_vars = existing_vars
    changes: dict[str, str] = {}
    for value, scss_name in var_map:
        if value:
            new_vars = upsert_scss_var(new_vars, scss_name, value)
            changes[scss_name] = value

    lines.append("### SCSS Variables to Apply\n```json\n" + json.dumps(changes, indent=2) + "\n```\n")

    if dry_run:
        lines.append("> **Dry run** — no changes written to ServiceNow.\n")
        return "\n".join(lines)

    # ── 6. Patch sp_portal directly ───────────────────────────────────────
    _snow_patch(f"table/sp_portal/{portal_sys_id}", {"css_variables": new_vars})
    lines.append(
        "**Branding applied successfully.**  \n"
        "Clear the portal cache in ServiceNow (Service Portal → Portals → Cache) to see changes."
    )
    return "\n".join(lines)


# ── Tool 3: branding_score ────────────────────────────────────────────────────

@mcp.tool()
def branding_score(portal_url_suffix: str) -> str:
    """
    Audit the current branding of a ServiceNow portal and return a score out of 100.

    Checks:
      - WCAG 2.1 AA contrast: primary color vs white
      - WCAG 2.1 AA contrast: body text vs background
      - Required CSS variable coverage (7 variables)
      - Font consistency (custom web font declared)

    Args:
        portal_url_suffix: URL suffix of the portal to audit (e.g. "sp").

    Returns a scored report with category breakdown and an actionable fix list.
    """
    try:
        portal_name, portal_sys_id = _resolve_portal(portal_url_suffix)
    except ValueError as exc:
        return str(exc)

    # Read css_variables directly from sp_portal record
    portal_data = _snow_get(f"table/sp_portal/{portal_sys_id}", {
        "sysparm_fields": "css_variables,title",
    })
    portal = portal_data.get("result", {})

    result = calculate_branding_score(portal)
    score: int = result["score"]
    wcag_ok: bool = result["wcag_aa_compliant"]
    breakdown: dict[str, Any] = result["breakdown"]
    fixes: list[str] = result["fixes"]

    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    wcag_badge = "WCAG AA ✓" if wcag_ok else "WCAG AA ✗"

    lines: list[str] = [
        f"## Branding Score — {portal_name}",
        f"**{score}/100** · Grade {grade} · {wcag_badge}\n",
        "### Category Breakdown\n",
    ]

    label_map = {
        "primary_vs_white": "Primary vs White",
        "text_vs_background": "Text vs Background",
        "scss_variables": "SCSS Variable Coverage",
    }

    for key, info in breakdown.items():
        label = label_map.get(key, key.replace("_", " ").title())
        s, m = info.get("score", 0), info.get("max", 25)
        filled = round(s / m * 10) if m else 0
        bar = "█" * filled + "░" * (10 - filled)

        detail = ""
        if "ratio" in info:
            detail = f" — {info['ratio']}:1 · WCAG {info.get('grade', '?')}"
        elif "font_family_base" in info:
            detail = f" — `{info['font_family_base']}`"
        elif "missing" in info:
            n_present = len(info.get("present", []))
            n_total = n_present + len(info.get("missing", []))
            detail = f" — {n_present}/{n_total} vars present"

        lines.append(f"- **{label}**: {s}/{m} `{bar}`{detail}")

    if fixes:
        lines.append("\n### Fixes Required\n")
        for i, fix in enumerate(fixes, 1):
            lines.append(f"{i}. {fix}")
    else:
        lines.append("\n_No fixes required — excellent branding!_")

    return "\n".join(lines)


# ── Tool 4: portal_analytics ──────────────────────────────────────────────────

@mcp.tool()
def portal_analytics(portal_url_suffix: str, sample_limit: int = 1000) -> str:
    """
    Pull portal usage data from the sp_log table (page views + searches).

    Returns:
      - Top 10 most visited pages
      - Top 10 search terms
      - Top 10 zero-result searches (content gaps)
      - Key metric callouts with UX recommendations

    Args:
        portal_url_suffix: URL suffix of the portal (e.g. "sp" or "esc").
        sample_limit:      Max records to sample per query (100–5000, default 1000).
    """
    portal_url_suffix = (portal_url_suffix or "").strip().lstrip("/")
    if not portal_url_suffix:
        return (
            "Error: portal_url_suffix is required.\n"
            "Pass the URL suffix of your portal, e.g. portal_analytics(portal_url_suffix='sp').\n"
            "Use list_portals() to see all available portals and their URL suffixes."
        )

    limit = min(max(sample_limit, 100), 5000)

    try:
        data = get_portal_analytics_data(_snow_get, portal_url_suffix, limit=limit)
    except ValueError as exc:
        return f"Error: {exc}"

    summary = data["summary"]
    top_pages: list[dict[str, Any]] = data["top_pages"]
    top_searches: list[dict[str, Any]] = data["top_searches"]
    zero_results: list[dict[str, Any]] = data["zero_result_searches"]

    lines: list[str] = [
        f"## Portal Analytics — `/{portal_url_suffix}`\n",
        f"Sample: **{summary['total_page_views_sampled']:,}** page views · "
        f"**{summary['total_searches_sampled']:,}** searches\n",
    ]

    # Top pages
    lines.append("### Top 10 Pages by Views\n")
    if top_pages and "error" not in top_pages[0]:
        for i, p in enumerate(top_pages, 1):
            lines.append(f"{i:>2}. `{p['page']}` — {p['views']:,} views")
    elif not top_pages:
        lines.append("_No page view data found for this portal._")
    else:
        err = top_pages[0].get("error", "unknown")
        lines.append(f"_Could not retrieve page views: {err}_")

    # Top searches
    lines.append("\n### Top 10 Search Terms\n")
    if top_searches and "error" not in top_searches[0]:
        for i, s in enumerate(top_searches, 1):
            lines.append(f'{i:>2}. "{s["term"]}" — {s["searches"]:,} searches')
    elif not top_searches:
        lines.append("_No search data found — users may not have searched yet._")
    else:
        err = top_searches[0].get("error", "unknown")
        lines.append(f"_Could not retrieve search logs: {err}_")

    # Zero-result searches
    lines.append("\n### Zero-Result Searches (Content Gaps)\n")
    if zero_results:
        for i, s in enumerate(zero_results, 1):
            lines.append(f'{i:>2}. "{s["term"]}" — {s["searches"]:,} searches, 0 results')
    else:
        lines.append("_No zero-result searches in sample._")

    # Key metrics + UX recommendations
    zero_pct: float = summary.get("zero_result_pct", 0)

    lines.append("\n### Key Metrics & UX Recommendations\n")
    lines.append(f"- **Zero-result rate** : {zero_pct}%")

    if top_searches and "error" not in top_searches[0]:
        if zero_pct > 20:
            lines.append(
                "\n> **Content gap**: {:.0f}% of searches yield no results. "
                "Expand KB articles for the top zero-result terms above, "
                "or configure search synonyms in ServiceNow.".format(zero_pct)
            )
        elif zero_pct <= 5:
            lines.append("\n> **Search health**: Excellent — zero-result rate below 5%.")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
