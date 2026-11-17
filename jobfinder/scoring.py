"""Free keyword scoring (0-100).

Score = role match (20) + skills overlap (40) + experience level (25) + location (15)

The skill groups come from the candidate's resume. They live in config.yaml
under `skills`, so they can be edited without touching code.
"""
from __future__ import annotations

import re

from .filters import location_kind
from .models import Job

SENIOR_TITLE = re.compile(
    r"\b(director|head of|vice[\s\-]president|\bvp\b|chief|partner)\b|(?<!associate )(?<!assistant )(?<!deputy )\bgeneral counsel\b",
    re.I,
)
YEARS = re.compile(
    r"(?:minimum of|at least|min\.?|over)?\s*(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|—|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)
FRENCH = re.compile(
    r"\bbilingual\b|french\s+(?:is\s+)?(?:required|mandatory|essential)|(?:fluency|proficiency)\s+in\s+(?:both\s+)?(?:english\s+and\s+)?french\s+(?:is\s+)?(?:required|mandatory)",
    re.I,
)


class Scorer:
    def __init__(self, cfg: dict):
        self.skill_groups: dict[str, list[re.Pattern]] = {}
        for name, terms in (cfg.get("skills") or {}).items():
            self.skill_groups[name] = [
                re.compile(r"(?<![A-Za-z])" + re.escape(t.lower()), re.I) for t in terms
            ]
        s = cfg.get("scoring", {})
        self.full_skill_groups = int(s.get("skill_groups_for_full_points", 7))
        self.short_desc_groups = int(s.get("skill_groups_for_full_points_short_description", 4))

    # --- parts -----------------------------------------------------------
    def role_points(self, match_kind: str) -> int:
        return {"primary": 20, "secondary": 15}.get(match_kind, 0)

    def skills_points(self, job: Job) -> tuple[int, list[str]]:
        text = f"{job.title} {job.description}"
        matched = [name for name, pats in self.skill_groups.items() if any(p.search(text) for p in pats)]
        need = self.full_skill_groups if len(job.description) >= 1500 else self.short_desc_groups
        pts = round(40 * min(1.0, len(matched) / max(1, need)))
        return pts, matched

    def experience_points(self, job: Job) -> tuple[int, str]:
        desc = job.description or ""
        best_min = None
        post_call = False
        for m in YEARS.finditer(desc):
            lo = int(m.group(1))
            if lo > 25:
                continue
            window = desc[max(0, m.start() - 80): m.end() + 120].lower()
            if not re.search(r"experience|post[\s\-]?call|year of call|years of call|practi[cs]", window):
                continue
            if best_min is None or lo > best_min:
                best_min = lo
                post_call = bool(re.search(r"post[\s\-]?call|year of call|years of call|call to the bar", window))
        if best_min is None:
            pts, note = 18, "experience not stated"
        elif best_min <= 2:
            pts, note = 25, f"{best_min}+ yrs asked"
        elif best_min <= 4:
            pts, note = (16 if post_call else 21), f"{best_min}+ yrs{' post-call' if post_call else ''} asked"
        elif best_min <= 7:
            pts, note = (11 if post_call else 17), f"{best_min}+ yrs{' post-call' if post_call else ''} asked"
        else:
            pts, note = (6 if post_call else 12), f"{best_min}+ yrs{' post-call' if post_call else ''} asked"
        if SENIOR_TITLE.search(job.title or ""):
            pts = max(0, pts - 5)
            note += "; senior title"
        return pts, note

    def location_points(self, job: Job) -> int:
        kind = location_kind(job.location, job.description)
        return {"ontario": 15, "remote_canada": 12}.get(kind, 0)

    # --- total -----------------------------------------------------------
    def score(self, job: Job, match_kind: str) -> Job:
        job.role_points = self.role_points(match_kind)
        job.skills_points, job.matched_skills = self.skills_points(job)
        job.experience_points, exp_note = self.experience_points(job)
        job.location_points = self.location_points(job)
        total = job.role_points + job.skills_points + job.experience_points + job.location_points
        notes = [exp_note]
        if FRENCH.search(job.description or ""):
            total -= 10
            notes.append("French may be required")
        if len(job.description) < 1500:
            notes.append("short description - check the posting")
        job.score = max(0, min(100, total))
        job.notes = notes
        return job
