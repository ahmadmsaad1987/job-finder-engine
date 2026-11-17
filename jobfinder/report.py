"""Build the Excel file and the daily email."""
from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .models import Job

HEADER_FILL = PatternFill("solid", fgColor="F3F3F3")


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], widths: list[int], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    return ws


def _scored_rows(jobs: list[Job]) -> list[list]:
    rows = []
    for j in jobs:
        rows.append([
            j.score / 100, j.title, j.company, j.location, j.job_type, "", j.posted,
            ", ".join(j.matched_skills), "; ".join(j.notes), j.source, j.url,
        ])
    return rows


SCORED_HEADERS = ["Score", "Role", "Employer", "Location", "Job type", "Interested?", "Posted",
                  "Skills matched", "Watch-outs", "Source", "Link"]
SCORED_WIDTHS = [8, 40, 26, 24, 16, 12, 14, 40, 36, 22, 50]


def build_excel(path: Path, matches: list[Job], near: list[Job], alerts: list[Job], log: list[tuple[str, str]]) -> Path:
    wb = Workbook()
    for title, jobs, first in (("Matches", matches, True), ("Near misses", near, False)):
        ws = _sheet(wb, title, SCORED_HEADERS, _scored_rows(jobs), SCORED_WIDTHS, first=first)
        for row in ws.iter_rows(min_row=2, max_col=1):
            row[0].number_format = "0%"
        for row in ws.iter_rows(min_row=2, min_col=11, max_col=11):
            if row[0].value:
                row[0].hyperlink = row[0].value
                row[0].style = "Hyperlink"
        if jobs:
            dv = DataValidation(type="list", formula1='"Yes,Maybe,No"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"F2:F{len(jobs) + 1}")
    _sheet(wb, "From job alerts", ["Role", "Employer", "Location", "Source", "Link"],
           [[j.title, j.company, j.location, j.source, j.url] for j in alerts], [40, 26, 24, 18, 60])
    _sheet(wb, "Run log", ["Source", "Result"], [list(x) for x in log], [36, 90])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_email_html(day: str, matches: list[Job], near: list[Job], alerts: list[Job],
                     log: list[tuple[str, str]], weekly: dict | None, threshold: int) -> str:
    e = html.escape

    def table(jobs: list[Job]) -> str:
        if not jobs:
            return "<p>None today.</p>"
        rows = "".join(
            f"<tr><td><b>{j.score}%</b></td><td><a href='{e(j.url)}'>{e(j.title)}</a></td>"
            f"<td>{e(j.company)}</td><td>{e(j.location)}</td><td>{e(j.job_type)}</td><td>{e('; '.join(j.notes))}</td></tr>"
            for j in jobs)
        return ("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
                "<tr style='background:#f3f3f3'><th>Score</th><th>Role</th><th>Employer</th><th>Location</th>"
                "<th>Type</th><th>Watch-outs</th></tr>" + rows + "</table>")

    parts = [
        f"<h2>Job matches for {e(day)}</h2>",
        f"<p><b>{len(matches)}</b> new jobs scored {threshold}% or higher. "
        f"{len(near)} near misses and {len(alerts)} jobs from alert emails are in the attached Excel file.</p>",
        table(matches),
    ]
    if alerts:
        items = "".join(f"<li><a href='{e(j.url)}'>{e(j.title)}</a> - {e(j.company)} ({e(j.source)})</li>" for j in alerts[:25])
        parts.append(f"<h3>From your job alerts (title match only - open to check)</h3><ul>{items}</ul>")
    if weekly:
        todo = "".join(f"<li>{e(t)}</li>" for t in weekly.get("todo", []))
        pages = "".join(f"<li><a href='{e(p['url'])}'>{e(p['name'])}</a></li>" for p in weekly.get("careers_pages", []))
        parts.append(f"<h3>This week's to-do (jobs that are not advertised)</h3><ul>{todo}</ul>")
        if pages:
            parts.append(f"<h3>Careers pages to check by hand this week</h3><ul>{pages}</ul>")
    problems = [f"<li>{e(s)}: {e(r)}</li>" for s, r in log if "ERROR" in r]
    if problems:
        parts.append("<h3>Sources with problems</h3><ul>" + "".join(problems) + "</ul>")
    parts.append("<p style='color:#666'>Check each posting is still open before applying.</p>")
    return "\n".join(parts)


def send_email(subject: str, html_body: str, to: list[str], attachment: Path | None) -> str:
    address = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        return "skipped - no GMAIL_ADDRESS / GMAIL_APP_PASSWORD secret yet"
    if not to:
        return "skipped - no report_to address in config.yaml"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = ", ".join(to)
    msg.set_content("Your email app can't show HTML. Open the attached Excel file.")
    msg.add_alternative(html_body, subtype="html")
    if attachment and attachment.exists():
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=attachment.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(address, password.replace(" ", ""))
        s.send_message(msg)
    return f"sent to {len(to)} address(es)"
