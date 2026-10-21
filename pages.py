"""Generate the Road Beyond Roles GitHub Pages website."""
import html
import json
import re
from pathlib import Path
from urllib.parse import quote


e = html.escape

BRAND = "Road Beyond Roles"
TAGLINE = "Helping You Build a Better Career."
YOUTUBE_URL = "https://www.youtube.com/@roadbeyondrole"

TIER = {
    "A": ("India", "#166534"),
    "B": ("Worldwide remote", "#1d4ed8"),
    "C": ("Remote - verify", "#b45309"),
}

STYLE = r"""
:root{--navy:#102746;--navy-2:#18395f;--blue:#1769e8;--blue-hover:#0e55c5;--ink:#1c2b40;--muted:#64748b;--line:#dbe3ed;--soft:#f4f7fb;--white:#fff;--green:#157347}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);font:14px/1.5 Inter,"Segoe UI",Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}a{color:inherit}button,input,select{font:inherit}.container{width:min(1280px,calc(100% - 48px));margin:0 auto}
.topbar{background:#fff;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20}.nav{min-height:68px;display:flex;align-items:center;gap:28px}.brand{display:flex;align-items:center;gap:10px;text-decoration:none;white-space:nowrap}.logo{width:34px;height:34px;object-fit:contain}.brand-copy{line-height:1.15}.brand-name{font-size:16px;font-weight:800;letter-spacing:-.5px;color:var(--navy)}.brand-name span{color:var(--blue)}.brand-tag{font-size:9px;letter-spacing:.25px;color:var(--muted);margin-top:4px}.navlinks{display:flex;align-items:center;justify-content:flex-end;gap:20px;margin-left:auto;white-space:nowrap}.navlinks a{font-size:12px;font-weight:650;color:#34445b;text-decoration:none;padding:25px 0 23px;border-bottom:2px solid transparent}.navlinks a:hover,.navlinks a.active{color:var(--blue);border-color:var(--blue)}.navlinks .youtube{padding:9px 12px;border:1px solid var(--line);border-radius:6px;color:var(--navy)}
.content{padding:24px 0 56px}.page-head{padding:28px 0 20px;border-bottom:1px solid var(--line);background:#fff}.breadcrumbs{font-size:11px;color:var(--muted);margin-bottom:10px}.page-head h1{font-size:28px;letter-spacing:-.8px;line-height:1.2;margin:0;font-weight:760;color:var(--navy)}.page-head p{margin:7px 0 0;color:var(--muted);font-size:13px;max-width:760px}
.searchbar{display:grid;grid-template-columns:minmax(220px,1fr) 150px;gap:8px;margin-top:20px}.search{width:100%;min-width:0;padding:12px 14px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:var(--ink);font-size:13px;outline:none}.search:focus,.filter:focus{border-color:var(--blue);box-shadow:0 0 0 3px #1769e81a}.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:36px;padding:9px 13px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:var(--navy);text-decoration:none;font-size:12px;font-weight:700;cursor:pointer}.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}.btn.primary:hover{background:var(--blue-hover)}.btn:hover{border-color:#91a4bd}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}.filter{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:#34445b;font-size:11px}.filter-link{display:inline-flex;align-items:center;padding:7px 10px;border:1px solid var(--line);border-radius:6px;color:#34445b;text-decoration:none;font-size:11px}.filter-link.active,.filter-link:hover{border-color:#a8c7ff;background:#eff5ff;color:var(--blue)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px;padding:24px 0 56px}.maincol{min-width:0}.sidecol{min-width:0}.results-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.results-head h2{font-size:18px;letter-spacing:-.35px;margin:0;color:var(--navy)}.results-head p{font-size:11px;color:var(--muted);margin:4px 0 0}.sort{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font-size:11px;color:#34445b}
.job-list{border:1px solid var(--line);border-radius:8px;overflow:hidden}.job{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:13px;padding:17px 16px;border-bottom:1px solid var(--line);background:#fff;margin:0;align-items:start}.job:last-child{border-bottom:0}.job:hover{background:#f9fbff}.company-mark{display:flex;align-items:center;justify-content:center;width:38px;height:38px;border:1px solid #e7edf5;border-radius:7px;background:#fff;color:var(--navy);font-size:13px;font-weight:800}.job-main{min-width:0}.job-title{font-size:14px;font-weight:750;line-height:1.35;margin:0 0 4px;color:var(--navy)}.job-title a{text-decoration:none}.job-title a:hover{color:var(--blue)}.company-line{font-size:12px;color:#41536b}.meta{display:flex;flex-wrap:wrap;gap:6px 13px;margin-top:9px;font-size:11px;color:var(--muted)}.tag-row{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}.chip{display:inline-flex;align-items:center;padding:3px 7px;border-radius:4px;background:#f1f5f9;color:#42536a;font-size:10px;line-height:1.4}.chip.m{background:#edf4ff;color:#235bb0;border:1px solid #d9e7ff}.job-actions{display:flex;flex-direction:column;align-items:stretch;gap:6px;min-width:88px}.job-actions .btn{min-height:31px;padding:7px 10px;font-size:11px}.job-actions .btn:not(.primary){border-color:transparent}.rank,.badge{display:none}
.side-panel{border:1px solid var(--line);border-radius:8px;margin-bottom:14px;background:#fff;overflow:hidden}.side-panel h3{font-size:14px;font-weight:750;margin:0;padding:13px 14px;border-bottom:1px solid var(--line);color:var(--navy)}.side-content{padding:12px 14px}.resource-link{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid #edf1f6;text-decoration:none;font-size:12px;color:#34445b}.resource-link:last-child{border-bottom:0}.resource-link:hover{color:var(--blue)}.resource-link small{display:block;color:var(--muted);font-size:10px;margin-top:2px}.youtube-panel{background:var(--navy);color:#fff;padding:16px;border-radius:8px;margin-bottom:14px}.youtube-panel h3{font-size:14px;margin:0 0 6px}.youtube-panel p{font-size:11px;color:#d5dfed;margin:0 0 12px}.youtube-panel .btn{background:#fff;color:var(--navy);border-color:#fff}
.stats{display:flex;flex-wrap:wrap;gap:0;border-bottom:1px solid var(--line);background:#f8fafc}.stat{flex:1;min-width:150px;padding:15px 18px;border-right:1px solid var(--line)}.stat:last-child{border-right:0}.stat strong{display:block;color:var(--navy);font-size:18px;line-height:1.25}.stat span{font-size:10px;color:var(--muted)}
.source-description{color:var(--ink);overflow-wrap:anywhere}
.source-description p{margin:0 0 16px;white-space:normal}
.source-description p:last-child{margin-bottom:0}
.source-description h3{font-size:16px;font-weight:900;text-transform:uppercase;letter-spacing:.35px;margin:24px 0 10px}
.source-description ul{margin:8px 0 18px;padding-left:24px}
.source-description li{margin:0 0 8px;padding-left:4px}
.source-description a{color:var(--blue);text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}
.source-description a:hover{color:var(--blue-dark)}
.detail{padding:22px 0 58px}.detail-card{max-width:1100px;margin:0 auto}.back{display:inline-block;font-size:11px;color:var(--blue);text-decoration:none;margin-bottom:16px}.detail-head{border:1px solid var(--line);border-radius:8px;padding:20px;background:#fff}.detail-title-row{display:flex;align-items:flex-start;gap:14px}.detail-card h1{font-size:26px;line-height:1.25;letter-spacing:-.6px;margin:0 0 6px;color:var(--navy)}.detail-company{font-size:14px;font-weight:650;color:#40536d}.detail-actions{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}.detail-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:13px}.detail-meta span{background:#f1f5f9;border:1px solid #e4eaf2;padding:5px 8px;border-radius:4px;font-size:10px;color:#42536a}.detail-tabs{display:flex;flex-wrap:wrap;gap:0;margin:14px 0;border-bottom:1px solid var(--line)}.detail-tabs a{padding:11px 13px;text-decoration:none;font-size:11px;color:#4c5d73;border-bottom:2px solid transparent}.detail-tabs a:hover{color:var(--blue);border-color:var(--blue)}.detail-columns{display:grid;grid-template-columns:minmax(0,1fr) 285px;gap:16px}.detail-section{border:1px solid var(--line);border-radius:8px;background:#fff;margin-bottom:13px;padding:17px}.detail-section h2{font-size:14px;color:var(--navy);margin:0 0 10px;font-weight:750}.detail-copy,.detail-list{font-size:12px;line-height:1.75;color:#43536a;margin:0}.detail-list{padding-left:18px}.detail-list li{margin:0 0 5px}.keyword-groups{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 13px}.keyword-group{border:1px solid var(--line);border-radius:8px;padding:14px;background:#fff}.keyword-group>b{display:block;font-size:12px;margin-bottom:9px;color:var(--navy)}.course-list,.question-list{margin:0;padding:0;list-style:none}.course-list li,.question-list li{padding:9px 0;border-bottom:1px solid #edf1f6;font-size:12px}.course-list li:last-child,.question-list li:last-child{border-bottom:0}.course-list a{color:var(--blue);text-decoration:none;font-weight:650}.course-list small{display:block;color:var(--muted);font-size:10px;margin-top:3px}.mut{color:var(--muted);font-size:11px}.notice{margin:18px 0 0;padding:13px;background:#f8fafc;border:1px solid var(--line);border-radius:6px;color:#596a80;font-size:11px;line-height:1.65}.archive-list{border-top:1px solid var(--line);margin-top:20px;padding-top:14px}.archive-list a{color:var(--blue);font-size:13px;font-weight:700;text-decoration:none}.archive-list li{margin:9px 0}.company-grid,.resource-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.company-card,.resource-card{border:1px solid var(--line);border-radius:8px;padding:16px;background:#fff}.company-card h3,.resource-card h3{font-size:14px;margin:0 0 6px;color:var(--navy)}.company-card p,.resource-card p{font-size:11px;color:var(--muted);margin:0 0 10px}.footer{border-top:1px solid var(--line);background:#f8fafc;padding:23px 0}.footer-grid{display:flex;justify-content:space-between;align-items:center;gap:20px}.footer-brand{font-size:12px;font-weight:800;letter-spacing:.2px;color:var(--navy)}.footer p{margin:4px 0 0;color:var(--muted);font-size:10px}.footer-yt{font-size:11px;font-weight:700;color:var(--blue);text-decoration:none}
@media(max-width:1080px){.nav{flex-wrap:wrap;padding:12px 0;gap:12px}.navlinks{order:3;width:100%;justify-content:flex-start;overflow-x:auto;gap:18px}.navlinks a{padding:8px 0}.layout{grid-template-columns:minmax(0,1fr) 250px}.detail-columns{grid-template-columns:minmax(0,1fr) 250px}}
@media(max-width:760px){.container{width:calc(100% - 28px)}.layout,.detail-columns{grid-template-columns:1fr}.sidecol{display:grid;grid-template-columns:1fr 1fr;gap:12px}.youtube-panel{grid-column:1/-1}.side-panel{margin-bottom:0}.detail-title-row{flex-wrap:wrap}.detail-actions{margin-left:0;width:100%}.detail-actions .btn{flex:1}.keyword-groups{grid-template-columns:1fr 1fr}.company-grid,.resource-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:520px){.brand-tag{display:none}.brand-name{font-size:14px}.navlinks{gap:15px}.navlinks a{font-size:11px}.searchbar{grid-template-columns:1fr}.searchbar .btn{width:100%}.page-head h1{font-size:24px}.stats{display:grid;grid-template-columns:1fr 1fr}.stat{min-width:0;border-bottom:1px solid var(--line);padding:12px}.job{grid-template-columns:34px minmax(0,1fr);padding:13px 11px;gap:9px}.company-mark{width:32px;height:32px}.job-actions{grid-column:2;flex-direction:row;min-width:0}.job-actions .btn{flex:1}.sidecol{display:block}.side-panel{margin-bottom:12px}.keyword-groups{grid-template-columns:1fr}.company-grid,.resource-grid{grid-template-columns:1fr}.detail-card h1{font-size:22px}.detail-tabs{overflow-x:auto;flex-wrap:nowrap}.detail-tabs a{white-space:nowrap}.footer-grid{align-items:flex-start;flex-direction:column}}
"""


def job_source_url(j: dict) -> str:
    """Return the posting's real source URL; no synthetic job ID is needed."""
    for key in ("url", "original_url", "source_url", "application_url", "apply_url"):
        value = str(j.get(key) or "").strip()
        if value.startswith(("https://", "http://")):
            return value
    return ""


def job_page_url(site_url: str, j: dict) -> str:
    """Build the detail-page URL from the real posting URL, not a generated ID."""
    source_url = job_source_url(j)
    return f"{site_url.rstrip('/')}/job.html?url={quote(source_url, safe='')}"


def header(asset_prefix: str, active: str = "") -> str:
    links = [
        ("Home", "index.html", "home"), ("Jobs", "jobs.html", "jobs"),
        ("Internships", "internships.html", "internships"), ("Apprenticeships", "apprenticeships.html", "apprenticeships"),
        ("Companies", "companies.html", "companies"), ("Career Tips", "career-tips.html", "career-tips"),
        ("Interview Prep", "interview-prep.html", "interview-prep"), ("Resume Guide", "resume-guide.html", "resume-guide"),
        ("Free Courses", "free-courses.html", "free-courses"),
    ]
    nav = "".join(f"<a class='{"active" if key == active else ""}' href='{asset_prefix}{href}'>{label}</a>" for label, href, key in links)
    return f"""
<header class='topbar'><div class='container nav'>
  <a class='brand' href='{asset_prefix}index.html'><img class='logo' src='{asset_prefix}assets/rbr-logo.jpg' alt='Road Beyond Roles'><div class='brand-copy'><div class='brand-name'>ROAD <span>BEYOND</span> ROLES</div><div class='brand-tag'>Jobs · Internships · Apprenticeships</div></div></a>
  <nav class='navlinks' aria-label='Main navigation'>{nav}<a class='youtube' href='{YOUTUBE_URL}' target='_blank' rel='noopener'>YouTube ↗</a></nav>
</div></header>"""


def footer() -> str:
    return f"""
<footer class='footer'><div class='container footer-grid'>
  <div><div class='footer-brand'>ROAD BEYOND ROLES</div><p>{TAGLINE}</p><p>Fresh opportunities · Career guidance · Growth</p></div>
  <a class='footer-yt' href='{YOUTUBE_URL}' target='_blank' rel='noopener'>Watch the YouTube channel ↗</a>
</div></footer>
"""


def page(title: str, body: str, asset_prefix: str = "", active: str = "") -> str:
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{e(title)}</title><meta name='description' content='{e(TAGLINE)} Road Beyond Roles brings fresh career opportunities and practical career guidance.'>
<style>{STYLE}</style></head><body>{header(asset_prefix, active)}{body}{footer()}
<script>
function filterJobs(){{const q=document.getElementById('q');const v=(q?.value||'').toLowerCase().trim();document.querySelectorAll('.job').forEach(d=>{{d.style.display=!v||d.textContent.toLowerCase().includes(v)?'':'none'}});}}
function filterCards(){{const q=document.getElementById('q');const v=(q?.value||'').toLowerCase().trim();document.querySelectorAll('.company-card').forEach(d=>{{d.style.display=!v||d.textContent.toLowerCase().includes(v)?'':'none'}});}}
const q=document.getElementById('q');q?.addEventListener('input',()=>{{if(document.querySelector('.job'))filterJobs();if(document.querySelector('.company-card'))filterCards();}});
</script></body></html>"""


def job_html(j: dict, rank: int, asset_prefix: str = "") -> str:
    j = normalize_job_fields(j)
    company = str(j.get("company", "Company"))
    mark = e("".join(word[0] for word in re.findall(r"[A-Za-z0-9]+", company)[:2]).upper() or "J")
    keywords = list(j.get("must", []))[:3] + list(j.get("nice", []))[:2]
    chips = "".join(f"<span class='chip'>{e(k)}</span>" for k in keywords)
    source_url = job_source_url(j)
    internal = f"{asset_prefix}job.html?url={quote(source_url, safe='')}" if source_url else f"{asset_prefix}jobs.html"
    extra = " · ".join(x for x in (j.get("experience"), j.get("salary")) if x)
    return f"""
<article class='job' data-category='{e(job_category(j))}'>
  <div class='company-mark' aria-hidden='true'>{mark}</div>
  <div class='job-main'><h3 class='job-title'><a href='{e(internal)}'>{e(j.get('title','Career Opportunity'))}</a></h3>
  <div class='company-line'>{e(company)}</div>
  <div class='meta'>{''.join(f"<span>{e(value)}</span>" for value in [j.get('location'), j.get('work_mode') or j.get('workplace_type'), j.get('employment_type') or j.get('job_type'), j.get('experience'), (f"Posted {j.get('posted')}" if j.get('posted') else '')] if value)}{f'<span>{e(extra)}</span>' if extra else ''}</div>
  <div class='tag-row'>{chips}</div></div>
  <div class='job-actions'><a class='btn primary' href='{e(internal)}'>View</a><a class='btn' href='{e(j.get('url',''))}' target='_blank' rel='noopener nofollow'>Apply ↗</a></div>
</article>"""


def job_category(j: dict) -> str:
    text = " ".join(str(j.get(k, "")) for k in ("title", "employment_type", "job_type")).lower()
    if "apprentice" in text or "apprenticeship" in text:
        return "apprenticeships"
    if "intern" in text or "internship" in text:
        return "internships"
    return "jobs"



def normalize_job_fields(job: dict) -> dict:
    """Normalize work mode, employment type and salary from supplied feed/full text."""
    item = dict(job)
    desc = str(item.get("description") or "")
    title = str(item.get("title") or "")
    loc = str(item.get("location") or "")
    text = f"{title}\n{loc}\n{desc}".lower()

    # Explicit structured values always win; otherwise infer only from clear evidence.
    work = str(item.get("work_mode") or item.get("workplace_type") or "").strip()
    if not work:
        # Explicit field labels in the original posting outrank broad keyword inference.
        labeled_work = re.search(r"(?im)^\s*(?:workplace type|work arrangement|work mode|location type)\s*[:—-]\s*(remote|hybrid|on[- ]site|onsite)\b", desc)
        if labeled_work:
            work = labeled_work.group(1).replace("on-site", "On-site").replace("onsite", "On-site").title()
        elif re.search(r"\bhybrid\b", text):
            work = "Hybrid"
        elif re.search(r"\b(on[- ]site|onsite|in[- ]office|office[- ]based)\b", text):
            work = "On-site"
        elif item.get("remote") is True or re.search(r"\b(remote|work from home|anywhere in the world|worldwide|distributed team)\b", text):
            work = "Remote"
        else:
            work = ""
    item["work_mode"] = work

    employment = str(item.get("employment_type") or item.get("job_type") or "").strip()
    if not employment:
        labeled_employment = re.search(r"(?im)^\s*(?:employment type|job type|employment|position type)\s*[:—-]\s*(full[- ]time|part[- ]time|contract(?:or)?|temporary|permanent|internship|apprenticeship|freelance)\b", desc)
        if labeled_employment:
            raw = labeled_employment.group(1).lower().replace("-", " ")
            employment = {"full time":"Full-time", "part time":"Part-time", "contractor":"Contract", "contract":"Contract", "temporary":"Temporary", "permanent":"Permanent", "internship":"Internship", "apprenticeship":"Apprenticeship", "freelance":"Freelance"}.get(raw, raw.title())
        elif re.search(r"\b(intern(ship)?|internship program)\b", title.lower()): employment = "Internship"
        elif re.search(r"\b(apprentice|apprenticeship)\b", title.lower()): employment = "Apprenticeship"
        elif re.search(r"\b(contract|contractor|freelance|fixed[- ]term)\b", text): employment = "Contract"
        elif re.search(r"\b(part[- ]time|part time)\b", text): employment = "Part-time"
        elif re.search(r"\b(full[- ]time|full time|permanent position|permanent role)\b", text): employment = "Full-time"
        else: employment = ""
    item["employment_type"] = employment

    experience = str(item.get("experience") or item.get("experience_level") or "").strip()
    if not experience:
        exp_patterns = [
            r"(?im)^\s*(?:experience|years of experience|experience required|required experience)\s*[:—-]\s*([^\n.;]{2,90})",
            r"(?i)\b((?:minimum of |at least )?\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\s+years?\s+(?:of )?experience)\b",
            r"(?i)\b((?:minimum of |at least )?\d{1,2}\+?\s+years?\s+(?:of )?experience)\b",
            r"(?i)\b(entry[- ]level|early career|mid[- ]level|senior[- ]level|junior|senior|staff|principal)\b",
        ]
        for pattern in exp_patterns:
            match = re.search(pattern, desc)
            if match:
                experience = re.sub(r"\s+", " ", match.group(1)).strip(" .;:")
                break
    item["experience"] = experience

    # Reject label-only feed values such as "range for this role is"; a salary must contain a numeric amount.
    salary = str(item.get("salary") or "").strip()
    if not re.search(r"\d", salary):
        salary = ""
    research = item.get("salary_research") if isinstance(item.get("salary_research"), dict) else {}
    if not salary and research.get("range"):
        salary = str(research.get("range") or "").strip()
        kind = str(research.get("kind") or "").strip()
        source = str(research.get("source") or "").strip()
        if kind == "employer_posted":
            item["salary_type"] = "Employer-posted compensation"
        elif kind == "market_estimate":
            item["salary_type"] = "Role-matched market estimate"
        elif source:
            item["salary_type"] = f"Source evidence: {source}"
        item["salary"] = salary
    if not salary:
        # Extract actual monetary ranges anywhere in the full description, including headings
        # such as "The anticipated salary range for this role is" followed by metro bands.
        money = r"(?:USD\s*)?(?:US\$|\$|₹|INR\s*)?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?:USD\s*)?\d{5,7}(?:\.\d+)?"
        range_pattern = re.compile(rf"(?<![\w])({money})\s*(?:-|–|—|to)\s*({money})(?:\s*(?:USD|INR|per year|/year|annually|per annum|LPA))?", re.I)
        ranges = []
        for match in range_pattern.finditer(desc):
            raw = match.group(0).strip()
            # Keep only plausible salary ranges; avoid dates and small numeric ranges.
            nums = [int(re.sub(r"[^0-9]", "", x)) for x in match.groups()]
            if len(nums) == 2 and min(nums) >= 1000 and max(nums) > min(nums):
                ranges.append((min(nums), max(nums), raw))
        if ranges:
            low = min(x[0] for x in ranges)
            high = max(x[1] for x in ranges)
            # Reformat as a clear range instead of returning the surrounding sentence fragment.
            currency = "₹" if re.search(r"₹|\bINR\b|LPA", desc, re.I) else "$"
            suffix = "INR/year" if currency == "₹" else "USD/year"
            salary = f"{currency}{low:,}–{currency}{high:,} {suffix} (employer lists location-specific ranges)"
            item["salary"] = salary
            item["salary_type"] = "Employer-stated (range extracted from posting text)"
        else:
            # Feed fields sometimes contain a valid number/range even without a currency symbol.
            feed_salary = str(job.get("salary") or "").strip()
            if re.search(r"\d", feed_salary):
                salary = feed_salary
                item["salary"] = salary
                item["salary_type"] = "Source/feed value — verify against employer posting"
    if salary and not item.get("salary_type"):
        item["salary_type"] = "Source/feed value — verify against employer posting"
    if not salary:
        item["salary"] = ""
        item["salary_type"] = "Not found in feed or description; market research required"
    return item

def parse_description(text: str) -> list[dict[str, object]]:
    """Keep the employer description intact; never split it into sentence-sized items."""
    source = str(text or "").replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()
    return [{"heading": "Original job description", "items": [source]}] if source else []

def build_site(date: str, ranked: list[dict], agg, docs: Path, channel: str, youtube_url: str = "") -> None:
    (docs / "archive").mkdir(parents=True, exist_ok=True)
    (docs / "data").mkdir(exist_ok=True)
    (docs / "assets").mkdir(exist_ok=True)
    (docs / ".nojekyll").write_text("", encoding="utf-8")

    slim = []
    for j in ranked:
        item = normalize_job_fields(j)
        item["description_sections"] = parse_description(j.get("description", ""))
        slim.append(item)
    (docs / "data" / f"{date}.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")

    yt = youtube_url or YOUTUBE_URL
    today_jobs = "".join(job_html(j, i) for i, j in enumerate(ranked, 1))
    internship_jobs = [j for j in ranked if job_category(j) == "internships"]
    apprenticeship_jobs = [j for j in ranked if job_category(j) == "apprenticeships"]
    regular_jobs = [j for j in ranked if job_category(j) == "jobs"]

    def listing_page(title: str, description: str, items: list[dict], active: str, filename: str, asset_prefix: str = "") -> None:
        rows = "".join(job_html(j, i, asset_prefix) for i, j in enumerate(items, 1))
        if not rows:
            rows = "<div class='notice'>No matching opportunities are available in this feed yet. New listings will appear when eligible postings are found. Older jobs are not added to fill the page.</div>"
        body = f"""
<main><section class='page-head'><div class='container'><div class='breadcrumbs'>Home / {e(title)}</div><h1>{e(title)}</h1><p>{e(description)}</p>
<form class='searchbar' onsubmit='event.preventDefault();filterJobs()'><input id='q' class='search' placeholder='Job title, skills, company or keywords' aria-label='Search jobs'><button class='btn primary' type='submit'>Search</button></form>
<div class='filters'><a class='filter-link' href='{asset_prefix}jobs.html'>All jobs</a><a class='filter-link' href='{asset_prefix}internships.html'>Internships</a><a class='filter-link' href='{asset_prefix}apprenticeships.html'>Apprenticeships</a></div>
</div></section><div class='container layout'><section class='maincol'><div class='results-head'><div><h2>{len(items)} opportunities</h2><p>Source links are provided on each listing. Check the employer page before applying.</p></div><select class='sort' aria-label='Sort opportunities'><option>Most relevant</option><option>Most recent</option></select></div><div class='job-list' id='job-list'>{rows}</div></section>
<aside class='sidecol'><section class='youtube-panel'><h3>Road Beyond Roles on YouTube</h3><p>Job walkthroughs, interview preparation, resume guidance and career advice.</p><a class='btn' href='{e(yt)}' target='_blank' rel='noopener'>Watch videos ↗</a></section><section class='side-panel'><h3>Career resources</h3><div class='side-content'><a class='resource-link' href='{asset_prefix}resume-guide.html'><span>Resume guide<small>Write for the role</small></span>→</a><a class='resource-link' href='{asset_prefix}interview-prep.html'><span>Interview preparation<small>Practice role-based questions</small></span>→</a><a class='resource-link' href='{asset_prefix}free-courses.html'><span>Free courses<small>Build relevant skills</small></span>→</a><a class='resource-link' href='{asset_prefix}career-tips.html'><span>Career tips<small>Improve your job search</small></span>→</a></div></section></aside></div></main>"""
        (docs / filename).write_text(page(f"{BRAND} · {title}", body, asset_prefix, active), encoding="utf-8")

    home_body = f"""
<main><section class='page-head'><div class='container'><div class='breadcrumbs'>Home</div><h1>Find jobs, internships and apprenticeships</h1><p>Search current opportunities, review the requirements, and prepare your application with role-specific guidance.</p>
<form class='searchbar' onsubmit='event.preventDefault();filterJobs()'><input id='q' class='search' placeholder='Job title, skills, company or keywords' aria-label='Search opportunities'><button class='btn primary' type='submit'>Search</button></form>
<div class='filters'><a class='filter-link active' href='jobs.html'>Jobs</a><a class='filter-link' href='internships.html'>Internships</a><a class='filter-link' href='apprenticeships.html'>Apprenticeships</a><a class='filter-link' href='companies.html'>Companies</a></div></div></section>
<div class='stats'><div class='container' style='display:flex;flex-wrap:wrap;padding:0'><div class='stat'><strong>{len(ranked)}</strong><span>Current opportunities in this feed</span></div><div class='stat'><strong>{len({str(j.get('company','')).strip() for j in ranked if j.get('company')})}</strong><span>Employers represented</span></div><div class='stat'><strong>{e(date)}</strong><span>Feed date</span></div><div class='stat'><strong>Guides</strong><span>Resume and interview resources</span></div></div></div>
<div class='container layout'><section class='maincol'><div class='results-head'><div><h2>Latest opportunities</h2><p>Browse the latest qualifying postings available in the current feed.</p></div><a class='btn' href='jobs.html'>All jobs →</a></div><div class='job-list' id='job-list'>{today_jobs or "<div class='notice'>No qualifying jobs were found for this feed date.</div>"}</div><div class='notice'>Listings link to their original source. Always confirm eligibility, location, compensation and application status on the employer's website.</div></section>
<aside class='sidecol'><section class='youtube-panel'><h3>Video guides</h3><p>Job walkthroughs, interview preparation, resume guidance and practical career advice.</p><a class='btn' href='{e(yt)}' target='_blank' rel='noopener'>Watch on YouTube ↗</a></section><section class='side-panel'><h3>Career resources</h3><div class='side-content'><a class='resource-link' href='resume-guide.html'><span>Resume guide<small>Tailor your resume to the role</small></span>→</a><a class='resource-link' href='interview-prep.html'><span>Interview preparation<small>Questions and answer frameworks</small></span>→</a><a class='resource-link' href='free-courses.html'><span>Free courses<small>Learn skills required by employers</small></span>→</a><a class='resource-link' href='career-tips.html'><span>Career tips<small>Search and application advice</small></span>→</a></div></section><section class='side-panel'><h3>Browse opportunities</h3><div class='side-content'><a class='resource-link' href='jobs.html'><span>Jobs</span>→</a><a class='resource-link' href='internships.html'><span>Internships</span>→</a><a class='resource-link' href='apprenticeships.html'><span>Apprenticeships</span>→</a></div></section></aside></div></main>"""
    (docs / "index.html").write_text(page(f"{BRAND} · Home", home_body, active="home"), encoding="utf-8")

    listing_page("Jobs", "Find current full-time, part-time and contract roles. Use the official employer posting to confirm the details.", regular_jobs, "jobs", "jobs.html")
    listing_page("Internships", "Explore internship opportunities and review the requirements before applying.", internship_jobs, "internships", "internships.html")
    listing_page("Apprenticeships", "Find apprenticeship opportunities that offer structured workplace learning.", apprenticeship_jobs, "apprenticeships", "apprenticeships.html")

    companies = sorted({str(j.get("company", "")).strip() for j in ranked if str(j.get("company", "")).strip()}, key=str.casefold)
    company_cards = "".join(f"<article class='company-card'><h3>{e(company)}</h3><p>{sum(1 for j in ranked if str(j.get('company','')).strip().casefold()==company.casefold())} current listing(s) in this feed</p><a class='btn' href='jobs.html'>Browse listings →</a></article>" for company in companies)
    companies_body = f"<main><section class='page-head'><div class='container'><div class='breadcrumbs'>Home / Companies</div><h1>Companies</h1><p>Employers represented in the current opportunity feed.</p><form class='searchbar' onsubmit='event.preventDefault();filterCards()'><input id='q' class='search' placeholder='Search companies' aria-label='Search companies'><button class='btn primary'>Search</button></form></div></section><div class='container content'><div class='company-grid' id='company-grid'>{company_cards or '<p class=mut>No company listings are available yet.</p>'}</div></div></main>"
    (docs / "companies.html").write_text(page(f"{BRAND} · Companies", companies_body, active="companies"), encoding="utf-8")

    resource_specs = {
        "career-tips": ("Career Tips", "Practical guidance for searching, evaluating and applying for opportunities.", [("Evaluate a job posting", "Check role requirements, location, eligibility, compensation and the employer's official application page."), ("Track applications", "Record the role, application date, source URL, next action and follow-up date."), ("Prepare before applying", "Match your relevant experience to the responsibilities and identify genuine skill gaps."), ("Avoid common job scams", "Be cautious of upfront payment requests and verify opportunities on official company domains.")]),
        "interview-prep": ("Interview Preparation", "Prepare with role-based practice questions. These examples are not represented as company-confirmed interview questions.", [("Role and experience", "Walk through a project relevant to the responsibilities. Explain your contribution, decisions and outcome."), ("Problem-solving", "Describe a difficult problem, the options you considered, and how you evaluated the result."), ("Collaboration", "Give an example of working across teams, handling feedback or resolving a disagreement."), ("Technical or functional skills", "Practice questions based on the specific skills and responsibilities listed in the job posting.")]),
        "resume-guide": ("Resume Guide", "Make your resume relevant to the job without claiming skills or experience you do not have.", [("Use relevant keywords", "Use important terms from the job requirements when they accurately describe your skills and experience."), ("Show evidence", "Connect each important skill to a project, task, responsibility or measurable result."), ("Write clear bullets", "Start with an action, explain the work, and include a result when you can substantiate it."), ("Check before sending", "Review dates, contact details, formatting, spelling and the job-specific version of your resume.")]),
        "free-courses": ("Free Courses", "Use these established learning platforms to find free learning material. Course availability and certificate costs can change.", [("freeCodeCamp", "Free programming and data learning curriculum.", "https://www.freecodecamp.org/learn/"), ("Khan Academy", "Free lessons across computing, math and related foundations.", "https://www.khanacademy.org/computing"), ("Microsoft Learn", "Free modules and learning paths for Microsoft technologies.", "https://learn.microsoft.com/training/"), ("HubSpot Academy", "Free marketing and business courses; check each course for certificate terms.", "https://academy.hubspot.com/")]),
    }
    for key, (title, desc, cards) in resource_specs.items():
        if key == "free-courses":
            cards_html = "".join(f"<article class='resource-card'><h3>{e(name)}</h3><p>{e(detail)}</p><a class='btn' href='{url}' target='_blank' rel='noopener'>Open learning platform ↗</a></article>" for name, detail, url in cards)
        else:
            cards_html = "".join(f"<article class='resource-card'><h3>{e(name)}</h3><p>{e(detail)}</p></article>" for name, detail in cards)
        body = f"<main><section class='page-head'><div class='container'><div class='breadcrumbs'>Home / {e(title)}</div><h1>{e(title)}</h1><p>{e(desc)}</p></div></section><div class='container content'><div class='resource-grid'>{cards_html}</div></div></main>"
        (docs / f"{key}.html").write_text(page(f"{BRAND} · {title}", body, active=key), encoding="utf-8")

    archive_items = ''.join(job_html(j, i, '../') for i, j in enumerate(ranked, 1))
    archive_days = "".join("<li><a href='" + d + ".html'>" + d + "</a></li>" for d in sorted((p.stem for p in (docs / "archive").glob("20*.html")), reverse=True))
    archive_body = f"<main class='detail'><div class='container'><div class='detail-card'><a class='back' href='../index.html'>← Home</a><h1>Opportunity archive</h1><p class='mut'>Daily feeds available in this site.</p><div class='archive-list'><ul>{archive_days}</ul></div></div></div></main>"
    (docs / "archive" / "index.html").write_text(page(f"{BRAND} · Archive", archive_body, "../"), encoding="utf-8")
    archive_day_body = f"<main class='detail'><div class='container'><div class='detail-card'><a class='back' href='../index.html'>← Home</a><h1>Opportunities for {e(date)}</h1><p class='mut'>{len(ranked)} qualifying postings.</p><div class='job-list'>{archive_items}</div></div></div></main>"
    (docs / "archive" / f"{date}.html").write_text(page(f"{BRAND} · {date}", archive_day_body, "../"), encoding="utf-8")

    job_script = f"""
<div class='detail'><div class='container'><div id='job-root' class='detail-card'><p class='mut'>Loading job details…</p></div></div></div>
<script>
const DATA_URL='data/{date}.json';
const sourceUrl=new URLSearchParams(location.search).get('url');
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const linkify=s=>esc(s).replace(/https?:\/\/[^\s<>"']+/g, raw=>{{
 const clean=raw.replace(/[.,;:!?)\\]]+$/,'');
 return `<a href="${{clean}}" target="_blank" rel="noopener noreferrer nofollow">${{clean}}</a>${{raw.slice(clean.length)}}`;
}});
const headingNames=new Set([
 'about us','about the role','your area of focus','your professional qualifications',
 '#li-ss1 #li-remote','about tebra','our values','perks & benefits',
 'compliance & privacy disclosures','what we offer','what you will do','what you’ll do',
 'what you will bring','what you’ll bring','what you’ll need','responsibilities','requirements',
 'qualifications','benefits','nice to have','preferred qualifications','additional qualifications',
 'education','experience','equal opportunity','job applicant privacy notice','how to apply',
 'who you are','about you','about us','about the company','the opportunity','the role','role overview',
 'your responsibilities','your area of focus','your professional qualifications','minimum qualifications','preferred skills','our mission',
 'things you’ll do','things you will do','bonus points','what you’ll get','what you will get','what you’ll bring','what you will bring',
 'our values','perks & benefits','compliance & privacy disclosures','#li-ss1 #li-remote',
 'why join us','compensation','application process','working at',
 'about seqûra','about sequra','what challenges you will be solving','which are the next steps',
 'what we offer','what you will need','what you will need','your first three months',
 'team focus areas','job summary','why work with us','about prove','about the role'
]);
const formatDescription=s=>{{
 if(!s) return '<p>The source did not provide a full description.</p>';
 const source=String(s).replace(/\\r\\n?/g,'\\n').replace(/\\\\n/g,'\\n').replace(/\\u00a0/g,' ');
 const lines=source.split('\\n');
 const out=[]; let paragraph=[]; let bullets=[];
 const flushParagraph=()=>{{if(paragraph.length){{out.push(`<p>${{linkify(paragraph.join(' ').trim())}}</p>`);paragraph=[];}}}};
 const flushBullets=()=>{{if(bullets.length){{out.push(`<ul>${{bullets.map(x=>`<li>${{linkify(x)}}</li>`).join('')}}</ul>`);bullets=[];}}}};
 const isHeading=line=>{{
   const t=line.trim().replace(/:$/,'');
   const clean=t.replace(/\s+/g,' ').trim();
   // Compare a plain-text label so emoji/symbol decorations don't prevent heading recognition.
   const normalized=clean.normalize('NFKC').replace(/[\p{{Extended_Pictographic}}\p{{Emoji_Presentation}}\uFE0F]/gu,'').replace(/[🤝🚀😎🙌🤓]/gu,'').replace(/\s+/g,' ').trim().toLowerCase();
   const titleCaseHeading=clean.length>=3 && clean.length<=85 && !/[.!?]$/.test(clean) && /^[A-Z0-9][A-Za-z0-9 &/(),+#'’—-]*$/.test(clean) && clean.split(/\s+/).length<=10 && clean.split(/\s+/).filter(w=>/^[A-Z0-9]/.test(w)).length>=2;
   const shortLabel=clean.length>=3 && clean.length<=70 && clean.split(/\s+/).length<=8 && !/[.!?]$/.test(clean) && !/^https?:/i.test(clean);
   return headingNames.has(normalized) || /^[A-Z][A-Za-z0-9 &/(),+#'’—-]{{2,65}}:$/.test(line.trim()) || titleCaseHeading || (shortLabel && /^(about\b|what\b|which\b|your\b|our\b|who\b|how\b|why\b|the role\b|responsibilities\b|qualifications\b)/i.test(normalized));
 }};
 for(const rawLine of lines){{
   const line=rawLine.trim().replace(/\\\\$/,'').trim();
   if(!line){{flushParagraph();flushBullets();continue;}}
   if(isHeading(line)){{flushParagraph();flushBullets();out.push(`<h3>${{esc(line.replace(/:$/,''))}}</h3>`);continue;}}
   if(/^([•●▪◦*-]|\\d+[.)])\\s+/.test(line)){{
     flushParagraph();bullets.push(line.replace(/^([•●▪◦*-]|\\d+[.)])\\s+/,'').trim());continue;
   }}
   flushBullets();paragraph.push(line);
 }}
 flushParagraph();flushBullets();
 return out.join('\\n') || `<p>${{linkify(source)}}</p>`;
}};
const textBlock=s=>`<div class="source-description">${{formatDescription(s)}}</div>`;
const listBlock=items=>`<ul class="detail-list">${{items.map(x=>`<li>${{esc(x)}}</li>`).join('')}}</ul>`;
const section=(heading,items,id='')=>`<section class="detail-section" id="${{id}}"><h2>${{esc(heading)}}</h2>${{items.length>1?listBlock(items):textBlock(items[0]||'Not provided in the source posting.')}}</section>`;
fetch(DATA_URL).then(r=>{{if(!r.ok)throw new Error('data');return r.json()}}).then(jobs=>{{
 const j=jobs.find(x=>[x.url,x.original_url,x.source_url,x.application_url,x.apply_url].some(value=>String(value||'').trim()===sourceUrl));const root=document.getElementById('job-root');
 if(!j){{root.innerHTML='<a class="back" href="index.html">← Home</a><section class="detail-section"><h2>Job not found</h2><p class="detail-copy">This listing may no longer be in the current feed. Return to the job list to browse available opportunities.</p><a class="btn primary" href="jobs.html">Browse jobs</a></section>';return;}}
 document.title=`${{j.title}} at ${{j.company}} · Road Beyond Roles`;
 const keywords=[...(j.must||[]),...(j.nice||[])].filter(Boolean);
 const unique=[...new Set(keywords.map(x=>String(x).trim()).filter(Boolean))];
 const stored=(j.description_sections||[]);
 const description=section('Original job description',[j.description||'The source did not provide a full description.']);
 const responsibilities=stored.filter(x=>/responsib|specifics of the role|key responsibilities/i.test(x.heading)).flatMap(x=>x.items||[]);
 const requirements=stored.filter(x=>/requirement|qualification|education|competenc/i.test(x.heading)).flatMap(x=>x.items||[]);
 const must=(j.must||[]).map(x=>`<span class="chip m">${{esc(x)}}</span>`).join('');
 const nice=(j.nice||[]).map(x=>`<span class="chip">${{esc(x)}}</span>`).join('');
 const q1=`Which experience or project best demonstrates your ability to do the work described for ${{j.title}}?`;
 const q2=`Choose one listed requirement and explain how you have used it in practice.`;
 const q3=`Describe a work problem relevant to this role, your approach, and the result.`;
 const courseLinks=[
  ['freeCodeCamp','Free programming and data learning','https://www.freecodecamp.org/learn/'],
  ['Microsoft Learn','Free Microsoft technology learning paths','https://learn.microsoft.com/training/'],
  ['Khan Academy','Free computing and foundational lessons','https://www.khanacademy.org/computing'],
  ['HubSpot Academy','Free marketing and business courses','https://academy.hubspot.com/']
 ];
 const roleText=`${{j.title||''}} ${{j.description||''}} ${{unique.join(' ')}}`.toLowerCase();
 const courseSet= /marketing|content|seo|social|email/.test(roleText)?[courseLinks[3],courseLinks[0]]:/data|python|sql|analyst|machine learning/.test(roleText)?[courseLinks[0],courseLinks[1],courseLinks[2]]:/microsoft|azure|office|power bi/.test(roleText)?[courseLinks[1],courseLinks[2]]:[courseLinks[0],courseLinks[1],courseLinks[2]];
 const courseHtml=courseSet.map(c=>`<li><a href="${{c[2]}}" target="_blank" rel="noopener">${{esc(c[0])}} ↗</a><small>${{esc(c[1])}}. Check the platform for relevant modules and current access terms.</small></li>`).join('');
 const companyMark=esc(String(j.company||'C').trim().split(' ').filter(Boolean).map(x=>x[0]).join('').slice(0,2).toUpperCase());
 const detailRows=[['Company',j.company],['Location',j.location],['Work mode',j.work_mode||j.workplace_type],['Employment type',j.employment_type||j.job_type],['Experience',j.experience],['Salary',j.salary?String(j.salary)+(j.salary_type?' ('+j.salary_type+')':''):((j.salary_research||{{}}).range?String(j.salary_research.range)+' ('+((j.salary_research||{{}}).kind==='employer_posted'?'employer-posted compensation':(j.salary_research||{{}}).kind==='market_estimate'?'role-matched market estimate':'source evidence')+')':'')],['Application deadline',j.application_deadline]].filter(([,v])=>v);
 const jobDetailRows=detailRows.map(([k,v])=>`<b>${{esc(k)}}:</b> ${{esc(v)}}`).join('<br>');
 root.innerHTML=`<a class="back" href="index.html">← Back to opportunities</a>
 <header class="detail-head"><div class="detail-title-row"><div class="company-mark">${{companyMark}}</div><div><h1>${{esc(j.title)}}</h1><div class="detail-company">${{[j.company,j.location].filter(Boolean).map(esc).join(' · ')}}</div></div><div class="detail-actions"><a class="btn primary" href="${{esc(j.url||'#')}}" target="_blank" rel="noopener nofollow">Apply on company site ↗</a></div></div>
 <div class="detail-meta">${{[j.work_mode||j.workplace_type,j.employment_type||j.job_type,j.experience,(j.posted?`Posted ${{j.posted}}`:''),j.source].filter(Boolean).map(v=>`<span>${{esc(v)}}</span>`).join('')}}</div></header>
 <nav class="detail-tabs"><a href="#overview">Overview</a><a href="#keywords">Skills & Keywords</a><a href="#interview">Interview Prep</a><a href="#resume">Resume Tips</a><a href="#courses">Free Courses</a></nav>
 <div class="detail-columns"><div><section class="detail-section" id="overview"><h2>Job description</h2>${{textBlock(j.description||'The source did not provide a full job description.')}}<p class="mut">Use the official employer page as the final source of truth. Preparation suggestions below are general role-based guidance unless explicitly identified as source-confirmed.</p></section>
 <section class="detail-section" id="keywords"><h2>Skills and resume keywords</h2><p class="detail-copy">Use these terms only where they accurately match your skills, experience or projects.</p><div class="tag-row">${{must||'<span class="mut">No core keywords were extracted from this listing.</span>'}} ${{nice}}</div></section>
 <section class="detail-section" id="interview"><h2>Interview tips and practice questions</h2><p class="mut">Role-based practice questions — not verified company interview questions.</p><ul class="question-list"><li><b>Experience:</b> ${{esc(q1)}}</li><li><b>Skills:</b> ${{esc(q2)}}</li><li><b>Problem-solving:</b> ${{esc(q3)}}</li></ul><p class="detail-copy" style="margin-top:10px">Prepare concise examples using the situation, task, action and result structure. Tie each answer to a requirement in the original posting.</p></section>
 <section class="detail-section" id="resume"><h2>Resume writing tips</h2><ul class="detail-list"><li>Reflect relevant terms from the requirements where they truthfully describe your experience.</li><li>Use project or work examples to demonstrate each important skill.</li><li>Start bullets with clear action verbs and include measurable outcomes only when you can substantiate them.</li><li>Prioritize the most relevant experience near the top; do not add unsupported skills.</li></ul></section>
 <section class="detail-section" id="courses"><h2>Free courses and learning resources</h2><p class="mut">These are free learning platforms with role-relevant starting points, not a guarantee that every course is free or that a certificate has no cost.</p><ul class="course-list">${{courseHtml}}</ul></section></div>
 <aside><section class="detail-section"><h2>Job details</h2><p class="detail-copy">${{jobDetailRows}}</p><a class="btn primary" style="width:100%;margin-top:12px" href="${{esc(j.url||'#')}}" target="_blank" rel="noopener nofollow">Open original posting ↗</a></section></aside></div>`;
}}).catch(()=>document.getElementById('job-root').innerHTML='<section class="detail-section"><h2>Unable to load job details</h2><p class="detail-copy">The job data could not be loaded. Return to the homepage and try again.</p><a class="btn primary" href="index.html">Home</a></section>');
</script>"""
    (docs / "job.html").write_text(page(f"{BRAND} · Job details", job_script), encoding="utf-8")
