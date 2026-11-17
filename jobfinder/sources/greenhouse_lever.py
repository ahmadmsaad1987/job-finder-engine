"""Employer careers sites on Greenhouse (boards.greenhouse.io/<board>) or
Lever (jobs.lever.co/<company>). Both publish public job lists."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import http
from ..models import Job
from ..textutil import html_to_text


def parse_greenhouse(payload: dict, company: str) -> list[Job]:
    jobs = []
    for p in payload.get("jobs", []):
        jobs.append(Job(
            title=p.get("title", ""),
            company=company,
            location=(p.get("location") or {}).get("name", ""),
            url=p.get("absolute_url", ""),
            source=f"Careers site: {company}",
            description=html_to_text(p.get("content", "")),
            posted=(p.get("updated_at") or "")[:10],
        ))
    return jobs


def parse_lever(payload: list, company: str) -> list[Job]:
    jobs = []
    for p in payload:
        cats = p.get("categories") or {}
        created = p.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat() if created else ""
        desc = p.get("descriptionPlain") or html_to_text(p.get("description", ""))
        for lst in p.get("lists", []) or []:
            desc += " " + lst.get("text", "") + " " + html_to_text(lst.get("content", ""))
        jobs.append(Job(
            title=p.get("text", ""),
            company=company,
            location=cats.get("location", "") or ", ".join(cats.get("allLocations", []) or []),
            url=p.get("hostedUrl", ""),
            source=f"Careers site: {company}",
            description=desc,
            posted=posted,
            job_type=cats.get("commitment", ""),
        ))
    return jobs


def collect(section: dict, ctx) -> list[Job]:
    out = []
    for e in section.get("greenhouse", []) or []:
        try:
            r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{e['board']}/jobs", params={"content": "true"})
            jobs = [j for j in parse_greenhouse(r.json(), e["name"]) if ctx.titles.match(j.title, j.description)]
            ctx.log(f"Greenhouse: {e['name']}", f"{len(jobs)} matching titles")
            out.extend(jobs)
        except Exception as ex:  # noqa: BLE001
            ctx.log(f"Greenhouse: {e['name']}", f"ERROR ({ex})")
    for e in section.get("lever", []) or []:
        try:
            r = http.get(f"https://api.lever.co/v0/postings/{e['company']}", params={"mode": "json"})
            jobs = [j for j in parse_lever(r.json(), e["name"]) if ctx.titles.match(j.title, j.description)]
            ctx.log(f"Lever: {e['name']}", f"{len(jobs)} matching titles")
            out.extend(jobs)
        except Exception as ex:  # noqa: BLE001
            ctx.log(f"Lever: {e['name']}", f"ERROR ({ex})")
    return out
