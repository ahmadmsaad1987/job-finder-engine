"""Decide which jobs are worth scoring: target titles, Ontario, job type."""
from __future__ import annotations

import re

from .models import Job

ONTARIO_CITIES = [
    "toronto", "ottawa", "mississauga", "brampton", "hamilton", "london", "markham",
    "vaughan", "kitchener", "waterloo", "cambridge", "guelph", "windsor", "oakville",
    "burlington", "richmond hill", "oshawa", "whitby", "ajax", "pickering", "barrie",
    "sudbury", "kingston", "thunder bay", "st. catharines", "niagara", "peterborough",
    "north york", "scarborough", "etobicoke", "woodbridge", "concord", "newmarket",
    "aurora", "milton", "sault ste", "north bay", "timmins", "belleville", "cornwall",
    "sarnia", "brantford", "welland", "caledon", "halton", "durham", "york region", "gta",
    "greater toronto",
]

OTHER_PROVINCES = [
    r"\bBC\b", "british columbia", r"\bAB\b", "alberta", r"\bQC\b", "quebec", "québec",
    r"\bMB\b", "manitoba", r"\bSK\b", "saskatchewan", r"\bNS\b", "nova scotia",
    r"\bNB\b", "new brunswick", r"\bNL\b", "newfoundland", r"\bPEI?\b", "prince edward",
    "vancouver", "calgary", "edmonton", "montreal", "montréal", "winnipeg", "halifax",
    "regina", "saskatoon",
]


def compile_titles(phrases: list[str]) -> list[re.Pattern]:
    out = []
    for p in phrases:
        p = p.strip().lower()
        if not p:
            continue
        # allow "-" or spaces between words, e.g. first-year / first year
        words = [w for w in re.split(r"[\s\-]+", p) if w]
        pattern = r"(?<![A-Za-z])" + r"[\s\-]+".join(re.escape(w) for w in words) + r"(?![A-Za-z])"
        out.append(re.compile(pattern, re.I))
    return out


class TitleMatcher:
    def __init__(self, cfg: dict):
        t = cfg.get("titles", {})
        self.primary = compile_titles(t.get("primary", []))
        self.secondary = compile_titles(t.get("secondary", []))
        self.exclude = compile_titles(t.get("exclude", []))
        self.associate_context = re.compile(
            r"\b(legal|law|lawyer|corporate|commercial|construction|business law|litigation|"
            r"real estate|infrastructure|banking|securities)\b", re.I)

    def match(self, title: str, description: str = "") -> str:
        """Return 'primary', 'secondary' or '' (no match)."""
        if not title:
            return ""
        if any(p.search(title) for p in self.exclude):
            return ""
        if any(p.search(title) for p in self.primary):
            return "primary"
        # A plain "Associate" only counts when it is a legal associate.
        if re.search(r"\bassociate\b", title, re.I) and not re.search(
            r"\bassociate\s+(director|vice|general|manager|partner|dean|professor)", title, re.I) and (
            self.associate_context.search(title)
            or re.search(r"law society|call to the bar|post-call|year of call", description or "", re.I)
        ):
            return "primary"
        if any(p.search(title) for p in self.secondary):
            return "secondary"
        return ""


def location_kind(location: str, description: str = "") -> str:
    """Return 'ontario', 'remote_canada' or '' (not usable)."""
    loc = location or ""
    low = loc.lower()
    if re.search(r"\bON\b", loc) or "ontario" in low or any(c in low for c in ONTARIO_CITIES):
        return "ontario"
    is_remote = "remote" in low or "anywhere" in low
    if is_remote and ("canada" in low or low.strip() in ("remote", "")):
        if not any(re.search(p, loc, re.I) for p in OTHER_PROVINCES):
            return "remote_canada"
    if low.strip() in ("canada", "ca", "") or re.search(r"\d+\s+locations", low):
        # Vague location: look in the description.
        d = (description or "")[:3000]
        if re.search(r"\bOntario\b|\bToronto\b|\bOttawa\b|\bMississauga\b", d):
            return "ontario"
        if re.search(r"remote", d, re.I) and re.search(r"canada", d, re.I):
            return "remote_canada"
    return ""


JOB_TYPES = [
    ("Part-time", r"\bpart[\s\-]?time\b"),
    ("Secondment", r"\bsecondment\b"),
    ("Contract", r"\b(contract|fixed[\s\-]term|temporary|term position|\d+[\s\-]month)\b(?!\s+(manager|management|administrator|administration|specialist|counsel|law|lawyer|review|drafting|negotiation))"),
    ("Permanent", r"\bpermanent\b"),
    ("Full-time", r"\bfull[\s\-]?time\b"),
]


def detect_job_type(job: Job) -> str:
    text = f"{job.title} {job.job_type} {job.description[:2500]}"
    found = []
    for label, pat in JOB_TYPES:
        if re.search(pat, text, re.I):
            found.append(label)
    if "Part-time" in found:
        return "Part-time"
    if "Secondment" in found:
        return "Secondment / contract"
    if "Contract" in found and "Permanent" not in found:
        return "Contract"
    if "Permanent" in found or "Full-time" in found:
        return "Permanent / full-time"
    return "Not stated"
