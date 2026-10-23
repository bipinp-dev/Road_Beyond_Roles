#!/usr/bin/env python3
"""
US-eligible job scraper
------------------------
Pulls fresh postings from public job feeds / company ATS APIs and keeps only
jobs an applicant in India can realistically take:
  * Tier A: job located in the US (any city, on-site / hybrid / remote)
  * Tier B: remote and explicitly open to "worldwide / anywhere / APAC / Asia"
  * Tier C: remote, location not stated (verify before applying)
Anything that mentions visa sponsorship, work permits, work authorisation,
"US only", "EU only", etc. is dropped.

Only jobs posted inside the freshness window are returned (default: last 24h),
and a small SQLite file remembers what you've already seen, so every run shows
ONLY NEW jobs.

Usage:
    python job_scraper.py                      # last 24h, new jobs only
    python job_scraper.py --today              # since midnight IST
    python job_scraper.py --hours 72 --all     # last 3 days, ignore "seen" history
    python job_scraper.py --keywords "python,data engineer" --exclude "intern"
    python job_scraper.py --strict             # drop Tier C (unclear location)
    python job_scraper.py --selftest           # test eligibility logic offline
"""
import argparse
import csv
import hashlib
import html
import json
import logging
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("jobs")
IST = timezone(timedelta(hours=5, minutes=30))
HERE = Path(__file__).parent

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 IndiaJobScraper/1.0")


# --------------------------------------------------------------------------
# Data model + helpers
# --------------------------------------------------------------------------
@dataclass
class Job:
    source: str
    title: str
    company: str
    location: str
    url: str
    posted: datetime | None
    description: str = ""
    remote: bool | None = None
    tier: str = ""
    note: str = ""


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, */*"})
    # A daily pipeline must not spend several minutes retrying every unavailable source.
    # One bounded retry is enough for transient errors; rate-limited sources can be retried
    # on the next scheduled run rather than stalling the whole episode.
    retry = Retry(total=1, connect=1, read=1, backoff_factor=0.3,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def get(s: requests.Session, url: str, **kw) -> requests.Response:
    timeout = kw.pop("timeout", 8)
    r = s.get(url, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def strip_html(text) -> str:
    """Convert source HTML to text while preserving paragraph/list structure and URLs."""
    if not text:
        return ""
    text = html.unescape(str(text))

    def keep_link(match):
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        href = html.unescape(match.group(1)).strip()
        if href and href.startswith(("https://", "http://")) and href not in label:
            return f"{label} ({href})" if label else href
        return label or href

    text = re.sub(
        r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""",
        keep_link, text, flags=re.I | re.S
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "\n• ", text, flags=re.I)
    text = re.sub(
        r"</(?:p|div|section|article|h[1-6]|li|ul|ol|tr|blockquote)\s*>",
        "\n\n", text, flags=re.I
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = []
    for line in text.split("\n"):
        cleaned.append(re.sub(r"[ \t\f\v]+", " ", line).strip())
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def parse_dt(v) -> datetime | None:
    """Accepts epoch (s or ms), ISO-8601, RFC-822, or 'YYYY-MM-DD HH:MM:SS'."""
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
            n = float(v)
            if n > 1e12:  # milliseconds
                n /= 1000
            return datetime.fromtimestamp(n, tz=timezone.utc)
        v = str(v).strip()
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            d = parsedate_to_datetime(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# --------------------------------------------------------------------------
# Eligibility logic (the important part)
# --------------------------------------------------------------------------
INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|navi mumbai|new delhi|"
    r"delhi|ncr|gurgaon|gurugram|noida|greater noida|chennai|kolkata|ahmedabad|"
    r"kochi|cochin|jaipur|chandigarh|mohali|indore|coimbatore|trivandrum|"
    r"thiruvananthapuram|nagpur|lucknow|bhubaneswar|vadodara|surat|"
    r"visakhapatnam|mysuru|mysore)\b", re.I)

US_RE = re.compile(
    r"(?<![a-z])(?:united states|u\.?s\.?a?|usa|us)(?![a-z])|"
    r"\b(?:new york|nyc|san francisco|sf bay area|bay area|seattle|"
    r"los angeles|chicago|boston|austin|denver|atlanta|miami|"
    r"dallas|houston|phoenix|san diego|portland|washington,?\s*d\.?c\.?|"
    r"pittsburgh|philadelphia|minneapolis|detroit|nashville|"
    r"raleigh|charlotte|california|texas)\b", re.I)

# US-specific phrases that the old India filter treated as blockers,
# but that are actually features for a US-targeted audience.
US_FEATURE_RE = re.compile(
    r"(?<!\w)(?:authori[sz]ed|eligible|permitted|legally (?:entitled|permitted|authori[sz]ed)) to work in (?:the )?(?:us|usa|u\.?s\.?a?|united states)\b|"
    r"(?<!\w)must (?:currently )?(?:reside|live|be located|be based|be resident)s? in (?:the )?(?:us|usa|u\.?s\.?a?|united states)\b|"
    r"(?<!\w)(?:us|usa|u\.?s\.?a?|united states)[- ]only\b|"
    r"(?<!\w)(?:us|usa|u\.?s\.?a?|united states)[\s-]*(?:based|resident|located)\b|"
    r"(?<!\w)(?:us|u\.?s\.?a?) citizens?\b|"
    r"work authori[sz]ation|green card|"
    r"(?<!\w)(?:w-?2|1099)\b",
    re.I)

STRONG_WORLD_RE = re.compile(
    r"\b(worldwide|world[- ]?wide|anywhere in the world|work from anywhere|"
    r"global(ly)?|any location|all countries)\b", re.I)
WEAK_WORLD_RE = re.compile(r"\banywhere\b", re.I)

_REGIONS = (r"uk|united kingdom|canada|"
            r"europe|european|eu|emea|latam|latin america|north america|americas|"
            r"australia|new zealand|germany|france|spain|poland|netherlands|"
            r"ireland|brazil|mexico|argentina|portugal|romania|india")
OTHER_REGION_RE = re.compile(rf"(?<!\w)({_REGIONS})(?!\w)", re.I)

# Restrictions that make a job unsafe to publish as India-eligible.
# These are checked BEFORE the India-location shortcut so an India-located
# posting cannot pass when its description explicitly limits eligibility.
BLOCK_RE = re.compile(
    r"visa sponsorship|sponsor(ship)? (a )?visa|sponsorship (is )?(not )?(available|provided)|"
    r"work permit|work authori[sz]ation|"
    r"(authori[sz]ed|eligible|legally (entitled|permitted|authori[sz]ed)|permitted) to work in|"
    r"right to work|security clearance|green card|"
    r"(?<!\w)(u\.?s\.?|us) citizen|citizens? only|"
    rf"must (currently )?(reside|live|be located|be based|be resident)s? in (the )?({_REGIONS})(?!\w)|"
    rf"(?<!\w)({_REGIONS})[- ]only|"
    rf"based in (the )?({_REGIONS})(?!\w)|"
    r"(?<!\w)(w-?2|1099) (only|employee)|"
    # Nationality / country-specific eligibility.
    r"\b(saudi|emirati|uae|qatari|kuwaiti|bahraini|omani|jordanian|"
    r"egyptian|mexican|canadian|australian|british|irish|german|french|"
    r"spanish|polish|brazilian) nationals? only\b|"
    r"\b(us|u\.s\.?|united states|uk|united kingdom|canada|australia|"
    r"saudi arabia|uae|emirates|qatar|kuwait|bahrain|oman|jordan|"
    r"philippines) nationals? only\b|"
    # Professional/licensing restrictions tied to a foreign jurisdiction.
    # Explicit foreign-country base requirements in title/description/location.
    r"\b(u\.?s\.?|us|united states|uk|united kingdom|canada|europe|"
    r"australia|new zealand|germany|france|spain|poland|netherlands|"
    r"ireland|brazil|mexico|argentina|portugal|romania|philippines|"
    r"saudi arabia|uae|qatar|kuwait|bahrain|oman)\s*[-,]?(?:based|resident|located|"
    r"based contractor|based remote)\b|"
    r"\b([a-z]{2}) license required\b|"
    r"\b(licensed|licensure) (in|by)\s+(the )?([a-z][a-z .-]{1,30})\b|"
    r"\bmust (hold|have|possess) (a |an )?[a-z .-]{0,25}(license|licence)\b",
    re.I)

TZ_RE = re.compile(r"overlap (with )?[^.]{0,40}\b(est|pst|cst|cet|gmt|utc|et|pt)\b|"
                   r"\b(est|pst|cst|cet) (hours|timezone|time zone)", re.I)

REMOTE_WORDS = re.compile(r"\b(remote|fully|distributed|work|from|home|wfh|"
                          r"flexible|only|position|job|jobs|hybrid)\b", re.I)


def explicit_region_restriction(job: Job) -> str:
    """Return an explicit non-India location restriction from the vacancy itself.

    ATS/aggregator location fields are sometimes over-broad (for example,
    "Anywhere in the World") while the description says "Location: EMEA".
    Specific vacancy wording must take precedence over that broad label.
    """
    text = f"{job.title}\n{job.location}\n{job.description}"
    # Labelled role-location statements are strong evidence; company headquarters
    # mentions alone are deliberately ignored.
    match = re.search(
        r"(?i)\b(?:work\s+)?location\s*:\s*"
        r"(EMEA|Europe|European Union|United States|U\.?S\.?|USA|UK|United Kingdom|"
        r"Canada|Australia|New Zealand|LATAM|Latin America)\b",
        text,
    )
    if match:
        region = match.group(1)
        if region.upper() in {"UNITED STATES", "US", "U.S.", "USA"}:
            return ""
        return f"vacancy explicitly labels location as {region}"
    patterns = (
        # US-only patterns removed for US-targeting: (r"(?i)\bremote (?:anywhere )?within the united states\b", "United States"),
        # US-only patterns removed for US-targeting: (r"(?i)\bremote (?:anywhere )?in the united states\b", "United States"),
        # US-only patterns removed for US-targeting: (r"(?i)\bposition can be remote anywhere within the united states\b", "United States"),
        # US-only patterns removed for US-targeting: (r"(?i)\b(?:united states|u\.?s\.?|usa) only\b", "United States"),
        (r"(?i)\bremote (?:anywhere )?within (?:the )?emea\b", "EMEA"),
        (r"(?i)\b(?:emea|europe|european union|uk|united kingdom|canada|australia|india) only\b", "restricted region"),
    )
    for pattern, region in patterns:
        if re.search(pattern, text):
            return f"vacancy explicitly restricts role to {region}"
    return ""


def classify(job: Job) -> tuple[str, str] | None:
    """Return (tier, note) if eligible for someone in the US, else None."""
    loc = (job.location or "").strip()
    text = f"{job.title} {job.description}"

    # Specific location restrictions in the description outrank broad aggregator tags.
    if explicit_region_restriction(job):
        return None

    # Apply explicit restrictions BEFORE accepting an India location.
    # A posting can say "India" in its location while still requiring foreign
    # work authorization, nationality, or a foreign professional license.
    if (BLOCK_RE.search(text) or BLOCK_RE.search(loc)) and not (US_FEATURE_RE.search(text) or US_FEATURE_RE.search(loc)):
        return None

    # Tier A: physically in US (office, hybrid or remote-in-US)
    if US_RE.search(loc):
        return "A", "US location"

    is_remote = bool(job.remote) or bool(re.search(r"\bremote\b", loc, re.I))
    if not is_remote:
        return None                      # on-site somewhere else -> no

    # Explicit foreign regions take precedence over broad words such as
    # "global", "APAC", or "anywhere". Example: "US, APAC" is not India-safe.
    if OTHER_REGION_RE.search(loc):
        return None

    cleaned = REMOTE_WORDS.sub(" ", re.sub(r"[^A-Za-z ]", " ", loc)).strip()
    tz_note = " (⚠ timezone overlap mentioned)" if TZ_RE.search(text) else ""

    if STRONG_WORLD_RE.search(loc):
        return "B", "Worldwide / APAC remote" + tz_note
    if WEAK_WORLD_RE.search(loc):
        return "B", "Remote - anywhere" + tz_note
    if not cleaned:
        return "C", "Remote, location not stated - verify" + tz_note
    return None                          # remote but tied to some other place


# --------------------------------------------------------------------------
# Sources (all public JSON / RSS endpoints)
# --------------------------------------------------------------------------
def fetch_remoteok(s):
    data = get(s, "https://remoteok.com/api").json()
    out = []
    for it in data:
        if not isinstance(it, dict) or "position" not in it:
            continue
        out.append(Job("RemoteOK", it.get("position", ""), it.get("company", ""),
                       it.get("location") or "", it.get("url") or it.get("apply_url", ""),
                       parse_dt(it.get("epoch") or it.get("date")),
                       strip_html(it.get("description")), remote=True))
    return out


def fetch_remotive(s):
    # NB: Remotive asks API users to poll sparingly (a few times/day) and its
    # public feed is delayed ~24h. Fine for a once-a-day run.
    data = get(s, "https://remotive.com/api/remote-jobs").json().get("jobs", [])
    return [Job("Remotive", j.get("title", ""), j.get("company_name", ""),
                j.get("candidate_required_location") or "", j.get("url", ""),
                parse_dt(j.get("publication_date")),
                strip_html(j.get("description")), remote=True) for j in data]


def fetch_jobicy(s):
    out = []
    for params in ({"count": 100, "geo": "usa"}, {"count": 100}):
        try:
            data = get(s, "https://jobicy.com/api/v2/remote-jobs", params=params).json()
        except Exception as e:
            log.warning("jobicy %s failed: %s", params, e)
            continue
        for j in data.get("jobs", []):
            geo = j.get("jobGeo", "")
            geo = ", ".join(geo) if isinstance(geo, list) else str(geo)
            out.append(Job("Jobicy", j.get("jobTitle", ""), j.get("companyName", ""),
                           geo, j.get("url", ""), parse_dt(j.get("pubDate")),
                           strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
                           remote=True))
        time.sleep(1)
    return out


def fetch_himalayas(s):
    out = []
    for offset in (0, 100):
        data = get(s, "https://himalayas.app/jobs/api",
                   params={"limit": 100, "offset": offset}).json().get("jobs", [])
        for j in data:
            restr = j.get("locationRestrictions") or []
            loc = ", ".join(restr) if restr else "Worldwide"
            out.append(Job("Himalayas", j.get("title", ""), j.get("companyName", ""),
                           loc, j.get("applicationLink") or j.get("guid", ""),
                           parse_dt(j.get("pubDate")),
                           strip_html(j.get("description") or j.get("excerpt")),
                           remote=True))
        time.sleep(1)
    return out


def fetch_wwr(s):
    out = []
    base = "https://weworkremotely.com"
    for path in ("/remote-jobs.rss",
                 "/categories/remote-programming-jobs.rss",
                 "/categories/remote-devops-sysadmin-jobs.rss"):
        root = ET.fromstring(get(s, base + path).content)
        for it in root.iter("item"):
            raw = (it.findtext("title") or "").strip()
            company, _, title = raw.partition(":")
            if not title:
                company, title = "", raw
            out.append(Job("WeWorkRemotely", title.strip(), company.strip(),
                           (it.findtext("region") or "").strip(),
                           (it.findtext("link") or "").strip(),
                           parse_dt(it.findtext("pubDate")),
                           strip_html(it.findtext("description")), remote=True))
        time.sleep(1)
    return out


def fetch_greenhouse(s, token):
    time.sleep(0.3)
    data = get(s, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
               params={"content": "true"}).json().get("jobs", [])
    return [Job(f"Greenhouse", j.get("title", ""), token.replace("-", " ").title(),
                (j.get("location") or {}).get("name", ""), j.get("absolute_url", ""),
                parse_dt(j.get("first_published") or j.get("updated_at")),
                strip_html(j.get("content"))) for j in data]


def fetch_lever(s, token):
    time.sleep(0.3)
    data = get(s, f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}).json()
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        out.append(Job("Lever", j.get("text", ""), token.replace("-", " ").title(),
                       "; ".join(l for l in locs if l), j.get("hostedUrl", ""),
                       parse_dt(j.get("createdAt")),
                       j.get("descriptionPlain", ""),
                       remote=(j.get("workplaceType") == "remote") or None))
    return out


def fetch_ashby(s, token):
    time.sleep(0.3)
    data = get(s, f"https://api.ashbyhq.com/posting-api/job-board/{token}").json().get("jobs", [])
    out = []
    for j in data:
        locs = [j.get("location", "")] + [x.get("location", "") if isinstance(x, dict) else str(x)
                                         for x in j.get("secondaryLocations") or []]
        out.append(Job("Ashby", j.get("title", ""), token.replace("-", " ").title(),
                       "; ".join(l for l in locs if l), j.get("jobUrl", ""),
                       parse_dt(j.get("publishedAt")),
                       strip_html(j.get("descriptionPlain") or j.get("descriptionHtml")),
                       remote=True if j.get("isRemote") else None))
    return out


BOARD_SOURCES = {
    "remoteok": fetch_remoteok, "remotive": fetch_remotive, "jobicy": fetch_jobicy,
    "himalayas": fetch_himalayas, "weworkremotely": fetch_wwr,
}
ATS_FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


# --------------------------------------------------------------------------
# Storage + output
# --------------------------------------------------------------------------
def job_key(j: Job) -> str:
    return hashlib.sha1((j.url or f"{j.title}|{j.company}").encode()).hexdigest()


def filter_unseen(jobs: list[Job], db_path: Path) -> list[Job]:
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS seen (k TEXT PRIMARY KEY, first_seen TEXT)")
    fresh = []
    for j in jobs:
        k = job_key(j)
        if con.execute("SELECT 1 FROM seen WHERE k=?", (k,)).fetchone() is None:
            fresh.append(j)
            con.execute("INSERT INTO seen VALUES (?,?)", (k, datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()
    return fresh


def ist(dt):
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M") if dt else ""


def write_outputs(jobs: list[Job], out_dir: Path, stamp: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"jobs_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tier", "title", "company", "location", "posted_ist", "source", "url", "note"])
        for j in jobs:
            w.writerow([j.tier, j.title, j.company, j.location, ist(j.posted), j.source, j.url, j.note])

    (out_dir / f"jobs_{stamp}.json").write_text(json.dumps([
        {"tier": j.tier, "title": j.title, "company": j.company, "location": j.location,
         "url": j.url, "source": j.source, "note": j.note, "remote": j.remote,
         "posted": j.posted.isoformat() if j.posted else None,
         "description": j.description} for j in jobs], ensure_ascii=False, indent=1),
        encoding="utf-8")

    badge = {"A": "#1a7f37", "B": "#0969da", "C": "#9a6700"}
    rows = "\n".join(
        f"<tr><td><span style='background:{badge[j.tier]};color:#fff;padding:2px 8px;border-radius:10px'>{j.tier}</span></td>"
        f"<td><a href='{html.escape(j.url)}' target='_blank' rel='noopener'>{html.escape(j.title)}</a></td>"
        f"<td>{html.escape(j.company)}</td><td>{html.escape(j.location)}</td>"
        f"<td>{ist(j.posted)}</td><td>{html.escape(j.source)}</td><td>{html.escape(j.note)}</td></tr>"
        for j in jobs)
    html_path = out_dir / f"jobs_{stamp}.html"
    html_path.write_text(f"""<!doctype html><meta charset="utf-8"><title>Jobs {stamp}</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}th{{background:#f6f8fa}}</style>
<h2>{len(jobs)} new US-eligible jobs - {stamp}</h2>
<p>A = located in the US &nbsp; B = worldwide remote &nbsp; C = remote, location unstated (verify)</p>
<table><tr><th>Tier</th><th>Title</th><th>Company</th><th>Location</th><th>Posted (IST)</th><th>Source</th><th>Note</th></tr>
{rows}</table>""", encoding="utf-8")
    return csv_path, html_path


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def selftest():
    cases = [
        (Job("t", "Dev", "x", "Bengaluru, Karnataka", "u", None), "A"),
        (Job("t", "Dev", "x", "Remote - US", "u", None, remote=True), None),
        (Job("t", "Dev", "x", "Remote - Anywhere in the US", "u", None, remote=True), None),
        (Job("t", "Dev", "x", "USA Only", "u", None, remote=True), None),
        (Job("t", "Dev", "x", "Worldwide", "u", None, "We do not offer visa sponsorship.", remote=True), None),
        (Job("t", "Dev", "x", "Worldwide", "u", None, "Build cool things.", remote=True), "B"),
        (Job("t", "Dev", "x", "Anywhere in the World", "u", None, remote=True), "B"),
        (Job("t", "Dev", "x", "Remote", "u", None, "Python role.", remote=True), "C"),
        (Job("t", "Dev", "x", "San Francisco, CA", "u", None), None),
        (Job("t", "Dev", "x", "Remote, Europe", "u", None, remote=True), None),
        (Job("t", "Dev", "x", "Remote - India", "u", None, remote=True), "A"),
        (Job("t", "Dev", "x", "Worldwide", "u", None, "Must be authorized to work in the UK", remote=True), None),
        (Job("t", "Nurse Practitioner", "x", "Remote", "u", None, "Active CT license required.", remote=True), None),
        (Job("t", "Account Executive", "x", "Riyadh, Saudi Arabia", "u", None, "Saudi nationals only.", remote=False), None),
        (Job("t", "Engineer", "x", "Remote - US, APAC", "u", None, "Global team.", remote=True), None),
        (Job("t", "Engineer", "x", "Bengaluru, India", "u", None, "US work authorization required.", remote=False), None),
        (Job("t", "Content Coordinator (U.S. Based, Remote Contractor)", "x",
             "Anywhere in the World", "u", None, "Content coordination.", remote=True), None),
        (Job("WeWorkRemotely", "Sr. Motion Designer", "Zapier", "Anywhere in the World", "u", None,
             "Location: EMEA\\nWe are looking for a Motion Designer to create product explainers.", remote=True), None),
        (Job("WeWorkRemotely", "Principal Product Marketing Manager", "ClickHouse", "Anywhere in the World", "u", None,
             "NOTE: this position can be remote anywhere within the United States. As the Principal Product Manager for ClickHouse Cloud, lead the database roadmap.", remote=True), None),
        (Job("t", "Designer", "Example", "Worldwide", "u", None,
             "Headquarters: United States\\nA worldwide remote role open to candidates in all countries.", remote=True), "B"),
    ]
    bad = 0
    for job, want in cases:
        res = classify(job)
        got = res[0] if res else None
        ok = got == want
        bad += not ok
        print(("PASS" if ok else "FAIL"), f"{job.location!r:40} -> {got} (want {want})")
    print("\nAll good." if not bad else f"\n{bad} failure(s).")
    raise SystemExit(bad)


def _configure_console_encoding() -> None:
    """Prevent Windows legacy console code pages from crashing on Unicode logs."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                # The pipeline must still run when stdout/stderr are redirected or wrapped.
                pass


def main():
    _configure_console_encoding()
    ap = argparse.ArgumentParser(description="Daily US-eligible job scraper")
    ap.add_argument("--hours", type=int, default=24, help="freshness window (default 24)")
    ap.add_argument("--today", action="store_true", help="only jobs posted since midnight IST")
    ap.add_argument("--all", action="store_true", help="don't hide jobs seen in earlier runs")
    ap.add_argument("--keywords", default="", help="comma list; title must match any")
    ap.add_argument("--exclude", default="", help="comma list; drop if title matches any")
    ap.add_argument("--strict", action="store_true", help="drop Tier C (location unstated)")
    ap.add_argument("--no-boards", action="store_true", help="skip remote job boards")
    ap.add_argument("--companies", default=str(HERE / "companies.json"))
    ap.add_argument("--out", default=str(HERE / "output"))
    ap.add_argument("--db", default=str(HERE / "jobs_seen.db"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if a.selftest:
        selftest()

    now = datetime.now(timezone.utc)
    if a.today:
        cutoff = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    else:
        cutoff = now - timedelta(hours=a.hours)
    log.info("Looking for jobs posted after %s IST", ist(cutoff))

    # Build task list
    tasks = []
    s = make_session()
    if not a.no_boards:
        tasks += [(n, lambda f=f: f(s)) for n, f in BOARD_SOURCES.items()]
    cp = Path(a.companies)
    if cp.exists():
        for ats, tokens in json.loads(cp.read_text()).items():
            if ats.startswith("_") or ats not in ATS_FETCHERS:
                continue
            tasks += [(f"{ats}:{t}", lambda f=ATS_FETCHERS[ats], t=t: f(s, t)) for t in tokens]

    raw: list[Job] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fn): name for name, fn in tasks}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                res = fut.result()
                log.info("%-28s %4d postings", name, len(res))
                raw += res
            except Exception as e:
                log.warning("%-28s FAILED: %s", name, e)

    # Filter: fresh -> eligible -> keywords -> dedupe -> unseen
    kw = [k.strip().lower() for k in a.keywords.split(",") if k.strip()]
    ex_kw = [k.strip().lower() for k in a.exclude.split(",") if k.strip()]
    undated = 0
    keep, seen_urls = [], set()
    for j in raw:
        if j.posted is None:
            undated += 1
            continue
        if j.posted < cutoff or not j.url or j.url in seen_urls:
            continue
        verdict = classify(j)
        if not verdict:
            continue
        j.tier, j.note = verdict
        if a.strict and j.tier == "C":
            continue
        t = j.title.lower()
        if kw and not any(k in t for k in kw):
            continue
        if any(k in t for k in ex_kw):
            continue
        seen_urls.add(j.url)
        keep.append(j)

    log.info("%d postings fetched | %d without a date (skipped) | %d fresh & eligible",
             len(raw), undated, len(keep))
    if not a.all:
        keep = filter_unseen(keep, Path(a.db))
        log.info("%d are new since your last run", len(keep))

    keep.sort(key=lambda j: (j.tier, -(j.posted.timestamp() if j.posted else 0)))
    stamp = datetime.now(IST).strftime("%Y-%m-%d")
    if not keep:
        log.info("Nothing new. Try --hours 72 or --all.")
        return
    csv_path, html_path = write_outputs(keep, Path(a.out), stamp)
    print(f"\n{len(keep)} jobs  ->  {html_path}\n               {csv_path}\n")
    for j in keep[:15]:
        print(f"[{j.tier}] {j.title} @ {j.company} | {j.location} | {ist(j.posted)} | {j.source}")
    if len(keep) > 15:
        print(f"... and {len(keep) - 15} more in the report")


if __name__ == "__main__":
    main()
