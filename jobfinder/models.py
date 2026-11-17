"""The Job record that every source produces."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    posted: str = ""          # ISO date (YYYY-MM-DD) when known
    job_type: str = ""        # Permanent / Contract / Part-time ... (filled by filters)
    # Filled by scoring
    score: int = 0
    role_points: int = 0
    skills_points: int = 0
    experience_points: int = 0
    location_points: int = 0
    matched_skills: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    title_only: bool = False  # True for jobs from alert emails (no description read)

    def key(self) -> str:
        """Stable identity used to avoid sending the same job twice."""
        import hashlib
        import re

        def norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

        base = f"{norm(self.title)}|{norm(self.company)}"
        if not self.company:
            base += "|" + (self.url or "")
        return hashlib.sha1(base.encode()).hexdigest()[:16]
