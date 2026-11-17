"""Adzuna job search API (free key from developer.adzuna.com).

Adzuna gathers postings from many Canadian job boards and employer sites.
Only a short description is returned, so these jobs are flagged
"short description - check the posting".
"""
from __future__ import annotations

import os

from .. import http
from ..models import Job
from ..textutil import html_to_text

API = "https://api.adzuna.com/v1/api/jobs/ca/search/{page}"


def parse(payload: dict) -> list[Job]:
    jobs = []
    for r in payload.get("results", []):
        loc = (r.get("location") or {})
        area = loc.get("area") or []
        location = loc.get("display_name") or ", ".join(area)
        if area and "Ontario" in area and "Ontario" not in location:
            location = f"{location}, Ontario"
        jtype = " ".join(x for x in [r.get("contract_time") or "", r.get("contract_type") or ""] if x)
        jobs.append(Job(
            title=html_to_text(r.get("title", "")),
            company=((r.get("company") or {}).get("display_name") or ""),
            location=location,
            url=r.get("redirect_url", ""),
            source="Adzuna",
            description=html_to_text(r.get("description", "")),
            posted=(r.get("created") or "")[:10],
            job_type=jtype.replace("_", "-"),
        ))
    return jobs


def collect(section: dict, ctx) -> list[Job]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        ctx.log("Adzuna", "skipped - no ADZUNA_APP_ID / ADZUNA_APP_KEY secret yet")
        return []
    phrases = section.get("search_phrases") or ctx.all_title_phrases()
    days = int(section.get("max_days_old", 3))
    out: list[Job] = []
    errors = 0
    for phrase in phrases:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 50,
            "what_phrase": phrase,
            "where": "Ontario",
            "max_days_old": days,
            "content-type": "application/json",
        }
        try:
            r = http.get(API.format(page=1), params=params)
            out.extend(parse(r.json()))
        except Exception as e:  # noqa: BLE001
            errors += 1
            if errors <= 2:
                ctx.log("Adzuna", f"error for '{phrase}': {e}")
    ctx.log("Adzuna", f"{len(out)} postings from {len(phrases)} searches ({errors} errors)")
    return out
