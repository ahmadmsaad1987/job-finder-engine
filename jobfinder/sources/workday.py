"""Employer careers sites built on Workday (URLs containing myworkdayjobs.com).

In config.yaml give the careers URL exactly as it appears in the browser, e.g.
  https://brookfield.wd5.myworkdayjobs.com/brookfield
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .. import http
from ..models import Job
from ..textutil import html_to_text


def parse_url(url: str) -> tuple[str, str, str]:
    """Return (host, tenant, site) from a Workday careers URL."""
    u = urlparse(url.strip())
    host = u.netloc
    tenant = host.split(".")[0]
    parts = [p for p in u.path.split("/") if p]
    # drop a locale like en-US
    parts = [p for p in parts if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
    if not parts:
        raise ValueError(f"Can't find the site name in {url}")
    return host, tenant, parts[0]


def parse_list(payload: dict, host: str, site: str, company: str) -> list[Job]:
    jobs = []
    for p in payload.get("jobPostings", []):
        path = p.get("externalPath", "")
        jobs.append(Job(
            title=p.get("title", ""),
            company=company,
            location=p.get("locationsText", ""),
            url=f"https://{host}/{site}{path}",
            source=f"Careers site: {company}",
            posted=p.get("postedOn", ""),  # e.g. "Posted 2 Days Ago"
        ))
        jobs[-1]._path = path  # type: ignore[attr-defined]
    return jobs


def parse_detail(payload: dict, job: Job) -> Job:
    info = payload.get("jobPostingInfo", {}) or {}
    job.description = html_to_text(info.get("jobDescription", ""))
    locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
    loc = "; ".join(x for x in locs if x)
    if loc:
        job.location = loc
    if info.get("startDate"):
        job.posted = info["startDate"][:10]
    if info.get("timeType"):
        job.job_type = info["timeType"]
    return job


def collect_one(entry: dict, ctx) -> list[Job]:
    company = entry["name"]
    host, tenant, site = parse_url(entry["url"])
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    found: dict[str, Job] = {}
    for phrase in entry.get("search_phrases") or ctx.workday_search_phrases():
        body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": phrase}
        r = http.post(api, json=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
        for j in parse_list(r.json(), host, site, company):
            found.setdefault(j.url, j)
    # Only read the full posting for titles we care about.
    keep = []
    for j in found.values():
        if not ctx.titles.match(j.title):
            continue
        try:
            d = http.get(f"https://{host}/wday/cxs/{tenant}/{site}{j._path}", headers={"Accept": "application/json"})  # type: ignore[attr-defined]
            parse_detail(d.json(), j)
        except Exception as e:  # noqa: BLE001
            j.notes.append(f"could not read full posting: {e}")
        keep.append(j)
    return keep


def collect(section: dict, ctx) -> list[Job]:
    out = []
    for entry in section.get("employers", []):
        if not entry.get("url"):
            continue
        try:
            jobs = collect_one(entry, ctx)
            ctx.log(f"Workday: {entry['name']}", f"{len(jobs)} matching titles")
            out.extend(jobs)
        except Exception as e:  # noqa: BLE001
            ctx.log(f"Workday: {entry['name']}", f"ERROR - check the URL in config.yaml ({e})")
    return out
