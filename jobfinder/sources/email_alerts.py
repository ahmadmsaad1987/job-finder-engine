"""Read job-alert emails (LinkedIn, Indeed, Glassdoor, job boards) from a
Gmail inbox, using a Gmail app password.

LinkedIn and Indeed don't allow automated searching, so the job seeker sets up job
alerts on those sites and sends them to this Gmail address. We only read the
alert emails he receives. These jobs have no description, so they are listed
by title only in their own sheet.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

from ..models import Job
from ..textutil import clean

JOB_LINK = re.compile(
    r"linkedin\.com/(comm/)?jobs/view|indeed\.(com|ca)/(rc/clk|viewjob|pagead|m/viewjob)|"
    r"glassdoor\.(com|ca)/(partner/)?job-listing|glassdoor\.(com|ca)/job-listing|"
    r"/job/\d+|jobs?/\d{4,}",
    re.I,
)
SENDER_NAMES = {
    "linkedin": "LinkedIn alert",
    "indeed": "Indeed alert",
    "glassdoor": "Glassdoor alert",
}


def _html_of(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def parse_alert_html(html: str, source: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not JOB_LINK.search(href):
            continue
        title = clean(a.get_text(" "))
        if not title or len(title) < 4 or len(title) > 140 or title.lower() in ("view job", "apply now", "see all jobs"):
            continue
        key = (title.lower(), href.split("?")[0])
        if key in seen:
            continue
        seen.add(key)
        # The company and location usually follow the title in the same block.
        block = a.find_parent(["td", "div", "tr"])
        extra = clean(block.get_text(" | ")) if block else ""
        extra = extra.replace(title, "").strip(" |")
        bits = [b.strip() for b in extra.split("|") if b.strip()][:3]
        company = bits[0] if bits else ""
        location = next((b for b in bits[1:] if re.search(r"ON\b|Ontario|Canada|Remote|Toronto", b)), "")
        jobs.append(Job(title=title, company=company, location=location, url=href.split("&trk")[0],
                        source=source, title_only=True))
    return jobs


def collect(section: dict, ctx) -> list[Job]:
    address = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        ctx.log("Alert emails", "skipped - no GMAIL_ADDRESS / GMAIL_APP_PASSWORD secret yet")
        return []
    since = (datetime.now() - timedelta(days=int(section.get("days_back", 2)))).strftime("%d-%b-%Y")
    out: list[Job] = []
    try:
        box = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        box.login(address, password.replace(" ", ""))
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, f'(SINCE "{since}")')
        ids = data[0].split() if data and data[0] else []
        read = 0
        for i in ids[-300:]:
            typ, msg_data = box.fetch(i, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            sender = str(make_header(decode_header(msg.get("From", "")))).lower()
            if not any(s in sender for s in section.get("senders", ["linkedin", "indeed", "glassdoor"])):
                continue
            label = next((v for k, v in SENDER_NAMES.items() if k in sender), "Job alert email")
            read += 1
            for j in parse_alert_html(_html_of(msg), label):
                if ctx.titles.match(j.title):
                    out.append(j)
        box.logout()
        ctx.log("Alert emails", f"{read} alert emails read, {len(out)} jobs with matching titles")
    except Exception as e:  # noqa: BLE001
        ctx.log("Alert emails", f"ERROR ({e})")
    return out
