"""Daily run: collect -> filter -> remove repeats -> score -> Excel + email."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import report
from .filters import TitleMatcher, detect_job_type, location_kind
from .models import Job
from .scoring import Scorer
from .sources import adzuna, email_alerts, greenhouse_lever, html_board, workday
from .store import Store

SOURCES = {
    "adzuna": adzuna.collect,
    "workday": workday.collect,
    "careers_sites": greenhouse_lever.collect,
    "job_boards": html_board.collect,
    "alert_emails": email_alerts.collect,
}


class Context:
    def __init__(self, cfg: dict, store: Store):
        self.cfg = cfg
        self.titles = TitleMatcher(cfg)
        self.store = store
        self.messages: list[tuple[str, str]] = []

    def log(self, source: str, msg: str) -> None:
        self.messages.append((source, msg))
        print(f"[{source}] {msg}", flush=True)

    def all_title_phrases(self) -> list[str]:
        t = self.cfg.get("titles", {})
        return list(dict.fromkeys((t.get("primary") or []) + (t.get("secondary") or [])))

    def workday_search_phrases(self) -> list[str]:
        return (self.cfg.get("workday") or {}).get("search_phrases") or ["counsel", "lawyer", "legal", "contracts", "compliance", "risk"]

    def already_seen_url(self, url: str) -> bool:
        return self.store.url_seen(url)


def process(cfg: dict, raw: list[Job], ctx: Context, store: Store) -> tuple[list[Job], list[Job], list[Job], list[Job]]:
    scorer = Scorer(cfg)
    threshold = int(cfg.get("scoring", {}).get("threshold", 75))
    near_min = int(cfg.get("scoring", {}).get("near_miss_min", 60))
    matches, near, alerts, evaluated = [], [], [], []
    seen_now: set[str] = set()
    for j in raw:
        kind = ctx.titles.match(j.title, j.description)
        if not kind:
            continue
        loc = location_kind(j.location, j.description)
        if not loc and not (j.title_only and not j.location):
            continue
        k = j.key()
        if k in seen_now or not store.is_new(j):
            continue
        seen_now.add(k)
        j.job_type = detect_job_type(j)
        evaluated.append(j)
        if j.title_only:
            alerts.append(j)
            continue
        scorer.score(j, kind)
        if j.score >= threshold:
            matches.append(j)
        elif j.score >= near_min:
            near.append(j)
    matches.sort(key=lambda x: -x.score)
    near.sort(key=lambda x: -x.score)
    return matches, near, alerts, evaluated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Daily job finder")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data")
    ap.add_argument("--no-email", action="store_true")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg.get("timezone", "America/Toronto"))
    now = datetime.now(tz)
    day = now.strftime("%Y-%m-%d")
    store = Store(Path(args.data))
    ctx = Context(cfg, store)

    raw: list[Job] = []
    for name, fn in SOURCES.items():
        section = cfg.get(name)
        if not section or section.get("enabled") is False:
            continue
        try:
            raw.extend(fn(section, ctx))
        except Exception as e:  # noqa: BLE001
            ctx.log(name, f"ERROR ({e})")

    matches, near, alerts, evaluated = process(cfg, raw, ctx, store)
    ctx.log("Summary", f"{len(raw)} collected, {len(evaluated)} new and relevant, "
                       f"{len(matches)} matches, {len(near)} near misses, {len(alerts)} from alerts")

    xlsx = report.build_excel(Path(args.data) / "reports" / f"jobs-{day}.xlsx", matches, near, alerts, ctx.messages)
    weekly = None
    wk = cfg.get("weekly") or {}
    if wk and now.strftime("%A").lower() == str(wk.get("day", "monday")).lower():
        weekly = wk
    threshold = int(cfg.get("scoring", {}).get("threshold", 75))
    body = report.build_email_html(day, matches, near, alerts, ctx.messages, weekly, threshold)
    (Path(args.data) / "reports" / f"jobs-{day}.html").write_text(body, encoding="utf-8")

    send_anyway = cfg.get("email", {}).get("send_when_no_matches", True)
    if not args.no_email and (matches or alerts or send_anyway):
        subject = f"{len(matches)} job matches ({day})"
        try:
            ctx.log("Email", report.send_email(subject, body, cfg.get("email", {}).get("report_to", []), xlsx))
        except Exception as e:  # noqa: BLE001
            ctx.log("Email", f"ERROR ({e})")

    store.remember(evaluated)
    store.save()
    store.append_history(matches + near)
    return 0


if __name__ == "__main__":
    sys.exit(main())
