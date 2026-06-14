"""Portal usage analytics — queries sp_log via Table API.

sp_log stores both page views (type='Page View') and searches (type='Search').
pa_page_view is a Performance Analytics table that doesn't exist on PDIs.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable


def _fetch_records(
    snow_get: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    table: str,
    query: str,
    fields: list[str],
    limit: int = 1000,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "sysparm_query": query,
        "sysparm_fields": ",".join(fields),
        "sysparm_limit": limit,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
        "sysparm_suppress_pagination_header": "true",
    }
    resp = snow_get(f"table/{table}", params)
    return resp.get("result", [])


def _display_val(field: Any) -> str:
    """Extract a string value whether the field is a plain string or display_value dict."""
    if isinstance(field, dict):
        return field.get("display_value", "") or ""
    return str(field or "")


def get_portal_analytics_data(
    snow_get: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    portal_url_suffix: str,
    limit: int = 1000,
) -> dict[str, Any]:
    """
    Aggregate portal usage data from the sp_log table.

    sp_log records both page views (type='Page View') and search events
    (type='Search') via the portal reference field.

    Args:
        snow_get: Callable matching ServiceNow GET helper signature.
        portal_url_suffix: URL suffix of the target portal (e.g. "sp").
        limit: Max records to sample per query (default 1000).

    Returns:
        {
            "top_pages": [...],
            "top_searches": [...],
            "zero_result_searches": [...],
            "summary": {...},
        }
    """
    portal_url_suffix = (portal_url_suffix or "").strip().lstrip("/")
    if not portal_url_suffix:
        raise ValueError(
            "portal_url_suffix is required — pass the URL suffix of your portal "
            "(e.g. 'sp' for /sp, 'esc' for /esc)."
        )

    base_query = f"portal.url_suffix={portal_url_suffix}"

    # ── Page views (sp_log type='Page View') ─────────────────────────────────
    top_pages: list[dict[str, Any]] = []
    total_page_views = 0

    try:
        page_records = _fetch_records(
            snow_get,
            "sp_log",
            f"type=Page View^{base_query}^ORDERBYDESCsys_created_on",
            ["page", "sys_created_on"],
            limit=limit,
        )
        page_counter: Counter[str] = Counter()
        for rec in page_records:
            page = _display_val(rec.get("page")).strip()
            if page:
                page_counter[page] += 1

        total_page_views = sum(page_counter.values())
        top_pages = [
            {"page": page, "views": count}
            for page, count in page_counter.most_common(10)
        ]
    except Exception as exc:
        top_pages = [{"error": str(exc)}]

    # ── Search logs (sp_log type='Search') ───────────────────────────────────
    top_searches: list[dict[str, Any]] = []
    zero_result_searches: list[dict[str, Any]] = []
    total_searches = 0

    try:
        search_records = _fetch_records(
            snow_get,
            "sp_log",
            f"type=Search^{base_query}^ORDERBYDESCsys_created_on",
            ["text", "count", "sys_created_on"],
            limit=limit,
        )
        search_counter: Counter[str] = Counter()
        zero_counter: Counter[str] = Counter()

        for rec in search_records:
            term = _display_val(rec.get("text")).strip().lower()
            if not term:
                continue
            try:
                result_count = int(rec.get("count") or -1)
            except (TypeError, ValueError):
                result_count = -1

            search_counter[term] += 1
            if result_count == 0:
                zero_counter[term] += 1

        total_searches = sum(search_counter.values())
        top_searches = [
            {"term": term, "searches": count}
            for term, count in search_counter.most_common(10)
        ]
        zero_result_searches = [
            {"term": term, "searches": count}
            for term, count in zero_counter.most_common(10)
        ]
    except Exception as exc:
        top_searches = [{"error": str(exc)}]

    # ── Summary ───────────────────────────────────────────────────────────────
    total_zero = sum(s["searches"] for s in zero_result_searches if "searches" in s)
    zero_pct = round(100 * total_zero / total_searches, 1) if total_searches else 0.0

    summary: dict[str, Any] = {
        "portal": portal_url_suffix,
        "total_page_views_sampled": total_page_views,
        "total_searches_sampled": total_searches,
        "zero_result_count": total_zero,
        "zero_result_pct": zero_pct,
    }

    return {
        "top_pages": top_pages,
        "top_searches": top_searches,
        "zero_result_searches": zero_result_searches,
        "summary": summary,
    }
