"""Generic reader for job boards that show a public list of postings,
such as Clear Legal Jobs. Each board in config.yaml gives:

  name:         label shown in the results
  list_urls:    pages that list recent jobs
  link_pattern: regular expression that matches a job's link on those pages
  pages:        how many result pages to read (adds ?page=N)
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import http
from ..models import Job
from ..textutil import clean, html_to_text

DATE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b", re.I)
LOC_RE = re.compile(r"(,\s*(Ontario|ON)\b)|\bCanada\b|\bRemote\b", re.I)


def parse_listing(html: str, base_url: str, link_pattern: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(link_pattern)
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if not pat.search(href) or href in seen:
            continue
        title = clean(a.get_text(" "))
        if not title or len(title) < 4:
            continue
        seen.add(href)
        out.append((title, href))
    return out


def parse_detail(html: str, url: str, fallback_title: str, board: str) -> Job:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean(h1.get_text(" ")) if h1 else fallback_title
    company = location = posted = ""
    if h1:
        items = []
        for li in h1.find_all_next("li", limit=12):
            t = clean(li.get_text(" "))
            if t and len(t) < 120:
                items.append(t)
        for t in items:
            if not posted and DATE_RE.search(t):
                posted = DATE_RE.search(t).group(0)
            elif not location and LOC_RE.search(t):
                location = t
            elif not company and not DATE_RE.search(t):
                company = t
    body = soup.find(string=re.compile(r"Job Description", re.I))
    if body is not None and body.parent is not None:
        container = body.parent.find_parent(["div", "section", "article"]) or body.parent
        description = html_to_text(str(container))
    else:
        main = soup.find("main") or soup.find("article") or soup.body or soup
        description = html_to_text(str(main))
    # Stop before "similar jobs" lists so other postings don't count as skills.
    description = re.split(r"(Similar jobs|Related jobs|More jobs|Share this job|Report this job|"
                           r"Email me jobs like this|Jobs you may like)", description, maxsplit=1, flags=re.I)[0]
    return Job(title=title, company=company, location=location, url=url, source=board,
               description=description[:20000], posted=posted)


def collect(section: dict, ctx) -> list[Job]:
    out = []
    for board in section.get("boards", []) or []:
        name = board["name"]
        try:
            links: list[tuple[str, str]] = []
            for base in board.get("list_urls", []):
                for page in range(1, int(board.get("pages", 1)) + 1):
                    url = base if page == 1 else f"{base}{'&' if '?' in base else '?'}page={page}"
                    r = http.get(url)
                    links.extend(parse_listing(r.text, url, board["link_pattern"]))
            uniq = {href: title for title, href in links}
            wanted = [(t, h) for h, t in uniq.items() if ctx.titles.match(t) and not ctx.already_seen_url(h)]
            jobs = []
            for title, href in wanted[: int(board.get("max_details", 40))]:
                try:
                    d = http.get(href)
                    jobs.append(parse_detail(d.text, href, title, name))
                except Exception as e:  # noqa: BLE001
                    ctx.log(name, f"could not open {href}: {e}")
            ctx.log(name, f"{len(uniq)} postings listed, {len(jobs)} with matching titles read")
            out.extend(jobs)
        except Exception as e:  # noqa: BLE001
            ctx.log(name, f"ERROR ({e})")
    return out
