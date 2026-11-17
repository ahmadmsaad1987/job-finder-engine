"""Remember which jobs were already sent, and keep a history file."""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from .models import Job


class Store:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen.json"
        self.seen: dict[str, str] = {}
        if self.seen_path.exists():
            self.seen = json.loads(self.seen_path.read_text())
        self.seen_urls = {v.split("|", 1)[1] for v in self.seen.values() if "|" in v}

    def is_new(self, job: Job) -> bool:
        return job.key() not in self.seen

    def url_seen(self, url: str) -> bool:
        return url in self.seen_urls

    def remember(self, jobs: list[Job]) -> None:
        today = date.today().isoformat()
        for j in jobs:
            self.seen.setdefault(j.key(), f"{today}|{j.url}")

    def save(self, keep_days: int = 180) -> None:
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v.split("|", 1)[0] >= cutoff}
        self.seen_path.write_text(json.dumps(self.seen, indent=0, sort_keys=True))

    def append_history(self, jobs: list[Job]) -> None:
        path = self.dir / "history.csv"
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["found_on", "score", "title", "company", "location", "job_type", "posted", "source", "url"])
            today = date.today().isoformat()
            for j in jobs:
                w.writerow([today, j.score, j.title, j.company, j.location, j.job_type, j.posted, j.source, j.url])
