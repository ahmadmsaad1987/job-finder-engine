"""Offline tests: every source is fed saved sample data instead of the internet.

Run from the job-finder-engine folder:  python -m pytest -q
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from jobfinder import http, main as main_mod
from jobfinder.filters import TitleMatcher, detect_job_type, location_kind
from jobfinder.models import Job
from jobfinder.scoring import Scorer
from jobfinder.sources import adzuna, email_alerts, greenhouse_lever, html_board, workday

FIX = Path(__file__).parent / "fixtures"
CONFIG = FIX / "sample_config.yaml"


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(CONFIG.read_text())


class FakeResp:
    def __init__(self, text: str):
        self.text = text

    def json(self):
        return json.loads(self.text)


def fake_get(url, **kw):
    if "adzuna" in url:
        return FakeResp((FIX / "adzuna.json").read_text())
    if "myworkdayjobs.com/wday/cxs" in url:
        return FakeResp((FIX / "workday_detail.json").read_text())
    if "greenhouse" in url:
        return FakeResp((FIX / "greenhouse.json").read_text())
    if "jobs-in-ontario" in url:
        return FakeResp((FIX / "board_list.html").read_text())
    if "/job/32920/" in url:
        return FakeResp((FIX / "board_detail_oxford.html").read_text())
    if "/job/32925/" in url:
        return FakeResp((FIX / "board_detail_samsung.html").read_text())
    raise RuntimeError(f"offline test: no sample for {url}")


def fake_post(url, **kw):
    if "myworkdayjobs.com/wday/cxs" in url:
        return FakeResp((FIX / "workday_list.json").read_text())
    raise RuntimeError(f"offline test: no sample for {url}")


# ---- titles and locations -------------------------------------------------
def test_titles(cfg):
    t = TitleMatcher(cfg)
    assert t.match("Legal Counsel") == "primary"
    assert t.match("First Year Associate") == "primary"
    assert t.match("Senior Contracts Manager") == "primary"
    assert t.match("Associate Director, Legal Services - Construction") == "secondary"
    assert t.match("Contracts Administrator") == "secondary"
    assert t.match("Corporate Associate") == "primary"
    assert t.match("Associate, Investments") == ""
    assert t.match("Articling Student") == ""
    assert t.match("Senior Law Clerk") == ""
    assert t.match("Senior Credit Risk Manager") == ""
    assert t.match("Guidance Counsellor") == ""


def test_locations():
    assert location_kind("Toronto, ON") == "ontario"
    assert location_kind("Markham, York Region, Ontario") == "ontario"
    assert location_kind("Remote, Canada") == "remote_canada"
    assert location_kind("Calgary, Alberta") == ""
    assert location_kind("2 Locations", "Based in our Toronto office") == "ontario"


def test_job_type():
    j = Job("Legal Counsel & Compliance Advisor", "Mobis", "Markham, ON", "u", "s",
            description="This position is structured as a part-time role of approximately 22.5 hours per week.")
    assert detect_job_type(j) == "Part-time"
    j2 = Job("Contracts Manager", "X", "Toronto, ON", "u", "s", description="Full-time permanent role managing contracts.")
    assert detect_job_type(j2) == "Permanent / full-time"
    j3 = Job("Legal Counsel", "OSC", "Toronto, ON", "u", "s", description="Fixed Term (12 to 18-Month Contract or Secondment)")
    assert detect_job_type(j3).startswith("Secondment")


# ---- scoring calibration against postings reviewed by hand ---------------
def _score(cfg, title, desc, loc="Toronto, ON"):
    s = Scorer(cfg)
    j = Job(title, "Co", loc, "u", "s", description=desc)
    kind = TitleMatcher(cfg).match(title, desc)
    return s.score(j, kind)


def test_scores_follow_manual_review(cfg):
    samsung = (FIX / "board_detail_samsung.html").read_text()
    oxford = (FIX / "board_detail_oxford.html").read_text()
    from jobfinder.textutil import html_to_text
    s1 = _score(cfg, "New Grad Program - Counsel, Legal and Regulatory Affairs", html_to_text(samsung), "Mississauga, ON")
    s2 = _score(cfg, "Associate Director, Legal Services - Construction", html_to_text(oxford))
    osc = _score(cfg, "Legal Counsel", "Minimum 5 years post-call to the Bar with experience in a law firm "
                                       "or regulatory role within the securities industry, including in-depth "
                                       "experience in securities regulation. Advise innovative businesses navigating "
                                       "Ontario's regulatory framework.")
    print(s1.score, s2.score, osc.score)
    assert s1.score >= 75
    assert s2.score >= 75
    assert osc.score < 75


# ---- each source parses its sample data ----------------------------------
def test_sources_offline(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(http, "get", fake_get)
    monkeypatch.setattr(http, "post", fake_post)
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    store = main_mod.Store(tmp_path)
    ctx = main_mod.Context(cfg, store)

    az = adzuna.collect({"search_phrases": ["legal counsel"]}, ctx)
    assert len(az) == 3

    wd = workday.collect({"employers": [{"name": "Brookfield", "url": "https://brookfield.wd5.myworkdayjobs.com/brookfield"}]}, ctx)
    assert [j.title for j in wd] == ["Legal Associate"]
    assert "Law Society of Ontario" in wd[0].description
    assert wd[0].url == "https://brookfield.wd5.myworkdayjobs.com/brookfield/job/Toronto/Legal-Associate_R123"

    gh = greenhouse_lever.collect({"greenhouse": [{"name": "TestCo", "board": "testco"}]}, ctx)
    assert gh and "SaaS" in gh[0].description

    jb = html_board.collect(cfg["job_boards"], ctx)
    titles = sorted(j.title for j in jb)
    assert titles == ["Associate Director, Legal Services - Construction",
                      "New Grad Program - Counsel, Legal and Regulatory Affairs (12 months)"]
    ox = next(j for j in jb if "Construction" in j.title)
    assert ox.company == "Oxford Properties Group" and "Ontario" in ox.location and ox.posted == "Nov 12, 2026"

    alerts = [j for j in email_alerts.parse_alert_html((FIX / "linkedin_alert.html").read_text(), "LinkedIn alert")
              if ctx.titles.match(j.title)]
    assert [a.title for a in alerts] == ["Contracts Manager"]
    assert alerts[0].company == "EllisDon"


def test_workday_url_parsing():
    assert workday.parse_url("https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers") == (
        "td.wd3.myworkdayjobs.com", "td", "TD_Bank_Careers")


# ---- whole daily run, offline ---------------------------------------------
def test_full_run(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(http, "get", fake_get)
    monkeypatch.setattr(http, "post", fake_post)
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    small = dict(cfg)
    small["adzuna"] = {"enabled": True, "search_phrases": ["legal counsel"]}
    small["workday"] = {"employers": [{"name": "Brookfield", "url": "https://brookfield.wd5.myworkdayjobs.com/brookfield"},
                                      {"name": "Broken", "url": "https://nowhere.example.com/"}]}
    small["careers_sites"] = {"greenhouse": [{"name": "TestCo", "board": "testco"}], "lever": []}
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(small))
    data = tmp_path / "data"
    assert main_mod.main(["--config", str(cfg_path), "--data", str(data)]) == 0
    reports = list((data / "reports").glob("*.xlsx"))
    assert reports
    from openpyxl import load_workbook
    wb = load_workbook(reports[0])
    assert wb.sheetnames == ["Matches", "Near misses", "From job alerts", "Run log"]
    matches = [r for r in wb["Matches"].iter_rows(min_row=2, values_only=True)]
    print("\n".join(f"{r[0]:.0%} {r[1]} | {r[2]} | {r[4]} | {r[8]}" for r in matches))
    assert len(matches) >= 3
    log = [r for r in wb["Run log"].iter_rows(min_row=2, values_only=True)]
    assert any("ERROR" in (r[1] or "") and "Broken" in r[0] for r in log)
    # Second run the same day sends nothing new.
    assert main_mod.main(["--config", str(cfg_path), "--data", str(data)]) == 0
    wb2 = load_workbook(sorted((data / "reports").glob("*.xlsx"))[-1])
    assert wb2["Matches"].max_row == 1

