"""Rank jobs and extract resume keywords (no paid APIs, fully deterministic)."""
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# canonical :: regex alternatives :: category   ("soft" is shown but not ranked)
_DEFS = r"""
Python :: Python :: lang
Java :: Java :: lang
JavaScript :: JavaScript|ECMAScript :: lang
TypeScript :: TypeScript :: lang
Go :: Golang|Go (?:programming|language|developer|engineer) :: lang
Rust :: Rust :: lang
C++ :: C\+\+ :: lang
C# :: C# :: lang
Kotlin :: Kotlin :: lang
Swift :: (?-i:Swift) :: lang
Scala :: Scala :: lang
PHP :: PHP :: lang
Ruby :: Ruby|Rails :: lang
Bash :: Bash|Shell scripting :: lang
SQL :: SQL|T-SQL|PL/SQL :: data
NoSQL :: NoSQL :: data
PostgreSQL :: PostgreSQL|Postgres :: data
MySQL :: MySQL :: data
MongoDB :: MongoDB|Mongo :: data
Redis :: Redis :: data
Elasticsearch :: Elasticsearch|OpenSearch :: data
Kafka :: Kafka :: data
RabbitMQ :: RabbitMQ :: data
Spark :: (?:Apache |Py)?Spark :: data
Airflow :: Airflow :: data
dbt :: (?-i:dbt) :: data
Snowflake :: Snowflake :: data
BigQuery :: BigQuery :: data
Databricks :: Databricks :: data
Hadoop :: Hadoop :: data
ETL :: ETL|ELT :: data
Data Modeling :: data model(?:l)?ing :: data
Data Warehousing :: data warehous(?:e|ing) :: data
Power BI :: Power ?BI :: data
Tableau :: Tableau :: data
Looker :: Looker :: data
Excel :: (?-i:Excel)|Microsoft Excel :: data
Pandas :: (?-i:Pandas) :: data
NumPy :: NumPy :: data
Statistics :: statistics|statistical :: data
A/B Testing :: A/B test(?:ing|s)? :: data
React :: (?-i:React)(?:\.js|JS|js)? :: web
Angular :: (?-i:Angular)(?:JS)? :: web
Vue :: Vue(?:\.js|JS)? :: web
Next.js :: Next\.?js :: web
Node.js :: Node(?:\.js|JS|js) :: web
Django :: Django :: web
Flask :: (?-i:Flask) :: web
FastAPI :: FastAPI :: web
Spring Boot :: Spring Boot|Spring Framework|Spring MVC|Spring Cloud :: web
.NET :: \.NET|dotnet :: web
GraphQL :: GraphQL :: web
REST APIs :: (?-i:REST)(?:ful)?(?: APIs?)?|RESTful APIs? :: web
Microservices :: microservices? :: web
HTML/CSS :: HTML5?|CSS3? :: web
Android :: Android :: mobile
iOS :: (?-i:iOS) :: mobile
Flutter :: Flutter :: mobile
React Native :: React Native :: mobile
AWS :: AWS|Amazon Web Services :: cloud
Azure :: Azure :: cloud
GCP :: GCP|Google Cloud :: cloud
Docker :: Docker :: devops
Kubernetes :: Kubernetes|(?-i:K8s)|k8s :: devops
Terraform :: Terraform :: devops
Ansible :: Ansible :: devops
Jenkins :: Jenkins :: devops
GitHub Actions :: GitHub Actions :: devops
CI/CD :: CI/CD|CI-CD|continuous integration :: devops
Linux :: Linux|Unix :: devops
Git :: (?-i:Git)(?:Hub|Lab)? :: devops
Prometheus :: Prometheus :: devops
Grafana :: Grafana :: devops
Observability :: observability|monitoring :: devops
Machine Learning :: machine learning|(?-i:ML) :: ai
Deep Learning :: deep learning :: ai
NLP :: NLP|natural language processing :: ai
LLMs :: LLMs?|large language models? :: ai
Generative AI :: generative AI|GenAI|gen AI :: ai
RAG :: (?-i:RAG)|retrieval[- ]augmented :: ai
Computer Vision :: computer vision :: ai
PyTorch :: PyTorch :: ai
TensorFlow :: TensorFlow :: ai
scikit-learn :: scikit-learn|sklearn :: ai
Selenium :: Selenium :: qa
Cypress :: Cypress :: qa
Playwright :: Playwright :: qa
Appium :: Appium :: qa
Test Automation :: test automation|automation testing :: qa
Manual Testing :: manual testing :: qa
API Testing :: API testing|Postman :: qa
pytest/JUnit :: pytest|JUnit|TestNG :: qa
QA :: (?-i:QA)|quality assurance :: qa
Figma :: Figma :: design
UI/UX :: UI/UX|UX design|user experience :: design
Product Management :: product management :: biz
Agile :: Agile :: biz
Scrum :: Scrum :: biz
Jira :: Jira :: biz
Salesforce :: Salesforce :: biz
SAP :: (?-i:SAP) :: biz
HubSpot :: HubSpot :: biz
SEO :: (?-i:SEO) :: biz
Content Writing :: content writ(?:ing|er) :: biz
Customer Support :: customer support|customer success :: biz
Cybersecurity :: cyber ?security|information security|InfoSec :: security
SIEM :: SIEM :: security
Penetration Testing :: penetration testing|pentest :: security
System Design :: system design :: soft
Data Structures & Algorithms :: data structures|algorithms :: soft
OOP :: object[- ]oriented|OOPs? :: soft
Distributed Systems :: distributed systems :: soft
Scalability :: scalab(?:le|ility) :: soft
Stakeholder Management :: stakeholder (?:management|engagement|communication)s? :: soft
Cross-functional Collaboration :: cross[- ]functional :: soft
Communication Skills :: communication skills|written and verbal :: soft
Problem Solving :: problem[- ]solving :: soft
Mentoring :: mentor(?:ing|ship)? :: soft
End-to-End Ownership :: end[- ]to[- ]end|ownership :: soft
Debugging :: debugging|troubleshooting :: soft
"""

SKILLS = []
for line in _DEFS.strip().splitlines():
    canon, pat, cat = [p.strip() for p in line.split(" :: ")]
    rx = re.compile(rf"(?<![A-Za-z0-9])(?:{pat})(?![A-Za-z0-9])", re.I)
    SKILLS.append((canon, rx, cat))

NICE_RE = re.compile(r"nice[- ]to[- ]have|good[- ]to[- ]have|preferred qualif|bonus|a plus|"
                     r"would be a plus|desirable|optional", re.I)
EXP_RE = re.compile(r"(\d{1,2})\s*(\+|-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs)", re.I)
CUR_RE = re.compile(r"(?:₹|INR|Rs\.?|\$|USD|€|EUR)\s?\d[\d,.]*\s?(?:k|K|LPA|lakhs?|cr)?"
                    r"(?:\s?(?:-|–|to)\s?(?:₹|INR|Rs\.?|\$|USD|€|EUR)?\s?\d[\d,.]*\s?(?:k|K|LPA|lakhs?|cr)?)?")
LPA_RE = re.compile(r"\d[\d.]*\s?(?:-|–|to)?\s?\d*[\d.]*\s?LPA", re.I)

# Deterministic section extraction used by the content-analysis layer.
_SECTION_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?"
    r"(responsibilities|what you(?:'|’)ll do|what you will do|"
    r"key responsibilities|duties|requirements|required qualifications|basic qualifications|"
    r"must have|what we(?:'|’)re looking for|qualifications|"
    r"preferred qualifications|nice to have|preferred skills|education|"
    r"educational qualifications|experience|assessment|interview process|hiring process)"
    r"[ \t]*:?[ \t]*$"
)
_BULLET_RE = re.compile(r"(?m)^[ \t]*(?:[-*•▪◦‣]|\d+[.)])[ \t]+(.+?)\s*$")
_EDUCATION_RE = re.compile(
    r"(?i)\b(?:bachelor(?:'s)?|master(?:'s)?|phd|doctorate|b\.?e\.?|b\.?tech\.?|"
    r"m\.?e\.?|m\.?tech\.?|b\.?sc\.?|m\.?sc\.?|bca|mca|mba|degree|diploma|"
    r"graduate|postgraduate)\b[^.\n]{0,180}"
)
_ASSESSMENT_RE = re.compile(
    r"(?is)\b(?:assessment|test|coding test|technical test|take[- ]home|assignment|"
    r"case study|online test|hackerrank|codility|screening exercise|work sample)\b.{0,500}"
)
_INTERVIEW_RE = re.compile(
    r"(?is)\b(?:interview|interviews|hiring process|interview process|recruitment process|"
    r"selection process|phone screen|technical screen|screening call|onsite|panel interview|"
    r"behavioral interview)\b.{0,700}"
)
_ROLE_LEVEL_RE = re.compile(
    r"(?i)\b(?:intern|internship|trainee|fresher|entry[- ]level|junior|associate|mid[- ]level|"
    r"senior|lead|principal|staff|manager|director|head|vp|vice president)\b"
)


def _clean_line(value: str) -> str:
    return re.sub(r"\\s+", " ", value).strip(" -–—•*\\t")


def _unique(items: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        item = _clean_line(item)
        if not item:
            continue
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
            if limit and len(out) >= limit:
                break
    return out


def _section_blocks(description: str) -> dict[str, str]:
    """Extract simple heading-delimited sections without an LLM."""
    matches = list(_SECTION_RE.finditer(description))
    blocks: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = re.sub(r"[^a-z0-9]+", "_", match.group(1).lower()).strip("_")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(description)
        body = description[start:end].strip()
        if body:
            blocks[name] = f"{blocks.get(name, '')}\n{body}".strip()
    return blocks


def _bullet_items(text: str, limit: int = 12) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^[ \t]*(?:[-*•▪◦‣]|\d+[.)])[ \t]+(.+?)\s*$", line)
        if match:
            items.append(match.group(1))
    return _unique(items, limit)


def _first_sentences(text: str, limit: int = 5) -> list[str]:
    return _unique(re.split(r"(?<=[.!?])\\s+|\\n+", text), limit)


def _find_section(blocks: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in blocks:
            return blocks[name]
    return ""


def _detect_role_level(title: str, description: str, experience: str) -> str:
    title_matches = list(_ROLE_LEVEL_RE.finditer(title))
    if title_matches:
        return title_matches[0].group(0).lower()
    matches = list(_ROLE_LEVEL_RE.finditer(f"{title} {description[:1800]}"))
    if matches:
        return matches[0].group(0).lower()
    return "entry level" if "entry" in experience.lower() else experience


def _extract_education(description: str, blocks: dict[str, str]) -> list[str]:
    edu_text = _find_section(blocks, ("education", "educational_qualifications"))
    source = edu_text or description
    return _unique([m.group(0) for m in _EDUCATION_RE.finditer(source)], 5)


def _extract_assessment(description: str) -> dict:
    match = _ASSESSMENT_RE.search(description)
    if not match:
        return {"found": False, "details": [], "source": "not_found_in_job_posting", "confidence": "none"}
    return {"found": True, "details": [_clean_line(match.group(0))], "source": "job_posting", "confidence": "high"}


def _extract_interview(description: str) -> dict:
    match = _INTERVIEW_RE.search(description)
    if not match:
        return {"process": [], "questions": [], "source": "not_found_in_job_posting", "confidence": "none"}
    return {"process": [_clean_line(match.group(0))], "questions": [], "source": "job_posting", "confidence": "high"}


def _inferred_questions(title: str, responsibilities: list[str], skills: list[str]) -> list[str]:
    questions: list[str] = []
    if responsibilities:
        questions.append(f"How would you approach the most important responsibilities of a {title}?")
    for skill in skills[:4]:
        questions.append(f"How have you used {skill} in a real project or work situation?")
    if not questions:
        questions.append(f"What would you prioritize in your first 30 days as a {title}?")
    return _unique(questions, 6)


def _indian_candidate_prep(title: str, experience: str, required_skills: list[str], education: list[str]) -> list[str]:
    prep = [
        "Verify that the posting explicitly accepts applicants from India before applying.",
        "Tailor the resume to the role using the exact relevant ATS keywords from the posting.",
    ]
    if required_skills:
        prep.append("Prepare concrete project/work examples demonstrating: " + ", ".join(required_skills[:5]) + ".")
    if education:
        prep.append("Check that your education matches the stated qualification requirements.")
    if experience:
        prep.append(f"Prepare examples that demonstrate the stated experience level: {experience}.")
    prep.append("Prepare concise STAR-format examples for ownership, problem-solving, and collaboration.")
    return prep


def analyze_job(job: dict) -> dict:
    """Build the structured deterministic content-analysis record for one job."""
    title = job.get("title", "")
    description = job.get("description", "") or ""
    blocks = _section_blocks(description)
    responsibilities_text = _find_section(blocks, ("responsibilities", "what_you_ll_do", "what_you_will_do", "key_responsibilities", "duties"))
    responsibilities = _bullet_items(responsibilities_text) or _first_sentences(responsibilities_text, 8)
    education = _extract_education(description, blocks)

    extract(job)
    required_skills = list(job.get("must", []))
    preferred_skills = list(job.get("nice", []))
    role_level = _detect_role_level(title, description, job.get("experience", ""))
    assessment = _extract_assessment(description)
    interview = _extract_interview(description)
    if not interview["questions"]:
        interview["questions"] = _inferred_questions(title, responsibilities, required_skills)
        if interview["source"] == "not_found_in_job_posting":
            interview["source"] = "role_based_inference"
            interview["confidence"] = "inferred"

    ats_keywords = _unique(required_skills + preferred_skills + job.get("soft", []) + [title, job.get("company", "")], 30)
    candidate_summary = responsibilities[:3] or _first_sentences(description, 3)

    job["analysis"] = {
        "role": title,
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "posted_at": job.get("posted", ""),
        "eligibility": job.get("tier", ""),
        "experience": job.get("experience", ""),
        "experience_level": role_level,
        "education": education,
        "responsibilities": responsibilities,
        "ideal_candidate": {
            "summary": candidate_summary,
            "required_skills": required_skills,
            "preferred_skills": preferred_skills,
        },
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "ats_keywords": ats_keywords,
        "tools_and_technologies": _unique(required_skills + preferred_skills, 30),
        "salary": job.get("salary", ""),
        "assessment": assessment,
        "interview": interview,
        "indian_candidate_prep": _indian_candidate_prep(title, job.get("experience", ""), required_skills, education),
        "content_angles": _unique([
            f"What this {title} role actually requires",
            "Resume keywords an applicant should use",
            "What to prepare before applying",
            "Assessment and interview preparation",
        ], 6),
        "evidence": {
            "job_posting": "primary source",
            "assessment": assessment["source"],
            "interview": interview["source"],
        },
    }
    return job


def analyze_jobs(jobs: list[dict]) -> list[dict]:
    """Analyze all jobs and return them in the original order."""
    return [analyze_job(job) for job in jobs]


def extract(job: dict) -> dict:
    """Return must-have / nice-to-have / soft keywords, experience, salary for one job."""
    title, desc = job.get("title", ""), job.get("description", "")
    m = NICE_RE.search(desc)
    cut = m.start() if m else len(desc)
    must, nice, soft = Counter(), Counter(), Counter()
    for canon, rx, cat in SKILLS:
        a = len(list(rx.finditer(desc[:cut]))) + (3 if rx.search(title) else 0)
        b = len(list(rx.finditer(desc[cut:])))
        if cat == "soft":
            if a + b:
                soft[canon] = a + b
        elif a:
            must[canon] = a
        elif b:
            nice[canon] = b
    order = {c: i for i, (c, _, _) in enumerate(SKILLS)}
    key = lambda kv: (-kv[1], order[kv[0]])
    job["must"] = [k for k, _ in sorted(must.items(), key=key)]
    job["nice"] = [k for k, _ in sorted(nice.items(), key=key)]
    job["soft"] = [k for k, _ in sorted(soft.items(), key=key)][:4]

    exp = ""
    mm = EXP_RE.search(desc)
    if mm and int(mm.group(1)) <= 20:
        lo, sep, hi = mm.group(1), mm.group(2), mm.group(3)
        exp = f"{lo}-{hi} years" if hi else (f"{lo}+ years" if sep == "+" else f"{lo} years")
    elif re.search(r"\b(fresher|entry[- ]level|graduate|junior)\b", title + desc[:600], re.I):
        exp = "entry level"
    job["experience"] = exp

    sal = CUR_RE.search(desc) or LPA_RE.search(desc)
    job["salary"] = sal.group(0).strip()[:32] if sal else ""
    return job


def hours_old(job: dict) -> float:
    if not job.get("posted"):
        return 99.0
    d = datetime.fromisoformat(job["posted"])
    return max(0.0, (datetime.now(timezone.utc) - d).total_seconds() / 3600)


def rank(jobs: list[dict], profile: dict) -> list[dict]:
    tgt = {k.lower(): w for k, w in profile.get("target_keywords", {}).items()}
    boost_t = [w.lower() for w in profile.get("boost_title_words", [])]
    avoid_t = [w.lower() for w in profile.get("avoid_title_words", [])]
    boost_c = [c.lower() for c in profile.get("boost_companies", [])]
    for j in jobs:
        analyze_job(j)
        h = hours_old(j)
        j["hours_old"] = h
        s = {"A": 40, "B": 28, "C": 10}.get(j["tier"], 0)
        s += max(0.0, 15 - h * 0.6)
        s += min(20, sum(tgt.get(k.lower(), 0) for k in j["must"]))
        t = j["title"].lower()
        s += min(8, 4 * sum(w in t for w in boost_t))
        s -= 30 * any(w in t for w in avoid_t)
        s += 6 if j["salary"] else 0
        s += 10 if j["company"].lower() in boost_c else 0
        s += 3 if len(j.get("description", "")) > 600 else -5
        s += min(5, len(j["must"]))          # well-specified roles are better content
        j["score"] = round(s, 1)
    jobs.sort(key=lambda j: -j["score"])
    return jobs


def pick(ranked: list[dict], n_video: int, n_list: int, per_company: int = 2):
    """Top n_video for the video (company-diverse) + next n_list for the quick list."""
    per, chosen, rest = Counter(), [], []
    for j in ranked:
        if len(chosen) < n_video and per[j["company"]] < per_company:
            chosen.append(j)
            per[j["company"]] += 1
        else:
            rest.append(j)
    return chosen, rest[:n_list]


def aggregate_keywords(jobs: list[dict], top: int = 10):
    """[(keyword, n_jobs, pct)] - how many of today's jobs ask for each hard skill."""
    c = Counter(k for j in jobs for k in set(j["must"] + j["nice"]))
    n = max(1, len(jobs))
    return [(k, v, round(100 * v / n)) for k, v in c.most_common(top)]


def load_profile(path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
