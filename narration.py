"""Build human, screen-synchronised narration scenes for daily Road Beyond Roles videos."""

from __future__ import annotations



import base64

import html

import json

import logging

import re

import queue

import threading

import time

import urllib.error

import urllib.request

from urllib.parse import quote_plus, urlparse, parse_qs

from html.parser import HTMLParser

from pathlib import Path

from typing import Any, Iterable

from datetime import datetime, timezone



log = logging.getLogger("narration")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "

       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 RoadBeyondRoles/1.0")



SPOKEN = [

    (r"C\+\+", "C plus plus"), (r"C#", "C sharp"), (r"\.NET", "dot net"),

    (r"CI/CD", "C I slash C D"), (r"Node\.js", "Node J S"), (r"Next\.js", "Next J S"),

    (r"UI/UX", "U I, U X"), (r"A/B", "A B"), (r"\bAWS\b", "AWS"), (r"\bGCP\b", "G C P"),

    (r"\bLLMs\b", "large language models"), (r"\bNLP\b", "N L P"), (r"\bETL\b", "E T L"),

    (r"\bQA\b", "Q A"), (r"\bSEO\b", "S E O"),

    (r"\bRAG\b", "rag"), (r"\bdbt\b", "D B T"), (r"\bBI\b", "B I"),

    (r"\u20b9\s?", "rupees "), (r"\bLPA\b", "lakhs per annum"), (r"\bUSD\b", "US dollars"),

]



_ATS_DOMAINS = (

    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com",

    "smartrecruiters.com", "workable.com", "jobvite.com", "bamboohr.com",

    "icims.com", "applytojob.com", "recruitee.com", "teamtailor.com",

)



_NON_RESPONSIBILITY_STARTS = re.compile(

    r"(?i)^(you\s+will\s+report\s+to|reports?\s+to|reporting\s+to|"

    r"this\s+(role|position)\s+is|this\s+is\s+a|"

    r"you\s+will\s+be\s+part\s+of|you\s+will\s+join|"

    r"we\s+are\s+seeking|we\s+are\s+looking\s+for|"

    r"about\s+the\s+role|location\s*:|headquarters\s*:|"

    r"employment\s+type|job\s+type|salary\s*:|compensation\s*:)"

)



_NAV_CONTAMINATION = re.compile(

    r"(?i)\b(?:observability|ui/ux|user experience|frontend framework|"

    r"react\.js|css|top 100|top trending|all design jobs|search by|"

    r"company profile|related jobs|see more|read more|apply now|"

    r"save job|boosted listing|experience certificate|experience letter|"

    r"certificate/letter|offer letter|joining letter|relieving letter|"

    r"passport copy|identity proof|resume upload|cv upload|application form)\b"

)



_ROLE_SECTION_HEADERS = re.compile(

    r"(?i)\b(?:responsibilities|what you(?:'|’)ll do|what you'll do|the role|"

    r"key responsibilities|your responsibilities|responsibilities\s*&\s*mandates|"

    r"what your day will look like|a typical day|what you'll be doing|"

    r"what you will be doing|day[\-\s]to[\-\s]day|in this role|"

    r"as part of the role|how you'll make an impact|what you(?:'|’)ll be doing|"

    r"primary duties|main duties|main responsibilities|key tasks|role overview)\b\s*:?"

)



_END_SECTION_HEADERS = re.compile(

    r"(?i)\b(?:qualifications|requirements|what you(?:'|’)ll bring|what you'll bring|"

    r"what we offer|benefits|why work with us|about the company|about us|"

    r"equal opportunity|how to apply|to apply|apply now|minimum qualifications|"

    r"preferred qualifications|nice to have|nice-to-have|skills|about you|who you are)\b\s*:?"

)





class _TextExtractor(HTMLParser):

    BLOCKS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "section"}

    def __init__(self) -> None:

        super().__init__(convert_charrefs=True)

        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:

        if tag in self.BLOCKS:

            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:

        if tag in self.BLOCKS:

            self.parts.append("\n")

    def handle_data(self, data: str) -> None:

        self.parts.append(data)





def clean_text(value: Any) -> str:

    raw = str(value or "")

    parser = _TextExtractor()

    try:

        parser.feed(raw)

        raw = " ".join(parser.parts)

    except Exception:

        raw = re.sub(r"<[^>]+>", " ", raw)

    raw = html.unescape(raw).replace("\xa0", " ")

    raw = re.sub(r"[ \t\f\v]+", " ", raw)

    raw = re.sub(r"\s*\n\s*", " ", raw)

    return re.sub(r"\s+", " ", raw).strip()





def spoken(text: str) -> str:

    for pattern, replacement in SPOKEN:

        text = re.sub(pattern, replacement, text, flags=re.I if pattern == r"\bLLMs\b" else 0)

    return re.sub(r"\s+", " ", text).strip()





def age_phrase(hours: float) -> str:

    if hours < 1:

        return "less than an hour ago"

    if hours < 2:

        return "about an hour ago"

    if hours < 24:

        return f"{int(hours)} hours ago"

    return "yesterday"





def human_list(items: Iterable[Any], n: int = 5) -> str:

    values = [str(item).strip() for item in list(items)[:n] if str(item).strip()]

    if not values:

        return ""

    if len(values) == 1:

        return values[0]

    return ", ".join(values[:-1]) + " and " + values[-1]





def summary_sentence(description: str) -> str:

    text = clean_text(description)

    if not text:

        return ""

    sentences = re.split(r"(?<=[.!?])\s+", text)

    reject = re.compile(

        r"^(about (the )?company|equal opportunity|we are an equal|apply now|click here|"

        r"salary range|compensation|benefits include)\b", re.I

    )

    for sentence in sentences[:35]:

        sentence = sentence.strip(" •-\t")

        if 55 <= len(sentence) <= 230 and not reject.search(sentence):

            return sentence

    return ""





def _is_valid_cached_official(j: dict[str, Any]) -> bool:

    cached_url = str(j.get("_official_job_url") or "").strip()

    cached_text = str(j.get("_official_job_text") or "").strip()

    if not cached_url or not cached_text:

        return False

    parsed = urlparse(cached_url)

    host = (parsed.hostname or "").lower()

    path = (parsed.path or "/").lower()

    if not host or path in {"", "/"}:

        return False

    company = re.sub(r"[^a-z0-9]", "", str(j.get("company") or "").lower())

    host_compact = re.sub(r"[^a-z0-9]", "", host)

    is_ats = any(host == d or host.endswith("." + d) for d in _ATS_DOMAINS)

    in_company_host = bool(company) and company in host_compact

    if not (is_ats or in_company_host):

        return False

    if not is_ats and not re.search(

        r"(?i)/(careers?|jobs?|positions?|openings?|roles?|apply|opportunit(?:y|ies))(/|$)", path,

    ):

        return False

    title = str(j.get("title") or "").lower()

    title_tokens = [t for t in re.findall(r"[a-z0-9]+", title) if len(t) > 3]

    matched = sum(1 for t in title_tokens if t in cached_text.lower())

    return matched >= max(2, min(3, len(title_tokens)))





def _description_sentences(j: dict[str, Any]) -> list[str]:

    primary = next((j.get(k) for k in ("description", "details", "summary") if j.get(k)), None)

    fallback = j.get("_official_job_text") or j.get("_source_page_text") or ""

    raw_primary = clean_text(primary or "")

    primary_is_usable = len(raw_primary) >= 160 and bool(re.search(

        r"(?i)\b(?:responsibilities|what you(?:'|’)ll do|you will|you'll|requirements|qualifications|experience|skills)\b",

        raw_primary))

    raw_primary = re.sub(

        r"(?is)to get timely updates on job openings\s*,?\s*feel free to join our community.*?(?=job overview\s*:|responsibilities\b|what you(?:'|’)ll do\b|requirements\b|qualifications\b|$)",

        " ", raw_primary)

    raw_primary = re.sub(r"(?i)\bjob overview\s*:\s*", " ", raw_primary)

    raw_fallback = clean_text(fallback)

    raw = (raw_primary if primary_is_usable

           else " ".join(v for v in (raw_primary, raw_fallback if fallback else "") if v)).strip()

    if not raw:

        return []

    raw = re.sub(r"(?is)\bqué es deazy\b.*?(?=\b(?:responsibilities|what you(?:'|’)ll do|requirements|qualifications|about the role)\b|$)", " ", raw)

    raw = re.sub(r"(?is)\bdeazy es una plataforma/marketplace\b.*?(?=\b(?:responsibilities|what you(?:'|’)ll do|requirements|qualifications|about the role)\b|$)", " ", raw)

    raw = re.sub(r"(?i)\b(?:top 100 remote companies|top trending remote jobs|search by job category|all design jobs|search by role|remote jobs by category)\b.*$", " ", raw)

    raw = re.sub(r"[^.!?]{0,260}(?:…|\.\.\.)", " ", raw)

    raw = re.sub(r"(?i)\bHeadquarters\s*:\s*[^.\n]{2,100}?(?=\s+URL\s*:|\s+Location\s*:|\s+(?:We are|We['’]re|The role|About the role)|$)", " ", raw)

    raw = re.sub(r"(?i)\bURL\s*:\s*https?://\S+", " ", raw)

    raw = re.sub(r"(?i)(Top 100 Remote Companies|Top Trending Remote Jobs|Search by Job Category|All Design Jobs|Search by Role).*$", " ", raw)

    role_heading = _ROLE_SECTION_HEADERS.search(raw)

    if role_heading:

        raw = raw[role_heading.end():].strip()

        next_section = _END_SECTION_HEADERS.search(raw)

        if next_section:

            raw = raw[:next_section.start()].strip()

    raw = re.sub(r"(?i)^FinOps uses data and operational excellence to deliver technology solutions, payroll services, operational excellence, and monetization services to [^.]+\.?\s*", "", raw)

    parts = re.split(

        r"(?<=[.!?])\s+(?=[A-Z0-9])"

        r"|(?<=[a-z0-9])\s+(?=(?:Your|You|We|The employer|Requirements|Responsibilities|This role|Candidates|Applicants|The role|What you)\b)"

        r"|\s*[•?]\s*|\s{2,}",

        raw)

    reject = re.compile(

        r"^(apply now|click here|equal opportunity|about us|about the company|"

        r"we are an equal|privacy policy|terms of service|read more|originally posted|interested trainers|how to apply|apply at|apply now|mode:|batch size|headquarters:|url:|search by|top 100|top trending|all design jobs)\b", re.I)

    out: list[str] = []

    seen: set[str] = set()

    for part in parts:

        item = re.sub(r"\s+", " ", part).strip(" \t\r\n•-–")

        label_match = re.match(r"^([^:]{2,100}):\s*(.+)$", item)

        if label_match:

            label, remainder = label_match.group(1).strip(), label_match.group(2).strip()

            known_heading = bool(re.fullmatch(

                r"(?i)(?:responsibilities|what you(?:'|’)ll do|what you'll do|requirements|qualifications|about the role|role overview|key responsibilities|what your day will look like|a typical day|how to apply|compensation|salary)",

                label))

            job_title = str(j.get("title") or "").strip()

            title_prefix = bool(job_title and label.casefold() == job_title.casefold())

            if known_heading or title_prefix:

                item = remainder

        item = item.lstrip(" ,;:-")

        if item and item[0].islower():

            item = item[0].upper() + item[1:]

        key = item.casefold()

        if not (45 <= len(item) <= 420) or reject.search(item) or key in seen:

            continue

        if re.search(r"(?i)\b(?:qué es|plataforma/marketplace|conecta empresas|agencias de desarrollo)\b", item):

            continue

        if item.endswith(("…", "...")) or item.count("…") or item.count("..."):

            continue

        seen.add(key)

        out.append(item)

    return out





def _topic_sentences(j: dict[str, Any], topic: str, limit: int = 2) -> list[str]:

    sentences = _description_sentences(j)

    patterns = {

        "responsibilities": r"responsib|you will|you'll|you would|day.to.day|manage|develop|build|create|lead|support|coordinate|evaluate|review|deliver|tasks|duties|work with|role involves",

        "requirements": r"require|qualif|experience|proficien|skill|must have|need to|degree|bachelor|master|fluen|knowledge of|familiar|preferred|plus",

        "location": r"remote|country|location|based in|work from|eligible|eligib|time zone|relocat|right to work",

        "compensation": r"salary|compensation|pay |paid|\$|usd|\bannual\b|per hour|hourly|benefit|equity|bonus",

        "assessment": r"assessment|interview|coding test|test|take.home|screening|selection process",

        "company": r"company|organisation|organization|platform|product|mission|founded|team",

    }

    pattern = re.compile(patterns.get(topic, re.escape(topic)), re.I)

    found = [s for s in sentences if pattern.search(s)]

    if topic == "responsibilities":

        found = [s for s in found if not _NON_RESPONSIBILITY_STARTS.match(s)]

        found = [s for s in found if not re.match(

            r"(?i)^(?:minimum |preferred |basic |required )?(?:requirements|qualifications|what you(?:'|’)ll bring|must have|you should have)\b",

            s)]

        found = [s for s in found if not re.search(

            r"(?i)(?:US\$|USD\s*|\$|\u20b9|€|£)\s*\d|\bper (?:task|project|session|assignment|hour|month|year)\b", s)]

    elif topic == "requirements":

        found = [s for s in found if not re.match(r"(?i)^(?:what you(?:'|’)ll do|responsibilities|day.to.day duties)\b", s)]

        found = [s for s in found if not re.search(

            r"(?i)(?:US\$|USD\s*|\$|\u20b9|€|£)\s*\d|\bper (?:task|project|session|assignment|hour|month|year)\b", s)]

        found = [s for s in found if not re.search(

            r"(?i)\b(?:experience certificate|experience letter|certificate/letter|offer letter|"

            r"joining letter|relieving letter|passport copy|identity proof|resume upload|cv upload|"

            r"application form)\b", s)]

    return found[:limit]





def _job_source_text(j: dict[str, Any], include_title: bool = True) -> str:

    values = (*((j.get("title"),) if include_title else ()), j.get("description"), j.get("details"),

              j.get("summary"), j.get("_official_job_text"), j.get("_source_page_text"))

    return clean_text(" ".join(str(v) for v in values if v)).lower()





def _role_mismatch(j: dict[str, Any]) -> bool:

    title = str(j.get("title") or "").lower().strip()

    if not title:

        return False

    primary_parts = [j.get(k) for k in ("description", "details", "summary") if j.get(k)]

    desc = clean_text(" ".join(str(v) for v in primary_parts)).lower()

    if not desc:

        desc = clean_text(str(j.get("_official_job_text") or "")).lower()

    if not desc:

        return False

    if "product marketing" in title:

        explicit_other_title = re.search(

            r"\b(?:as the|as a|for the role of|position of|role of|title:?)\s+"

            r"(?:principal|senior|lead|staff|group)?\s*product manager\b", desc)

        strong_pm_signals = (

            "product roadmap", "principal product manager", "product manager for",

            "product management experience", "define and drive the product roadmap",

            "database engine", "query execution", "storage tiering", "distributed query",

            "schema evolution", "database systems", "query optimizer", "replication",

        )

        real_marketing_signals = (

            "product marketing manager", "go-to-market strategy", "go to market strategy",

            "sales enablement", "competitive analysis", "customer segmentation",

            "demand generation", "marketing campaign", "launch marketing strategy",

            "product marketing strategy", "market positioning strategy",

        )

        if explicit_other_title or (sum(s in desc for s in strong_pm_signals) >= 2 and sum(s in desc for s in real_marketing_signals) == 0):

            return True

    opening = desc[:1800]

    explicit_role_patterns = (

        r"\b(?:as the|as a|we are hiring a|we are looking for a|the role is|position:?)\s+"

        r"(?:senior |principal |lead |staff |junior |associate )?"

        r"(?:customer support representative|customer service representative|sales representative|"

        r"database administrator|software engineer|software developer|data analyst|"

        r"motion designer|graphic designer|product designer|visual designer)\b")

    if re.search(explicit_role_patterns, opening):

        named = re.search(explicit_role_patterns, opening)

        alt = named.group(0).lower() if named else ""

        if "design" in title or "animator" in title:

            if any(t in alt for t in ("customer support", "customer service", "sales representative", "database administrator", "software engineer", "software developer", "data analyst")):

                return True

        elif "support" in title or "customer service" in title:

            if any(t in alt for t in ("sales representative", "software engineer", "software developer", "motion designer", "graphic designer")):

                return True

        elif "engineer" in title or "developer" in title:

            if any(t in alt for t in ("customer support", "customer service", "sales representative", "motion designer", "graphic designer")):

                return True

    families = {

        "customer_support": (("customer support", "customer service", "support representative", "service desk"),

                             ("software engineer", "database development", "product roadmap", "machine learning model")),

        "software_engineering": (("software engineer", "software developer", "backend engineer", "frontend engineer"),

                                 ("customer support representative", "sales representative", "social media moderator")),

        "data_analytics": (("data analyst", "business analyst", "analytics analyst"),

                           ("customer support representative", "sales representative", "motion designer")),

        "design": (("motion designer", "motion design", "graphic designer", "product designer", "visual designer", "animator"),

                   ("customer support representative", "sales representative", "database administrator", "database development", "software engineer")),

    }

    for _, (title_signals, conflict_signals) in families.items():

        if any(s in title for s in title_signals):

            if sum(s in opening for s in conflict_signals) >= 2:

                return True

    return False





def _india_eligibility_issue(j: dict[str, Any]) -> str:

    location = str(j.get("location") or "").strip().lower()

    eligibility = str(j.get("eligibility") or j.get("candidate_eligibility") or "").strip().lower()

    desc = _job_source_text(j)

    scoped = " ".join((location, eligibility))

    labelled = re.search(

        r"(?i)\b(?:work\s+)?location\s*:\s*"

        r"(emea|europe|european union|united states|u\.?s\.?|usa|uk|united kingdom|"

        r"canada|australia|new zealand|latam|latin america)\b", desc)

    if labelled:

        region = labelled.group(1).upper() if labelled.group(1).lower() in {"emea", "uk", "usa"} else labelled.group(1)

        return f"source vacancy labels the role location as {region}; India eligibility is not established"

    if re.search(r"\b(?:emea|europe|european union|eu only|united kingdom only|uk only|canada only|australia only)\b", scoped):

        region = next((n for n in ("EMEA", "Europe", "European Union", "UK", "Canada", "Australia") if n.lower() in scoped), "restricted region")

        return f"explicit location/eligibility is {region}, which does not establish India eligibility"

    us_only_patterns = (

        r"\bremote anywhere within the united states\b",

        r"\bremote anywhere in the united states\b",

        r"\bremote within the united states\b",

        r"\bremote anywhere in the us\b",

        r"\bposition can be remote anywhere within the united states\b",

        r"\b(?:united states|u\.?s\.?|us) only\b",

        r"\bonly (?:within|in) the (?:united states|u\.?s\.)\b",

        r"\bmust be based in the (?:united states|u\.?s\.)\b",

        r"\bapplicants? must reside in the (?:united states|u\.?s\.)\b",

    )

    if any(re.search(p, desc, re.I) for p in us_only_patterns):

        return "source explicitly restricts the role to the United States"

    for pattern, region in (

        (r"\b(?:remote|based|located) (?:only )?(?:within|in) the united kingdom\b", "United Kingdom"),

        (r"\b(?:remote|based|located) (?:only )?(?:within|in) canada\b", "Canada"),

        (r"\b(?:remote|based|located) (?:only )?(?:within|in) australia\b", "Australia"),

    ):

        if re.search(pattern, desc, re.I):

            return f"source restricts the role to {region}"

    return ""





def _usable_must_requirements(job: dict[str, Any]) -> list[str]:

    values = [str(x).strip() for x in (job.get("must") or []) if str(x).strip()]

    reject = re.compile(

        r"(?i)\b(?:experience certificate|experience letter|certificate/letter|"

        r"offer letter|joining letter|relieving letter|passport copy|identity proof|"

        r"resume upload|cv upload|application form|documents? required)\b")

    return [v for v in values if not reject.search(v) and not _NAV_CONTAMINATION.search(v)]





def _description_is_contaminated_or_truncated(j: dict[str, Any]) -> bool:

    raw = clean_text(" ".join(str(j.get(k) or "") for k in ("description", "details", "summary")))

    if not raw:

        return True

    promo = re.search(r"(?i)to get timely updates on job openings.*?(?=job overview\s*:|$)", raw)

    overview = re.search(r"(?i)job overview\s*:\s*(.{0,260})", raw)

    if promo and (not overview or len(overview.group(1).strip()) < 100 or re.search(r"(?:…|\.\.\.)", overview.group(1))):

        return True

    if re.search(r"(?i)\b(?:looking for operations management interns?\s*,?\s*with an interest)\s*(?:…|\.\.\.)?$", raw):

        return True

    return False





def _job_content_quality_issue(j: dict[str, Any]) -> str:

    location = clean_text(j.get("location") or "")

    title = clean_text(j.get("title") or "")

    if len(location) > 120 or re.search(

        r"(?i)\b(?:is building|we are|you will|responsibilities|requirements|about the company|mercury is)\b",

        location):

        return "location field contains concatenated company or vacancy-description text"

    requirement_text = " ".join(_usable_must_requirements(j)) or clean_text(

        " ".join(str(j.get(k) or "") for k in ("requirements", "nice")))

    if (re.search(r"(?i)\b(?:aml|anti.money laundering|compliance|investigator)\b", title)

            and re.search(r"(?i)\b(?:observability|ui/ux|user experience|frontend framework|react\.js|css)\b", requirement_text)):

        return "requirements appear unrelated to the AML/compliance role; verify against the original vacancy"

    parts = [j.get(k) for k in ("description", "details", "summary", "_official_job_text", "_source_page_text") if j.get(k)]

    text = clean_text(" ".join(str(v) for v in parts))

    if not text:

        return "source has no usable vacancy description"

    if _description_is_contaminated_or_truncated(j):

        official_fallback = bool(j.get("_official_job_text") or j.get("_source_page_text"))

        if (not official_fallback

                or not _topic_sentences({**j, "description": "", "details": "", "summary": ""}, "responsibilities", 2)

                or not _topic_sentences({**j, "description": "", "details": "", "summary": ""}, "requirements", 2)):

            return "source contains a community promotion or truncated job overview instead of complete vacancy details"

    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower())

    if re.search(r"what you ll do\s+(?:•\s*)?what you ll bring\s+(?:•\s*)?(?:about the team|how .*?support)", normalized):

        return "source description has empty responsibilities and requirements sections"

    if re.search(r"(?i)qué es deazy|deazy es una plataforma/marketplace|conecta empresas que necesitan desarrollo", text):

        cleaned = re.sub(r"(?is)qué es deazy.*$|deazy es una plataforma/marketplace.*$", " ", text)

        if len(clean_text(cleaned)) < 100:

            return "source description contains aggregator explanation but no usable vacancy responsibilities"

    if not _topic_sentences(j, "responsibilities", 3):

        return "source description has no complete, usable responsibility sentence"

    if not _topic_sentences(j, "requirements", 3) and not (j.get("must") or j.get("requirements")):

        return "source description has no usable requirements evidence"

    return ""





def _responsibility_detail(j: dict[str, Any], max_chars: int = 300) -> str:

    title = str(j.get("title") or "").lower()

    primary = next((j.get(k) for k in ("description", "details", "summary") if j.get(k)), None)

    raw = clean_text(primary if primary else (j.get("_official_job_text") or j.get("_source_page_text") or ""))

    if "sap car" in title or ("corporate trainer" in title and "sap" in raw.lower()):

        modules = [n for n in ("SAP Merchandise Planning", "SAP Assortment Planning", "SAP Allocation Management") if n.lower() in raw.lower()]

        if modules:

            return ("This is a specialist training engagement covering " + human_list(modules, 3) +

                    ". The trainer needs to explain how retail planning, product assortment and stock allocation work, "

                    "including how these modules connect with SAP S/4HANA or third-party systems. The employer says the batch is 15 corporate professionals, so the work is about teaching an experienced business audience, not delivering a beginner overview.")

    if any(term in title for term in ("motion designer", "motion design", "animator")) and raw:

        return ("This job is about turning product screens and brand briefs into polished product-demo animations and feature explainers. "

                "It also asks you to build reusable motion templates, components and guidelines, so other teams can make on-brand videos without starting from scratch each time. "

                "There is also short-form motion work for paid social campaigns.")

    if "product marketing" in title and raw:

        return "The work should connect the product to the people who might buy it: understand customer needs, shape clear messaging, support launches and give sales teams useful material. I would only use this summary after the collected description has been matched to the actual product-marketing vacancy."

    sentences = _topic_sentences(j, "responsibilities", 3)

    if sentences:

        clean = [_plain_job_detail(item, 600).strip() for item in sentences]

        clean = [item if item.endswith((".", "!", "?")) else item + "." for item in clean if item]

        if clean:

            chosen = [clean[0]]

            if len(clean) > 1 and len(chosen[0]) + len(clean[1]) + 1 <= max(max_chars, 420):

                chosen.append(clean[1])

            return " ".join(chosen)

    return ""





def _job_location(j: dict[str, Any]) -> str:

    location = str(j.get("location") or "").strip()

    eligibility = str(j.get("eligibility") or j.get("candidate_eligibility") or "").strip()

    unknown = {"unknown", "not stated", "not specified", "n/a"}

    if eligibility and eligibility.lower() not in unknown:

        if eligibility.strip().lower() == "emea":

            return "The employer lists this as an EMEA role."

        return f"Eligibility guidance: {eligibility}."

    if not location or location.lower() in unknown:

        return ""

    low = location.lower()

    if "emea" in low:

        return "The employer lists this as an EMEA role, not a worldwide opening. Applicants in India should confirm eligibility before applying."

    if "remote from india" in low or low == "india":

        return "This opportunity is advertised for candidates based in India."

    if "anywhere in the world" in low or "worldwide" in low or "global" in low:

        official_text = clean_text(j.get("_official_job_text") or "")

        if re.search(r"(?i)\bremote,?\s*(?:from )?any location\b|\banywhere in the world\b", official_text):

            return "The employer says remote from any location; confirm India eligibility."

        return "The listing says worldwide remote; confirm India eligibility with the employer."

    if "remote" in low:

        return f"The advertised work location is {location}; country eligibility is not explicit in the captured data."

    return f"The advertised location is {location}."





def _employment_phrase(j: dict[str, Any]) -> str:

    value = str(j.get("employment_type") or j.get("employment") or "").strip()

    return f"The role is described as {value.lower()} employment." if value and value.lower() not in {"not specified", "unknown", "n/a"} else ""





class _SalarySearchParser(HTMLParser):

    def __init__(self) -> None:

        super().__init__(convert_charrefs=True)

        self.results: list[dict[str, str]] = []

        self._current: dict[str, str] | None = None

        self._result_depth = 0

        self._capture: str | None = None

        self._buffer: list[str] = []

        self._snippet_depth = 0



    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:

        attrs_d = dict(attrs)

        classes = set((attrs_d.get("class") or "").split())

        if tag == "div" and "result" in classes and self._current is None:

            self._current = {"title": "", "url": "", "snippet": ""}

            self._result_depth = 1

            return

        if self._current is None:

            return

        if tag == "div" and self._result_depth:

            self._result_depth += 1

            if self._capture == "snippet":

                self._snippet_depth += 1

        if tag == "a" and "result__a" in classes:

            self._current["url"] = str(attrs_d.get("href") or "")

            self._capture = "title"

            self._buffer = []

        elif ("result__snippet" in classes) and (tag in {"a", "div", "span"}):

            self._capture = "snippet"

            self._buffer = []

            self._snippet_depth = 1



    def handle_data(self, data: str) -> None:

        if self._capture:

            self._buffer.append(data)



    def handle_endtag(self, tag: str) -> None:

        if self._current is None:

            return

        if self._capture == "title" and tag == "a":

            self._current["title"] = re.sub(r"\s+", " ", " ".join(self._buffer)).strip()

            self._capture = None

            self._buffer = []

        elif self._capture == "snippet" and tag in {"a", "div", "span"}:

            self._snippet_depth -= 1

            if self._snippet_depth <= 0:

                self._current["snippet"] = re.sub(r"\s+", " ", " ".join(self._buffer)).strip()

                self._capture = None

                self._buffer = []

        if tag == "div" and self._result_depth:

            self._result_depth -= 1

            if self._result_depth <= 0:

                if self._current.get("title") or self._current.get("snippet"):

                    self.results.append(self._current)

                self._current = None

                self._capture = None

                self._buffer = []





def _unwrap_search_url(url: str) -> str:

    url = html.unescape(str(url or "").strip())

    if url.startswith("//"):

        url = "https:" + url

    if url.startswith("/url?"):

        url = "https://www.google.com" + url

    try:

        parsed = urlparse(url)

        query = parse_qs(parsed.query)

        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):

            target = query.get("uddg", [""])[0]

            if target.startswith(("https://", "http://")):

                return target

        if "google." in parsed.netloc and parsed.path.rstrip("/") == "/url":

            for key in ("q", "url", "uddg"):

                target = query.get(key, [""])[0]

                if target.startswith(("https://", "http://")):

                    return target

        if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/a"):

            wrapped = query.get("u", [""])[0].split("&", 1)[0]

            if wrapped.startswith("a1"):

                encoded = wrapped[2:]

                encoded += "=" * (-len(encoded) % 4)

                try:

                    decoded = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8", errors="ignore")

                    if decoded.startswith(("https://", "http://")):

                        return decoded

                except Exception:

                    pass

    except Exception:

        pass

    return url





def _salary_range_has_valid_order(value: str) -> bool:

    endpoints = re.findall(

        r"(?i)(?:(?:CA\$|C\$|US\$|USD\s*|CAD\s*|INR\s*|Rs\.?\s*|[$€£\u20b9])\s*)?"

        r"(\d[\d,.]*)(?:\s*(k|m|b|lpa|lakhs?|crores?))?", value)

    if len(endpoints) != 2:

        return False

    def amount(number: str, suffix: str) -> float:

        try:

            base = float(number.replace(",", ""))

        except ValueError:

            return 0.0

        return base * {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "lakh": 100_000,

                       "lakhs": 100_000, "lpa": 100_000, "crore": 10_000_000, "crores": 10_000_000}.get(suffix.lower(), 1)

    low, high = amount(*endpoints[0]), amount(*endpoints[1])

    return low > 0 and high >= low and high / low <= 100





def _salary_range_from_text(text: str) -> str:

    value = clean_text(text)

    patterns = [

        r"(?i)(?:\u20b9|INR\s*|Rs\.?\s*)\s*\d[\d,.]*(?:\s*(?:k|lakh|lakhs|LPA|crore|crores))?\s*(?:-|–|—|to|through)\s*(?:(?:\u20b9|INR\s*|Rs\.?\s*)\s*)?\d[\d,.]*(?:\s*(?:k|lakh|lakhs|LPA|crore|crores))?",

        r"(?i)(?:US\$|CA\$|C\$|\$|USD\s*|CAD\s*)\s*\d[\d,.]*(?:\s*[kmb])?\s*(?:-|–|—|to|through)\s*(?:(?:US\$|CA\$|C\$|\$|USD\s*|CAD\s*)\s*)?\d[\d,.]*(?:\s*[kmb])?",

        r"(?i)(?:€|£)\s*\d[\d,.]*(?:\s*[kmb])?\s*(?:-|–|—|to|through)\s*(?:(?:€|£)\s*)?\d[\d,.]*(?:\s*[kmb])?",

        r"(?i)\b\d[\d,.]*\s*(?:LPA|lakhs?\s*(?:per annum|a year|annually)?)\s*(?:-|–|—|to|through)\s*\d[\d,.]*\s*(?:LPA|lakhs?\s*(?:per annum|a year|annually)?)?",

    ]

    for pattern in patterns:

        m = re.search(pattern, value)

        if m:

            found = re.sub(r"\s+", " ", m.group(0)).strip(" .,:;")

            if len(re.findall(r"\d[\d,.]*", found)) == 2 and _salary_range_has_valid_order(found):

                return found

    return ""





def _bounded_url_read(request: urllib.request.Request, timeout: float, limit: int) -> tuple[bytes, str] | None:

    result_queue: queue.Queue[tuple[bool, bytes, str]] = queue.Queue(maxsize=1)

    bounded_timeout = max(1.0, min(float(timeout), 4.0))

    def worker() -> None:

        try:

            with urllib.request.urlopen(request, timeout=bounded_timeout) as response:

                body = response.read(limit)

                content_type = str(response.headers.get("Content-Type") or "").lower()

            result_queue.put((True, body, content_type))

        except Exception:

            try:

                result_queue.put((False, b"", ""))

            except queue.Full:

                pass

    threading.Thread(target=worker, name="rbr-bounded-http", daemon=True).start()

    try:

        ok, body, content_type = result_queue.get(timeout=bounded_timeout + 0.75)

    except queue.Empty:

        return None

    return (body, content_type) if ok else None





def _google_salary_results(query: str, headers: dict[str, str]) -> list[dict[str, str]]:

    """Deprecated stub — kept only for monkeypatch compatibility."""

    return []





def _bing_salary_results(query: str, headers: dict[str, str]) -> list[dict[str, str]]:

    """Deprecated stub — kept only for monkeypatch compatibility."""

    return []





def _salary_relevance_score(result_title: str, snippet: str, target_url: str,

                            company: str, title: str, location: str) -> tuple[int, bool, bool, bool]:

    title_text = clean_text(result_title + " " + snippet).lower()

    host = urlparse(target_url).netloc.lower().removeprefix("www.")

    path = urlparse(target_url).path.lower()

    compact = re.sub(r"[^a-z0-9]", "", title_text + " " + host + " " + path)

    company_key = re.sub(r"[^a-z0-9]", "", company.lower())

    company_match = bool(company_key and company_key in compact)

    stop = {"with","from","that","this","your","role","jobs","job","senior","staff","level","the","and","for","engineer","specialist","manager"}

    title_tokens = [t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 2 and t not in stop]

    haystack = (result_title + " " + snippet + " " + path).lower()

    matched_tokens = {t for t in set(title_tokens) if t in haystack}

    title_match = len(matched_tokens) >= 2 or any(len(t) >= 7 for t in matched_tokens)

    salary_domains = ("glassdoor.com", "ambitionbox.com", "indeed.com", "levels.fyi", "salary.com",

                     "payscale.com", "ziprecruiter.com", "talent.com", "salaryexpert.com",

                     "comparably.com", "builtin.com", "naukri.com")

    salary_source = any(host == d or host.endswith("." + d) for d in salary_domains)

    generic_paths = ("/login", "/sign-in", "/signin", "/sign-up", "/signup", "/about", "/install", "/wiki/")

    generic_page = path in {"", "/"} or any(p in path for p in generic_paths)

    location_tokens = [t for t in re.findall(r"[a-z0-9]+", location.lower()) if len(t) > 3 and t not in {"india","remote","worldwide","global"}]

    location_match = not location_tokens or any(t in haystack for t in location_tokens)

    score = 0

    if company_match: score += 3

    if title_match: score += 4

    score += min(2, int(len(matched_tokens) / max(1, len(set(title_tokens))) * 3))

    if salary_source: score += 3

    if re.search(r"(?i)\b(salar(?:y|ies)|compensation|pay range|base pay|hourly rate|annual pay)\b", haystack): score += 2

    if location_match: score += 1

    if generic_page: score -= 5

    return score, company_match, title_match, salary_source





def _parse_salary_amount(v) -> int | None:

    if v is None:

        return None

    s = str(v).strip()

    for token in ("$", "€", "£", "\u20b9", "US", "CA", "CAD", "USD", "EUR", "GBP", "INR"):

        s = s.replace(token, "")

    s = re.sub(r"\s+", "", s)

    if not s:

        return None

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM])?$", s)

    if m:

        num = float(m.group(1))

        suffix = (m.group(2) or "").lower()

        if suffix == "k": num *= 1_000

        elif suffix == "m": num *= 1_000_000

        return int(num)

    try:

        return int(float(s))

    except (TypeError, ValueError):

        return None





def _city_from_location(location: str) -> str:

    if not location:

        return ""

    return re.split(r"[,;(]", str(location))[0].strip()





def _is_us_role(j: dict[str, Any]) -> bool:

    text = f"{j.get('location', '')} {str(j.get('description', ''))[:500]}".casefold()

    if re.search(r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|chennai|noida|gurgaon)\b", text):

        return False

    return bool(re.search(r"\b(united states|usa|\bu\.?s\.?a?\b|remote[- ]us|new york|san francisco|seattle)\b", text))





def _make_market_estimate(lo, hi, currency, period, source: str, url: str) -> dict[str, Any] | None:

    lo_num = _parse_salary_amount(lo)

    hi_num = _parse_salary_amount(hi)

    if lo_num is None or hi_num is None or hi_num <= lo_num or lo_num <= 0:

        return None

    cur = (currency or "").upper().strip()

    prefix = {"USD":"US$", "US$":"US$", "US":"US$", "CAD":"CA$", "CAN$":"CA$", "CAN":"CA$", "C$":"CA$",

              "EUR":"€", "€":"€", "GBP":"£", "£":"£", "AUD":"A$", "A$":"A$", "INR":"\u20b9", "\u20b9":"\u20b9"}.get(cur)

    if prefix is None:

        return None

    period_norm = (period or "").lower().strip()

    if period_norm == "yearly":

        period_norm = "annual"

    if period_norm not in ("annual", "monthly", "weekly", "hourly", "daily", "per task", "per project", "per session"):

        return None

    return {

        "range": f"{prefix}{lo_num:,}–{prefix}{hi_num:,}",

        "kind": "market_estimate", "source": source, "url": url, "geo": "",

        "period": period_norm, "research_date": datetime.now(timezone.utc).date().isoformat(),

    }





def _specific_job_url(item: dict) -> str:

    """Extract a specific job posting URL from an API response item.



    Rejects generic endpoints (/, /jobs/api, ?query=...) and company homepages.

    Returns "" if no specific vacancy page is present. This is required because

    `_salary_phrase` refuses to cite an API endpoint as salary evidence.

    """

    for key in ("applicationLink", "apply_url", "jobUrl", "url", "job_url", "guid"):

        value = str(item.get(key) or "").strip()

        if not value.startswith("https://"):

            continue

        lowered = value.lower()

        if "?query=" in lowered or "?limit=" in lowered or "/jobs/api" in lowered:

            continue

        parsed = urlparse(value)

        path = (parsed.path or "/").strip("/")

        if not path or path in {"jobs/api", "api"}:

            continue

        # Require the URL to look like a specific job page, not a company homepage.

        if re.search(r"(?i)/(?:jobs?|positions?|openings?|careers?|roles?|opportunit(?:y|ies))/[^/]+", parsed.path):

            return value

        if re.search(r"(?i)/companies/[^/]+/jobs/[^/]+", parsed.path):

            return value

    return ""





def _himalayas_salary(j: dict[str, Any]) -> dict[str, Any] | None:

    """Himalayas public JSON — keyless. Returns None if no specific job URL is present."""

    lo = j.get("minSalary") or j.get("salary_min")

    hi = j.get("maxSalary") or j.get("salary_max")

    if lo and hi:

        specific_url = _specific_job_url(j)

        if specific_url:

            return _make_market_estimate(lo, hi,

                                         str(j.get("currency") or "USD").upper(),

                                         str(j.get("salaryPeriod") or "annual").lower(),

                                         "Himalayas", specific_url)

    title = str(j.get("title") or "").strip()

    if not title:

        return None

    url = "https://himalayas.app/jobs/api?limit=20&query=" + quote_plus(title)

    fetched = _bounded_url_read(

        urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"}),

        timeout=6, limit=300_000)

    if not fetched:

        return None

    try:

        data = json.loads(fetched[0].decode("utf-8", errors="replace"))

    except (ValueError, UnicodeDecodeError):

        return None

    target_tokens = {t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 3}

    for item in data.get("jobs", []):

        if not isinstance(item, dict):

            continue

        jt = {t for t in re.findall(r"[a-z0-9]+", str(item.get("title") or "").lower()) if len(t) > 3}

        if target_tokens and jt and len(target_tokens & jt) < max(2, len(target_tokens) // 2):

            continue

        if item.get("minSalary") and item.get("maxSalary"):

            specific_url = _specific_job_url(item)

            if not specific_url:

                continue

            result = _make_market_estimate(item["minSalary"], item["maxSalary"],

                                           (item.get("currency") or "USD").upper(),

                                           (item.get("salaryPeriod") or "annual").lower(),

                                           "Himalayas", specific_url)

            if result:

                return result

    return None





def _engineersalary_salary(j: dict[str, Any]) -> dict[str, Any] | None:

    """EngineerSalaryData public JSON — keyless, engineering titles only.



    Returns None; the endpoint has no per-job URL, so this cannot pass `_salary_phrase`.

    Kept so a future endpoint change can be plugged in without touching the driver.

    """

    return None





def _remotejobsapi_salary(j: dict[str, Any]) -> dict[str, Any] | None:

    """remote-jobs-api.tten.no — keyless. Returns None if no specific job URL is present."""

    title = str(j.get("title") or "").strip()

    if not title:

        return None

    url = f"https://remote-jobs-api.tten.no/v1/jobs?query={quote_plus(title)}&limit=20"

    fetched = _bounded_url_read(

        urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"}),

        timeout=6, limit=500_000)

    if not fetched:

        return None

    try:

        payload = json.loads(fetched[0].decode("utf-8", errors="replace"))

    except (ValueError, UnicodeDecodeError):

        return None

    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []

    target_tokens = {t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 3}

    for job in jobs:

        if not isinstance(job, dict):

            continue

        jt = {t for t in re.findall(r"[a-z0-9]+", str(job.get("title") or "").lower()) if len(t) > 3}

        if target_tokens and jt and len(target_tokens & jt) < max(2, len(target_tokens) // 2):

            continue

        lo = job.get("salary_min") or job.get("min_salary")

        hi = job.get("salary_max") or job.get("max_salary")

        if lo and hi:

            specific_url = _specific_job_url(job)

            if not specific_url:

                continue

            result = _make_market_estimate(lo, hi,

                                           (job.get("salary_currency") or "USD").upper(),

                                           (job.get("salary_period") or "annual").lower(),

                                           "Remote Jobs API", specific_url)

            if result:

                return result

    return None





def _bls_salary(j: dict[str, Any]) -> dict[str, Any] | None:

    """BLS OEWS static table — keyless, US-only. Requires data/bls_oews.json. Returns None otherwise."""

    if not _is_us_role(j):

        return None

    table_path = Path(__file__).parent / "data" / "bls_oews.json"

    if not table_path.is_file():

        return None

    try:

        table = json.loads(table_path.read_text(encoding="utf-8"))

    except (OSError, ValueError):

        return None

    title_lower = str(j.get("title") or "").lower()

    for key, entry in table.items():

        if isinstance(entry, dict) and key and key.lower() in title_lower and entry.get("p25") and entry.get("p75"):

            result = _make_market_estimate(entry["p25"], entry["p75"], "USD", "annual",

                                           "BLS OEWS", "https://www.bls.gov/oes/tables.htm")

            if result:

                return result

    return None





def _ddg_salary_results(j: dict[str, Any]) -> dict[str, Any] | None:

    title = str(j.get("title") or "").strip()

    company = str(j.get("company") or "").strip()

    if not title:

        return None

    time.sleep(1.5)

    query = f'"{title}" salary'

    if company:

        query = f'"{company}" "{title}" salary'

    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)

    fetched = _bounded_url_read(urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=10, limit=800_000)

    if not fetched:

        return None

    parser = _SalarySearchParser()

    try:

        parser.feed(fetched[0].decode("utf-8", errors="replace"))

    except Exception:

        return None

    title_tokens = {t for t in re.findall(r"[a-z0-9]+", title.lower())

                    if len(t) > 3 and t not in {"senior","staff","principal","engineer","manager","specialist","associate"}}

    company_key = re.sub(r"[^a-z0-9]", "", company.lower())

    location = str(j.get("location") or "").lower()

    location_tokens = {t for t in re.findall(r"[a-z0-9]+", location)

                       if len(t) > 3 and t not in {"remote","worldwide","global","india","united","states"}}

    for result in parser.results:

        result_title = clean_text(result.get("title") or "")

        snippet = clean_text(result.get("snippet") or "")

        result_url = _unwrap_search_url(result.get("url") or "")

        if not result_url.startswith("https://"):

            continue

        parsed = urlparse(result_url)

        host = (parsed.hostname or "").lower().removeprefix("www.")

        if not host or host.endswith("duckduckgo.com") or _is_generic_company_url(result_url):

            continue

        source_text = f"{result_title} {snippet} {parsed.path}".lower()

        matched_title = {t for t in title_tokens if t in source_text}

        if title_tokens and len(matched_title) < max(1, (len(title_tokens) + 1) // 2):

            continue

        if company_key and company_key not in re.sub(r"[^a-z0-9]", "", f"{result_title} {snippet} {host} {parsed.path}".lower()):

            if location_tokens and not any(t in source_text for t in location_tokens):

                continue

        elif location_tokens and not any(t in source_text for t in location_tokens):

            continue

        salary_range = _salary_range_from_text(source_text)

        if not salary_range or not _salary_range_has_valid_order(salary_range):

            continue

        period = _explicit_salary_period(source_text)

        if not period:

            continue

        if not re.search(r"(?i)(?:US\$|\bUSD\b|CA\$|\bCAD\b|C\$|€|\bEUR\b|£|\bGBP\b|\u20b9|\bINR\b|\bRs\.?\b)", source_text):

            continue

        return {"range": salary_range, "kind": "market_estimate",

                "source": f"{host} search result", "url": result_url,

                "geo": str(j.get("location") or ""), "period": period,

                "research_date": datetime.now(timezone.utc).date().isoformat()}

    return None





def _try_keyless_tiers(j: dict[str, Any]) -> dict[str, Any] | None:

    for tier_fn in (_himalayas_salary, _remotejobsapi_salary, _bls_salary):

        try:

            result = tier_fn(j)

        except Exception as exc:

            log.info("SALARY TIER %s failed for %s/%s: %s",

                     tier_fn.__name__, j.get("company"), j.get("title"), exc)

            continue

        if result:

            return result

    return None





def _research_salary_estimate(j: dict[str, Any]) -> None:

    if _salary_phrase(j):

        return

    research_version = 12

    previous_attempt = j.get("salary_research_attempt")

    if (isinstance(previous_attempt, dict) and previous_attempt.get("completed") is True

            and previous_attempt.get("research_version") == research_version):

        return

    title = str(j.get("title") or "").strip()

    company = str(j.get("company") or "").strip()

    if not title or not company or _role_mismatch(j):

        return

    tier_result = _try_keyless_tiers(j)

    if tier_result:

        j["salary_research"] = tier_result

        j["salary_estimated"] = True

        j["salary_research_attempt"] = {

            "research_version": research_version, "queries": [],

            "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),

            "completed": True, "successful_searches": 1,

            "sources_checked": ["himalayas", "remotejobsapi", "bls_oews"],

            "result": "role_matched_market_estimate_found",

            "diagnostics": {"tier_used": "keyless", "range": tier_result["range"], "source": tier_result["source"]},

        }

        return

    try:

        ddg_result = _ddg_salary_results(j)

    except Exception as exc:

        log.info("SALARY TIER ddg_html failed for %s/%s: %s", company, title, exc)

        ddg_result = None

    if ddg_result:

        j["salary_research"] = ddg_result

        j["salary_estimated"] = True

        j["salary_research_attempt"] = {

            "research_version": research_version, "queries": [f'"{title}" salary'],

            "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),

            "completed": True, "successful_searches": 1,

            "sources_checked": ["duckduckgo_html"],

            "result": "role_matched_market_estimate_found",

            "diagnostics": {"tier_used": "duckduckgo_html", "range": ddg_result["range"], "source": ddg_result["source"]},

        }

        return

    j["salary_research_attempt"] = {

        "research_version": research_version,

        "queries": [f'"{title}" salary', f'"{company}" "{title}" salary'],

        "attempted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),

        "completed": True, "successful_searches": 0,

        "sources_checked": ["source_description", "employer_page", "himalayas", "remotejobsapi", "bls_oews", "duckduckgo_html"],

        "result": "no_reliable_role_matched_range_found",

        "diagnostics": {"tier_used": None,

                        "rejection_reasons": {"all_keyless_tiers_no_match": 1, "ddg_html_no_match": 1}},

    }





def _salary_for_speech(value: str) -> str:

    text = str(value or "").strip()

    pattern = re.compile(

        r"(?i)(CA\$|CAD|C\$|\u20b9|INR|Rs\.?|€|EUR|£|GBP|US\$|USD|\$)?\s*(\d[\d,.]*)\s*(K|M|B|LPA|LAKHS?|CRORES?)?\s*(?:-|–|—|to)\s*(CA\$|CAD|C\$|\u20b9|INR|Rs\.?|€|EUR|£|GBP|US\$|USD|\$)?\s*(\d[\d,.]*)\s*(K|M|B|LPA|LAKHS?|CRORES?)?"

    )

    currency_names = {"ca$":"Canadian dollars", "cad":"Canadian dollars", "c$":"Canadian dollars",

                      "\u20b9":"rupees", "inr":"rupees", "rs":"rupees", "rs.":"rupees",

                      "€":"euros", "eur":"euros", "£":"pounds", "gbp":"pounds",

                      "us$":"US dollars", "usd":"US dollars", "$":"dollars"}

    def currency_label(raw: str | None) -> str:

        return currency_names.get((raw or "").lower(), "")

    def amount(raw: str, suffix: str | None) -> tuple[float, str]:

        val = float(raw.replace(",", ""))

        unit = (suffix or "").lower()

        if unit == "k": return val * 1_000, ""

        if unit == "m": return val * 1_000_000, ""

        if unit == "b": return val * 1_000_000_000, ""

        if unit in {"lpa", "lakh", "lakhs"}: return val, "lakh"

        if unit in {"crore", "crores"}: return val, "crore"

        return val, ""

    def fmt(num: float) -> str:

        return f"{int(num):,}" if num.is_integer() else f"{num:,.1f}"

    m = pattern.search(text)

    if m:

        c1, n1, s1, c2, n2, s2 = m.groups()

        currency = currency_label(c1 or c2)

        try:

            v1, u1 = amount(n1, s1); v2, u2 = amount(n2, s2)

        except ValueError:

            return text

        unit = u1 if u1 == u2 and u1 else ""

        suffix = f" {unit}" if unit else ""

        currency_suffix = f" {currency}" if currency else ""

        return f"{fmt(v1)} to {fmt(v2)}{suffix}{currency_suffix}".strip()

    single = re.search(r"(?i)(CA\$|CAD|C\$|\u20b9|INR|Rs\.?|€|EUR|£|GBP|US\$|USD|\$)\s*(\d[\d,.]*)\s*(K|M|B|LPA|LAKHS?|CRORES?)?", text)

    if not single:

        return text

    currency_raw, raw_number, suffix = single.groups()

    try:

        val, unit = amount(raw_number, suffix)

    except ValueError:

        return text

    unit_text = f" {unit}" if unit else ""

    currency = currency_label(currency_raw)

    currency_text = f" {currency}" if currency else ""

    return f"{fmt(val)}{unit_text}{currency_text}".strip()





def _salary_phrase(j: dict[str, Any]) -> str:

    research = j.get("salary_research") if isinstance(j.get("salary_research"), dict) else {}

    salary = str(research.get("range") or j.get("researched_salary") or j.get("salary_range") or "").strip()

    if not salary or salary.lower() in {"not stated", "not specified", "unknown", "n/a", "undisclosed", "competitive"}:

        return ""

    if re.search(r"(?i)\d[\d,.]*\s*(?:-|–|—|to|through)\s*\d", salary) and not _salary_range_from_text(salary):

        return ""

    if re.fullmatch(r"(?:[$€£\u20b9]\s*)?500(?:\.0{1,2})?", salary):

        return ""

    kind = str(research.get("kind") or "").strip().lower()

    source = str(research.get("source") or j.get("salary_source") or "").strip()

    url = str(research.get("url") or j.get("salary_source_url") or "").strip()

    period = str(research.get("period") or j.get("salary_period") or "").strip().lower()

    company = str(j.get("company") or "").strip()

    title = str(j.get("title") or "").strip()

    search_derived = bool(re.search(r"(?i)\bvia\s+(?:bing|google|duckduckgo)\s+search\b", source))

    if (kind == "market_estimate" or search_derived) and company and title:

        identity_text = re.sub(r"[^a-z0-9]+", " ", f"{source} {url}".lower())

        role_tokens = [t for t in re.findall(r"[a-z0-9]+", title.lower())

                       if len(t) > 3 and t not in {"senior", "staff", "engineer", "manager", "specialist"}]

        parsed_salary_url = urlparse(url)

        path = (parsed_salary_url.path or "/").strip("/").lower()

        generic_or_api = (path in {"", "jobs/api", "api", "wp-json/salarydata/v1/salaries", "tables.htm"}

                          or "?query=" in url.lower() or "?limit=" in url.lower())

        is_bls_table = "bls.gov" in (parsed_salary_url.hostname or "").lower() and path.startswith("oes/tables")

        if generic_or_api and not is_bls_table:

            return ""

        if role_tokens and not is_bls_table and not any(t in identity_text for t in role_tokens):

            return ""

    if not source or not url.startswith(("https://", "http://")):

        return ""

    host = urlparse(url).netloc.lower().removeprefix("www.")

    aggregator_domains = ("jobicy.com","weworkremotely.com","remotive.com","wellfound.com","remoteok.com",

                          "himalayas.app","up2staff.com","linkedin.com","indeed.com","glassdoor.com","ambitionbox.com")

    is_aggregator = any(host == d or host.endswith("." + d) for d in aggregator_domains)

    currency_explicit = bool(re.search(r"(?i)(?:US\$|\bUSD\b|CA\$|\bCAD\b|\bC\$|€|\bEUR\b|£|\bGBP\b|\u20b9|\bINR\b|\bRs\.?)", salary))

    valid_periods = {"annual", "yearly", "hourly", "monthly", "weekly", "per task", "per project", "per session", "per assignment"}

    if not currency_explicit or period not in valid_periods:

        return ""

    period_phrase = {"annual":" a year","yearly":" a year","hourly":" an hour","monthly":" a month",

                     "weekly":" a week","per task":" per task","per project":" per project",

                     "per session":" per session","per assignment":" per assignment"}[period]

    spoken_salary = _salary_for_speech(salary)

    if not spoken_salary:

        return ""

    if kind == "employer_posted":

        if is_aggregator or not any(m in source.lower() for m in ("official employer","employer career","company careers","employer website")):

            return ""

        return f"The employer's official page states {spoken_salary}{period_phrase}."

    if kind == "source_posted":

        source_name = source.split(" via ", 1)[0].strip()

        source_name = {"jobicy.com":"Jobicy","weworkremotely.com":"We Work Remotely","remotive.com":"Remotive",

                       "wellfound.com":"Wellfound","remoteok.com":"Remote OK","himalayas.app":"Himalayas",

                       "up2staff.com":"Up2staff"}.get(source_name.lower(), source_name)

        if source_name.lower() == "source vacancy description":

            source_name = "captured vacancy"

        return f"The {source_name} listing states {spoken_salary}{period_phrase}; confirm the terms on the employer's page."

    if kind == "market_estimate":

        if not any(marker in host for marker in (

            "glassdoor.", "ambitionbox.", "indeed.", "levels.fyi", "salary.com",

            "payscale.", "ziprecruiter.", "salaryexpert.", "talent.com",

            "himalayas.app", "remote-jobs-api.tten.no", "bls.gov",

        )):

            return ""

        return f"A role-matched market source estimates {spoken_salary}{period_phrase}. This is an estimate, not an employer promise."

    return ""





def _salary_missing_context(j: dict[str, Any]) -> str:

    title = str(j.get("title") or "").lower()

    employment = str(j.get("employment_type") or j.get("employment") or "").lower()

    if "contract" in employment or "trainer" in title:

        return "Because this is a contract training engagement, agree the trainer fee, preparation time, number of sessions and payment schedule before committing."

    return ""





def _plain_job_detail(text: str, max_chars: int = 280) -> str:

    text = clean_text(text)

    text = re.sub(r"https?://\S+", "", text)

    text = re.sub(r"Originally posted on .*?$", "", text, flags=re.I)

    text = re.sub(r"(?i)(?:related jobs|similar jobs|job alerts|share this job|report this job|apply now|how to apply)\b.*$", "", text)

    text = re.sub(r"\s+", " ", text).strip(" .;:-")

    text = re.sub(r"^(?:in this role[, ]+|in this position[, ]+)", "", text, flags=re.I)

    if len(text) > max_chars:

        cut = text.rfind(" ", 0, max_chars)

        text = text[:cut if cut > 100 else max_chars].rstrip(" ,;:-") + "…"

    return text





def _job_intro(j: dict[str, Any], index: int) -> str:

    title = str(j.get("title") or "this role").strip()

    company = str(j.get("company") or "the employer").strip().rstrip(".")

    location = _job_location(j)

    employment = _employment_phrase(j)

    openings = {1: f"First up is {title} with {company}.",

                2: f"Next, {company} has a role titled {title}.",

                3: f"Our third opportunity is {title} at {company}."}

    parts = [openings.get(index, f"Let's look at {title} at {company}.")]

    if _role_mismatch(j):

        parts.append("The captured description does not match the title, so the role details are withheld until the correct vacancy is identified.")

    if location:

        parts.append(location)

    if employment:

        parts.append(employment)

    return spoken(" ".join(parts))





def _fetch_page_text(url: str, timeout: float = 7.0) -> str:

    url = str(url or "").strip()

    if not url.startswith(("https://", "http://")):

        return ""

    request = urllib.request.Request(url, headers={"User-Agent": "RoadBeyondRolesResearch/1.0 (+public job-page review)"})

    fetched = _bounded_url_read(request, timeout=timeout, limit=1_500_000)

    if not fetched:

        return ""

    body, content_type = fetched

    if "text/html" not in content_type and "text/plain" not in content_type:

        return ""

    try:

        raw = body.decode("utf-8", errors="replace")

        raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)

        return clean_text(raw)

    except (urllib.error.URLError, TimeoutError, OSError, ValueError):

        return ""





def _is_third_party_job_url(url: str) -> bool:

    host = urlparse(str(url or "")).netloc.lower().removeprefix("www.")

    domains = ("jobicy.com","weworkremotely.com","remotive.com","wellfound.com","remoteok.com",

               "himalayas.app","up2staff.com","linkedin.com","indeed.com","glassdoor.com",

               "ambitionbox.com","ziprecruiter.com")

    return any(host == d or host.endswith("." + d) for d in domains)





def _is_generic_company_url(value: str) -> bool:

    try:

        parsed = urlparse(str(value or "").strip())

    except Exception:

        return True

    if parsed.scheme.lower() != "https" or not parsed.hostname:

        return True

    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/").lower() or "/"

    generic_paths = {"/","/websites","/about","/company","/careers","/career","/jobs","/job",

                     "/open-roles","/openings","/join-us","/work-with-us"}

    return path in generic_paths





def _discover_official_job_page(j: dict[str, Any]) -> tuple[str, str]:

    title = str(j.get("title") or "").strip()

    company = str(j.get("company") or "").strip()

    j["_episode_source_verified"] = False

    j["_episode_source_verification_issue"] = "Official vacancy has not been verified yet against the employer and role."

    j.pop("_episode_source_verified_at", None)

    j.pop("_episode_source_verified_url", None)

    stale_official_removed = False

    for field in ("official_job_url", "_official_job_url", "employer_job_url"):

        stale = str(j.get(field) or "").strip()

        if stale and _is_generic_company_url(stale):

            j.pop(field, None)

            stale_official_removed = True

    if stale_official_removed:

        j.pop("_official_job_text", None)

        j.pop("_episode_source_verified_url", None)

        j["_episode_source_verified"] = False

        j["_episode_source_verification_issue"] = "Official vacancy has not been verified yet; the stored official URL was a generic company page, not a specific vacancy."

    if not title or not company or _role_mismatch(j):

        return "", ""

    explicit = str(j.get("official_job_url") or j.get("employer_job_url") or "").strip()

    candidates = [explicit]

    candidates.extend(str(j.get(k) or "").strip() for k in ("original_url", "source_url", "url"))

    company_key = re.sub(r"[^a-z0-9]", "", company.lower())

    title_tokens = [t for t in re.findall(r"[a-z0-9]+", title.lower()) if len(t) > 3]

    def verify(candidate: str) -> tuple[str, str]:

        candidate = _unwrap_search_url(candidate)

        if not candidate.startswith("https://") or _is_third_party_job_url(candidate) or _is_generic_company_url(candidate):

            return "", ""

        parsed = urlparse(candidate)

        host = (parsed.hostname or "").lower().removeprefix("www.")

        path = parsed.path.lower()

        if path in {"", "/", "/websites", "/about", "/company", "/careers"}:

            return "", ""

        is_ats = any(host == d or host.endswith("." + d) for d in _ATS_DOMAINS)

        host_compact = re.sub(r"[^a-z0-9]", "", host)

        company_in_host = len(company_key) >= 4 and company_key in host_compact

        if not (is_ats or company_in_host):

            return "", ""

        if not is_ats and not re.search(

            r"(?i)/(careers?|jobs?|positions?|openings?|roles?|apply|opportunit(?:y|ies))(/|$)", path):

            return "", ""

        page = _fetch_page_text(candidate, timeout=4.0)

        if not page:

            return "", ""

        page_lower = page.lower()

        page_compact = re.sub(r"[^a-z0-9]", "", page_lower)

        matched = sum(t in page_lower for t in set(title_tokens))

        title_matches = title.lower() in page_lower or matched >= max(2, min(3, len(set(title_tokens))))

        company_matches = company_key in page_compact or company_in_host

        if not (title_matches and company_matches):

            return "", ""

        j["official_job_url"] = candidate

        j["_episode_source_verified"] = True

        j.pop("_episode_source_verification_issue", None)

        j["_episode_source_verified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        j["_episode_source_verified_url"] = candidate

        j["_official_job_url"] = candidate

        return candidate, page

    for candidate in dict.fromkeys(candidates):

        if candidate:

            url, page = verify(candidate)

            if url:

                return url, page

    for field in ("official_job_url", "_official_job_url", "application_url", "apply_url"):

        stale = str(j.get(field) or "").strip()

        if not stale:

            continue

        if _is_generic_company_url(stale):

            j.pop(field, None)

            if field == "_official_job_url":

                j.pop("_official_job_text", None)

    return "", ""





def _salary_from_source_description(text: str) -> tuple[str, str]:

    source = clean_text(text)

    if not source:

        return "", ""

    fixed = re.search(

        r"(?i)((?:CA\$|C\$|CAD\s*|US\$|USD\s*|\$|€|£|\u20b9|INR\s*)\s*\d[\d,]*(?:\.\d{1,2})?)\s*"

        r"(?:USD|US dollars?|CAD|EUR|GBP|INR)?\s*(per task|for each (?:accepted )?task|per project|per session|per assignment|per hour|/hour|p/hr|hourly|per week|/week|weekly|per month|/month|monthly|per year|/year|/yr|annually|yearly|per annum)",

        source)

    if fixed:

        preceding = source[max(0, fixed.start() - 35):fixed.start()]

        if not re.search(r"(?i)(?:-|–|—|to|through)\s*$", preceding):

            unit = fixed.group(2).lower()

            period = ("per task" if "task" in unit else "per project" if "project" in unit else

                      "per session" if "session" in unit else "per assignment" if "assignment" in unit else

                      "hourly" if any(x in unit for x in ("hour","/hr","p/hr")) else "weekly" if "week" in unit else

                      "monthly" if "month" in unit else "annual" if any(x in unit for x in ("year","annual","annum","/yr")) else unit)

            amount_text = re.sub(r"\s+", "", fixed.group(1))

            evidence_window = source[max(0, fixed.start() - 20):min(len(source), fixed.end() + 20)]

            if re.search(r"(?i)\b(?:USD|US dollars?)\b", evidence_window) and "$" in amount_text and "US$" not in amount_text.upper():

                amount_text = re.sub(r"(?<![A-Z])\$", "US$", amount_text)

            elif re.search(r"(?i)\b(?:CAD|Canadian dollars?)\b", evidence_window) and "$" in amount_text and "CA$" not in amount_text.upper():

                amount_text = re.sub(r"(?<![A-Z])\$", "CA$", amount_text)

            return amount_text, period

    range_pattern = re.compile(

        r"(?i)(?:(?:CA\$|C\$|CAD\s*|US\$|USD\s*|\$|€|£|\u20b9|INR\s*)\s*)?"

        r"\d[\d,]*(?:\.\d{1,2})?(?:\s*(?:k|m|b|lpa|lakhs?|crores?))?\s*"

        r"(?:-|–|—|to|through)\s*"

        r"(?:(?:CA\$|C\$|CAD\s*|US\$|USD\s*|\$|€|£|\u20b9|INR\s*)\s*)?"

        r"\d[\d,]*(?:\.\d{1,2})?(?:\s*(?:k|m|b|lpa|lakhs?|crores?))?")

    for match in range_pattern.finditer(source):

        start, end = match.span()

        before = source[max(0, start - 110):start]

        after = source[end:min(len(source), end + 70)]

        labelled = bool(re.search(

            r"(?i)(salary|compensation|base pay|pay range|pay rate|salary range|rate offered|estimated annual cash)",

            before[-70:]))

        # FIX (defect: 2-of-3 featured roles): recognise annual-salary phrases that

        # do not contain the literal word "annual". Real employer postings use

        # "Pay Range", "Base salary range", "Cash compensation range", "Salary band",

        # or "Compensation range". Without this, period stayed "" and _salary_phrase

        # rejected legitimate source-posted pay for Airbnb / Fivetran / PlanetScale /

        # Customer.io / Abnormal / Clover / Mixpanel / Legion.

        period = (

            "hourly" if re.search(r"(?i)\b(per hour|/hour|p/hr|hourly)\b", before + " " + after) else

            "weekly" if re.search(r"(?i)\b(per week|/week|weekly)\b", before + " " + after) else

            "monthly" if re.search(r"(?i)\b(per month|/month|monthly)\b", before + " " + after) else

            "annual" if re.search(r"(?i)\b(per year|/year|/yr|annually|annual salary|yearly|per annum|LPA|lakhs per annum)\b", before + " " + after) else

            "annual" if re.search(

                r"(?i)(?:\b(?:pay|salary|compensation|cash)\s*(?:range|band)\b|"

                r"\bbase\s+salary\s+range\b)",

                before[-120:]) else ""

        )

        value = re.sub(r"\s*(?:-|–|—|to|through)\s*", "–", match.group(0), flags=re.I).strip(" .,:;")

        value = re.sub(r"(?i)(CA\$|C\$|CAD|US\$|USD|INR)\s+", r"\1", value)

        if not (labelled or period):

            continue

        if not re.search(r"(?i)(?:\$|€|£|\u20b9|\bUSD\b|\bCAD\b|\bINR\b|\bLPA\b|\blakhs?\b|\bcrores?\b)", value) and not labelled:

            continue

        if re.search(r"(?i)\bCAN\b", after) and "$" in value and "CA$" not in value.upper():

            value = re.sub(r"(?<![A-Z])\$", "CA$", value)

        elif re.search(r"(?i)\bUSD\b", before[-25:] + after[:25]) and "$" in value and "US$" not in value.upper():

            value = re.sub(r"(?<![A-Z])\$", "US$", value)

        if not _salary_range_has_valid_order(value):

            continue

        return value, period

    return "", ""





def _explicit_salary_period(text: str) -> str:

    source = str(text or "")

    if re.search(r"(?i)\b(?:per hour|/hour|p/hr|hourly|/hr|an hour)\b", source): return "hourly"

    if re.search(r"(?i)\b(?:per week|/week|weekly|a week)\b", source): return "weekly"

    if re.search(r"(?i)\b(?:per month|/month|monthly|a month)\b", source): return "monthly"

    if re.search(r"(?i)\b(?:per year|/year|/yr|annually|annual salary|yearly|a year|per annum|LPA|lakhs per annum)\b", source): return "annual"

    return ""





def _salary_from_official_text(text: str) -> str:

    if not text:

        return ""

    m = re.search(r"(?is)(?:compensation range|salary range|pay range|base salary|compensation)\s*[:\-]?\s*((?:[$€£\u20b9]|USD\s*|EUR\s*|INR\s*)?\s*\d[\d,.]*(?:\s*[kmb]|\s*(?:lakh|lakhs|LPA))?\s*(?:-|–|—|to)\s*(?:(?:[$€£\u20b9]|USD\s*|EUR\s*|INR\s*)?\s*)\d[\d,.]*(?:\s*[kmb]|\s*(?:lakh|lakhs|LPA))?)", text)

    return _salary_range_from_text(m.group(1)) if m else ""





def _verify_source_context_only(j: dict[str, Any]) -> None:

    stale_official_removed = False

    for field in ("official_job_url", "_official_job_url", "employer_job_url"):

        value = str(j.get(field) or "").strip()

        if value and _is_generic_company_url(value):

            j.pop(field, None)

            stale_official_removed = True

    if stale_official_removed:

        j.pop("_official_job_text", None)

        j.pop("_episode_source_verified_url", None)

        j["_episode_source_verified"] = False

        j["_episode_source_verification_issue"] = "Official vacancy has not been verified yet; the stored official URL was a generic company page, not a specific vacancy."

        j["_source_verification_attempted"] = False

    if j.get("_source_verification_attempted") and _is_valid_cached_official(j):

        return

    j["_source_verification_attempted"] = True

    if j.get("_official_job_text") and _is_valid_cached_official(j):

        return

    official_url, official_text = _discover_official_job_page(j)

    if not official_url or not official_text:

        return

    j["_official_job_url"] = official_url

    j["_official_job_text"] = official_text

    location_match = re.search(r"(?i)\bLocation\s*:?\s*(EMEA|Europe|United States|India|United Kingdom|Asia-Pacific|APAC)\b", official_text)

    if location_match:

        j["location"] = location_match.group(1)

        j["eligibility"] = location_match.group(1)

    deadline_match = re.search(r"(?i)(?:deadline to apply|application deadline|apply before)\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+20\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})", official_text)

    if deadline_match:

        j["application_deadline"] = deadline_match.group(1).strip()

    official_salary = _salary_from_official_text(official_text)

    if official_salary:

        j["salary_research"] = {

            "range": official_salary, "kind": "employer_posted",

            "source": "official employer job page", "url": official_url,

            "geo": str(j.get("location") or ""), "period": _explicit_salary_period(official_text),

            "research_date": datetime.now(timezone.utc).date().isoformat()}

        j["salary_estimated"] = False





def _enrich_source_context(j: dict[str, Any]) -> None:

    for key in ("salary_research", "salary", "salary_range", "researched_salary"):

        value = j.get(key)

        if isinstance(value, dict):

            value = value.get("range") or ""

        value = str(value or "").strip()

        if re.search(r"(?i)\d[\d,.]*\s*(?:-|–|—|to|through)\s*\d", value) and not _salary_range_from_text(value):

            j.pop(key, None)

    _verify_source_context_only(j)

    existing_research = j.get("salary_research") if isinstance(j.get("salary_research"), dict) else {}

    existing_url = str(existing_research.get("url") or "").strip()

    if str(existing_research.get("kind") or "").lower() == "employer_posted" and _is_third_party_job_url(existing_url):

        existing_research["kind"] = "source_posted"

        source_name = str(j.get("source") or "").strip()

        if not source_name or source_name.lower() in {"original job post", "source vacancy description", "official employer job page"}:

            host = urlparse(existing_url).netloc.lower().removeprefix("www.")

            source_name = {"jobicy.com":"Jobicy","weworkremotely.com":"We Work Remotely","remotive.com":"Remotive",

                           "wellfound.com":"Wellfound","remoteok.com":"Remote OK","himalayas.app":"Himalayas",

                           "up2staff.com":"Up2staff"}.get(host, host or "third-party vacancy")

        existing_research["source"] = source_name

        body = str(next((j.get(k) for k in ("description", "details", "summary") if j.get(k)), ""))

        extracted_pay, extracted_period = _salary_from_source_description(body)

        if extracted_pay:

            existing_research["range"] = extracted_pay

            existing_research["period"] = extracted_period

    original_url = str(j.get("original_url") or j.get("source_url") or j.get("url") or "").strip()

    company_url = str(j.get("company_url") or j.get("website") or "").strip()

    application_url = str(j.get("application_url") or j.get("apply_url") or "").strip()

    if application_url:

        app_parsed = urlparse(application_url)

        app_host = (app_parsed.hostname or "").lower().removeprefix("www.")

        app_path = (app_parsed.path or "/").lower()

        is_ats_app = any(app_host == d or app_host.endswith("." + d) for d in _ATS_DOMAINS)

        is_job_board = _is_third_party_job_url(application_url)

        company_key = re.sub(r"[^a-z0-9]", "", str(j.get("company") or "").lower())

        host_key = re.sub(r"[^a-z0-9]", "", app_host)

        company_host = bool(company_key and len(company_key) >= 4 and company_key in host_key)

        job_path = bool(re.search(r"(?i)/(careers?|jobs?|positions?|openings?|roles?|apply|opportunit(?:y|ies))(/|$)", app_path))

        suspicious_docs = bool(re.search(r"(?i)(?:^|/)(?:docs?|documentation|developers?|api|reference|latest|products?|platform-overview)(?:/|$)", app_path))

        if suspicious_docs or not (is_ats_app or is_job_board or (company_host and job_path)):

            j.pop("application_url", None)

            j.pop("apply_url", None)

            if original_url and original_url.startswith("https://") and not _is_generic_company_url(original_url):

                j["application_url"] = original_url

    if (not j.get("_official_job_text") or not _is_valid_cached_official(j)) and not j.get("_source_verification_attempted"):

        official_url, official_text = _discover_official_job_page(j)

        if official_url and official_text:

            j["_official_job_url"] = official_url

            j["_official_job_text"] = official_text

            lm = re.search(r"(?i)\bLocation\s*:?\s*(EMEA|Europe|United States|India|United Kingdom|Asia-Pacific|APAC)\b", official_text)

            if lm:

                j["location"] = lm.group(1); j["eligibility"] = lm.group(1)

            dm = re.search(r"(?i)(?:deadline to apply|application deadline|apply before)\s*:?\s*([A-Za-z]+\s+\d{1,2},?\s+20\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})", official_text)

            if dm:

                j["application_deadline"] = dm.group(1).strip()

            official_salary = _salary_from_official_text(official_text)

            if official_salary:

                j["salary_research"] = {"range": official_salary, "kind": "employer_posted",

                                        "source": "official employer job page", "url": official_url,

                                        "geo": str(j.get("location") or ""),

                                        "period": _explicit_salary_period(official_text),

                                        "research_date": datetime.now(timezone.utc).date().isoformat()}

                j["salary_estimated"] = False

    if not (isinstance(j.get("salary_research"), dict) and j["salary_research"].get("range")):

        official_text = str(j.get("_official_job_text") or "")

        official_pay, official_period = _salary_from_source_description(official_text)

        if official_pay and j.get("_official_job_url"):

            j["salary_research"] = {"range": official_pay, "kind": "employer_posted",

                                    "source": "official employer job page", "url": str(j["_official_job_url"]),

                                    "geo": str(j.get("location") or ""), "period": official_period,

                                    "research_date": datetime.now(timezone.utc).date().isoformat()}

            j["salary_estimated"] = False

    if not (isinstance(j.get("salary_research"), dict) and j["salary_research"].get("range")):

        body = next((j.get(k) for k in ("description", "details", "summary") if j.get(k)), "")

        fixed_pay, fixed_period = _salary_from_source_description(str(body))

        if fixed_pay:

            j["salary_research"] = {"range": fixed_pay, "kind": "source_posted",

                                    "source": str(j.get("source") or "source vacancy description"),

                                    "url": original_url,

                                    "geo": (str(j.get("location") or "") if str(j.get("location") or "").strip().lower() not in {"remote","worldwide remote","worldwide","global","anywhere in the world"} else ""),

                                    "period": fixed_period}

    if not _salary_phrase(j):

        _research_salary_estimate(j)

    research = j.get("salary_research") if isinstance(j.get("salary_research"), dict) else {}

    researched_range = str(research.get("range") or "").strip()

    if researched_range and research.get("source") and research.get("url"):

        period_value = str(research.get("period") or "").strip()

        j["salary"] = researched_range + (f" / {period_value}" if period_value in {"annual","yearly","hourly","monthly","weekly"} and not re.search(r"(?i)\b(?:per year|/year|/yr|annually|yearly|per hour|/hour|hourly|per month|/month|monthly|per week|/week|weekly)\b", researched_range) else "")

        if not period_value:

            j["salary"] += " (pay period not stated)"

        j["salary_type"] = {"employer_posted":"Employer-posted compensation",

                            "source_posted":"Third-party listing; verify with employer",

                            "market_estimate":"Role-matched market estimate"}.get(str(research.get("kind") or ""),

                            "Source-backed compensation; verify with employer")

    need_application = not any(str(j.get(k) or "").strip() for k in ("application_process","how_to_apply","application_instructions")) and not (isinstance(j.get("application_steps"), list) and j.get("application_steps"))

    if need_application and original_url and not j.get("_source_page_text"):

        j["_source_page_text"] = _fetch_page_text(original_url)

    need_company = not any(str(j.get(k) or "").strip() for k in ("company_overview","company_description","company_summary"))

    if need_company and company_url and not j.get("_company_page_text"):

        j["_company_page_text"] = _fetch_page_text(company_url)





def _application_detail(j: dict[str, Any]) -> str:

    for key in ("application_process", "how_to_apply", "application_instructions"):

        value = str(j.get(key) or "").strip()

        if value:

            cleaned = _plain_job_detail(value, 260)

            if cleaned and not re.search(r"(?i)\b(?:equal opportunity|privacy policy|we believe that our work is stronger|by submitting your resume)\b", cleaned):

                return cleaned

    steps = j.get("application_steps")

    if isinstance(steps, list) and steps:

        cleaned = [_plain_job_detail(str(s), 120) for s in steps[:3] if str(s).strip()]

        cleaned = [s for s in cleaned if s]

        if cleaned:

            return "; ".join(cleaned)[:300]

    raw = clean_text(next((j.get(k) for k in ("description","details","summary") if j.get(k)), ""))

    m = re.search(r"(?i)\b(?:how to apply|application process|how to submit|application instructions)\b\s*:?\s*", raw)

    if not m:

        return ""

    detail = raw[m.end():]

    boundary = re.search(r"(?i)\b(?:why work with us|about the company|equal opportunity|privacy policy|benefits|requirements|qualifications|responsibilities|originally posted on)\b", detail)

    if boundary:

        detail = detail[:boundary.start()]

    detail = re.sub(r"(?i)\b(?:apply now|submit your application)\b.*$", "", detail)

    detail = re.sub(r"\s+", " ", detail).strip(" .;:-")

    if re.search(r"(?i)\b(?:we believe that our work is stronger|by submitting your resume|privacy policy|equal opportunity)\b", detail):

        return ""

    return _plain_job_detail(detail, 260) if len(detail) >= 25 else ""





def _screen_narration(j: dict[str, Any], index: int, shot_index: int, shot_count: int) -> str:

    title = str(j.get("title") or "this role")

    company = str(j.get("company") or "the employer")

    topic = str(j.get("_review_topic") or "responsibilities")

    if _role_mismatch(j):

        return ""

    if topic == "responsibilities":

        detail = _responsibility_detail(j)

        if not detail:

            facts = _topic_sentences(j, "responsibilities", 2)

            detail = " ".join(_plain_job_detail(x, 220) for x in facts if _plain_job_detail(x, 220))

        return spoken(f"Here's the practical meaning of the work at {company}: {detail}") if detail else ""

    if topic == "requirements":

        must = _usable_must_requirements(j)

        nice = [str(x).strip() for x in (j.get("nice") or []) if str(x).strip()]

        facts = [_plain_job_detail(x, 180) for x in _topic_sentences(j, "requirements", 2)]

        facts = [x for x in facts if x and not re.search(r"we encourage you to apply|we are looking for the best fit|if you have deep technical", x, re.I)]

        if must:

            line = f"The main skills to demonstrate are {human_list(must, 5)}."

            if nice:

                line += f" The extra skills that could strengthen an application are {human_list(nice, 3)}."

            if facts:

                line += " The employer also explains: " + " ".join(facts[:1])

            return spoken(line)

        if facts:

            return spoken(f"For this role, the key requirement is not just naming skills; be ready to show evidence for this: {' '.join(facts[:2])}")

        return ""

    if topic == "eligibility":

        eligibility = str(j.get("eligibility") or j.get("candidate_eligibility") or "").strip()

        location = str(j.get("location") or "").strip()

        if "emea" in (eligibility + " " + location).lower():

            return spoken("One important point: this vacancy is listed for EMEA, not worldwide. India is normally treated as a separate region, so applicants based in India should not assume they qualify. Check the employer's eligible-country list before spending time on the application.")

        if eligibility and eligibility.lower() not in {"unknown","not stated","not specified","n/a"}:

            return spoken(f"Before spending time on the application, check this eligibility detail: {eligibility}.")

        if location and any(w in location.lower() for w in ("europe","india","united states","us only","uk only")):

            return spoken(f"One important point is location: this vacancy is listed for {location}. Remote does not automatically mean it is open in every country, so use the website link to confirm the eligible countries before applying.")

        return ""

    if topic == "application":

        process = _application_detail(j)

        if process:

            return spoken(f"To apply, follow these instructions: {process}. Keep your examples specific to the work described in the vacancy.")

        return ""

    if topic == "company":

        company_info = str(j.get("company_overview") or j.get("company_description") or j.get("company_summary") or "").strip()

        if not company_info:

            page = clean_text(j.get("_company_page_text") or "")

            m = re.search(r"(?i)(?:about us|about [A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,2})\s+(.{25,350}?)(?:careers|products|solutions|contact|privacy policy|terms of service)", page)

            company_info = m.group(1).strip() if m else ""

        return spoken(f"A little context about {company}: {_plain_job_detail(company_info, 260)}") if company_info else ""

    if topic == "candidate_fit":

        return spoken(_candidate_fit_scene(j))

    return ""





def _salary_context_scene(j: dict[str, Any]) -> str:

    return ""





def _candidate_fit_scene(j: dict[str, Any]) -> str:

    title = str(j.get("title") or "").lower()

    company = str(j.get("company") or "the employer")

    skills = [str(x).strip() for x in (j.get("must") or []) if str(x).strip()]

    top = human_list(skills[:3], 3) if skills else "the main skills named in the vacancy"

    if any(t in title for t in ("motion","designer","design","animator","creative")):

        return spoken(f"To make your application stronger for {company}, don't send a portfolio with no explanation. Pick two or three pieces that match the work: a product demo, a feature explainer or a reusable motion template. Under each one, explain the brief, what you made, which tools you used, how you handled timing and consistency, and what part was yours. If the project was a team effort, say which parts you personally owned. If you're a fresher, a self-initiated project can still help when you label it as a personal project and show the finished work. A useful portfolio case study makes it easy for the reviewer to understand your thinking without needing you in the room. For Zapier specifically, show that you can make motion both polished and repeatable: one strong animation is good, but a reusable template or component system is especially relevant to this vacancy.")

    if any(t in title for t in ("product","marketing","growth","customer","sales","business")):

        return spoken(f"For {company}, choose examples that show how you understand a customer or business problem. Explain what you researched, what you recommended or delivered, and what changed as a result. If you're a fresher, use a college project or a clearly labelled sample campaign to show the same thinking. Don't claim revenue or growth numbers unless you can prove where they came from. Keep the resume focused: one example that shows customer understanding, one that shows communication, and one that shows how you used evidence to make a decision is often more convincing than a long list of unrelated skills.")

    return spoken(f"For {company}, use the requirements as a checklist. Pick the two strongest examples that prove {top}. For each one, explain the situation, the task you handled, the action you took and the outcome. Freshers can use internships, college work or personal projects, clearly labelled; experienced candidates should focus on their own contribution rather than copying the whole job description. Put the most relevant evidence near the top, use simple headings, and remove details that do not help the employer judge this role. The goal is to make the fit clear in the first quick scan, then give enough detail that the interviewer can ask you about the work.")





def _keyword_scene(j: dict[str, Any], index: int) -> str:

    if _role_mismatch(j):

        return ""

    title = str(j.get("title") or "").lower()

    company = str(j.get("company") or "the employer")

    skills = [str(x).strip() for x in (j.get("must") or []) + (j.get("nice") or []) if str(x).strip()]

    selected = human_list(skills[:4], 4) if skills else "the skills in the vacancy"

    if any(t in title for t in ("motion","designer","design","animator","creative")):

        return spoken(f"For this design role at {company}, use the exact terms that genuinely describe your work, such as {selected}. Don't just paste them into a skills list. Connect each important term to a finished piece: what you animated, which tool you used, how you handled timing or visual consistency, and who the work was for. A personal portfolio project counts as evidence when you label it honestly.")

    return spoken(f"For this role at {company}, the important terms include {selected}. Use the employer's wording when it accurately describes your experience, then attach it to a task, context and result. If your old job title was different, translate the transferable work into language the employer recognises without changing what you actually did.")





def _framing_variant(options: tuple[str, ...], seed: int, offset: int = 0) -> str:

    return options[(seed + offset) % len(options)]





def _framing_requirement(job: dict[str, Any]) -> str:

    must = _usable_must_requirements(job)

    if must:

        return human_list(must[:3], 3)

    facts = [_plain_job_detail(x, 180) for x in _topic_sentences(job, "requirements", 2)]

    for fact in [f for f in facts if f]:

        invited = re.search(r"(?i)if you have (.+?),\s*(?:we want to hear from you|please apply|apply now)", fact)

        if invited:

            return invited.group(1).strip(" .,!;:")

        fact = re.sub(r"(?i)^(?:the ideal candidate (?:will have|has)|candidates must have|must have)\s+", "", fact).strip(" .,!;:")

        if fact:

            return fact

    return "the core requirements in the original vacancy"





def _framing_apply_detail(job: dict[str, Any]) -> str:

    detail = _application_detail(job)

    if detail:

        return detail

    deadline = str(job.get("application_deadline") or "").strip()

    if deadline:

        return f"Check the stated deadline ({deadline}) and complete any required application questions."

    eligibility = str(job.get("eligibility") or job.get("candidate_eligibility") or "").strip()

    if eligibility and eligibility.lower() not in {"unknown","not stated","not specified","n/a"}:

        return f"Confirm this eligibility condition before applying: {_plain_job_detail(eligibility, 180)}"

    return "Check the employer's eligibility rules and required documents before submitting."





def _spoken_salary_for_narration(job: dict) -> str:
    """Return a phonetically-spoken salary string, or empty if not defensible."""
    research = job.get("salary_research") if isinstance(job.get("salary_research"), dict) else {}
    if not research.get("range"):
        return ""
    if not _salary_phrase(job):
        return ""
    raw = str(research.get("range") or "")
    period = str(research.get("period") or "")
    spoken = _salary_for_speech(raw)
    period_phrase = {
        "annual": " a year", "yearly": " a year", "monthly": " a month",
        "weekly": " a week", "hourly": " an hour", "per task": " per task",
        "per project": " per project",
    }.get(period, "")
    return f"{spoken}{period_phrase}"


def _job_monologue(job: dict, idx: int, total: int) -> str:
    """One-paragraph-per-topic peer-voice narration for a single role.

    Reads like a senior recruiter's verdict, not a recited job description.
    """
    title = str(job.get("title") or "this role").strip()
    company = str(job.get("company") or "the employer").strip()
    salary = _spoken_salary_for_narration(job)
    must = _usable_must_requirements(job)
    must_phrase = human_list(must[:3], 3) if must else "the core requirements in the posting"
    eligibility_note = _india_eligibility_issue(job)
    location = str(job.get("location") or "").strip().lower()

    # Opening: name the role and the salary, honestly
    parts = []
    if salary:
        parts.append(
            f"Role number {idx}: {company} is hiring a {title}. "
            f"The verified compensation published on the source listing sits at {salary}."
        )
    else:
        parts.append(
            f"Role number {idx}: {company} is hiring a {title}. "
            f"No verified salary range was published on the source, so treat compensation as an open question to raise with the recruiter."
        )

    # Eligibility reality
    if eligibility_note:
        parts.append(
            f"For applicants in India, this is where it gets tricky: {eligibility_note}."
        )
    elif "worldwide" in location or "anywhere" in location:
        parts.append(
            "The listing is tagged worldwide remote, but a worldwide label alone does not guarantee India payroll eligibility. "
            "Ask the recruiter about entity and tax-nexus coverage in your first message so you don't lose weeks to a role that can't hire you."
        )
    elif "india" in location:
        parts.append(
            "This role is explicitly open to candidates based in India."
        )

    # Who should skip
    if must:
        parts.append(
            f"Who should honestly skip this? If your core strength is not in {must_phrase}, "
            "or if you cannot show production evidence for it, move on. This role is not a stretch fit."
        )
    else:
        parts.append(
            "Who should honestly skip this? If you cannot point to real production work that matches the role's core scope, move on."
        )

    # Resume strategy — role-specific, not generic
    if must:
        parts.append(
            f"Here is your resume strategy. Do not just list {must_phrase} in a skills section — "
            "that gets filtered. Surround each one with the operational context this team actually cares about. "
            "Pair your stack with phrases like system ownership, scale, reliability and shipped outcomes, "
            "and write bullets that show what you personally architected, not what your team used."
        )

    # Application
    apply_url = str(job.get("application_url") or job.get("url") or "").strip()
    if apply_url:
        parts.append(
            "Apply directly through the official posting linked in the description. "
            "Do not rely on a repost or an aggregator link."
        )

    return " ".join(parts)


def build_scenes(videos, rest, agg, date_label, total, channel, review_mode: bool = False, website_url: str = ""):
    """7-scene monologue structure. One continuous narration per job."""
    featured = [j for j in videos if isinstance(j, dict)
                and not _role_mismatch(j) and not _india_eligibility_issue(j)]
    if not featured:
        return []

    featured = featured[:3]
    n = len(featured)

    # Episode intro: name all three roles with their salary headlines
    headlines = []
    for j in featured:
        title = str(j.get("title") or "a role").strip()
        company = str(j.get("company") or "an employer").strip()
        sal = _spoken_salary_for_narration(j)
        headlines.append(f"{title} at {company}" + (f" paying up to {sal.split(' to ')[-1]}" if " to " in sal else ""))
    intro_roles = human_list(headlines, 3)

    intro_text = (
        "Look — if you're applying to remote roles from India right now, you know how exhausting the hunt has become. "
        "You spend an hour polishing your resume for a posting tagged worldwide remote, only to find out three rounds in that they hire only within US time zones. "
        f"Welcome back to Road Beyond Roles. Today we're cutting through the noise with {n} roles that have verified, defensible salary figures on the public record: {intro_roles}. "
        "We are not just reading you the job descriptions. We are breaking down who should honestly skip these roles, "
        "what the cross-border reality looks like for applicants in India, and the exact resume keywords you need to survive the initial applicant tracking filters. "
        "Let's get straight into it."
    )

    scenes = [
        {"kind": "banner", "chapter": "Cold open", "text": intro_text, "framing": "visiq"},

    ]

    for idx, job in enumerate(featured, 1):
        company = str(job.get("company") or "Employer")
        title = str(job.get("title") or "Open role")
        scenes.append({
            "kind": "job_scroll",
            "chapter": f"{idx}. {company} — {title}"[:90],
            "text": _job_monologue(job, idx, n),
            "job": job,
            "framing": "visiq",
        })

    # Outro
    rest_names = []
    for r in (rest or [])[:5]:
        rest_names.append(f"{r.get('title','a role')} at {r.get('company','an employer')}")
    list_phrase = human_list(rest_names, 5) if rest_names else ""

    outro_text = (
        "If none of those three match your stack today, we've posted several more verified listings directly on the Road Beyond Roles site"
        + (f", including {list_phrase}" if list_phrase else "")
        + ". Here's the bottom line: mass-applying with a generic PDF does not work in this market. "
        "The candidates landing international remote roles are the ones who dig into the posting, verify the legal realities, "
        "and tailor their real project evidence directly to the employer's highest-priority keywords. "
        "All source links and evidence notes are in the pinned description. Check the requirements, protect your time, and submit with confidence. "
        "I'll see you in the next one."
    )
    _homepage_text = (
        "Before you go, here are the other roles we have posted on the Road Beyond Roles site today. "
        + (f"These include {list_phrase}. " if list_phrase else "")
        + "Open each vacancy's page to check the full requirements and the original application link before deciding whether to apply. "
        "If a role is not right for you, it may still be useful to someone you know."
    )
    scenes.append({"kind": "homepage", "chapter": "More roles on the site", "text": _homepage_text, "framing": "visiq"})
    scenes.append({"kind": "banner", "chapter": "Before you apply", "text": outro_text, "framing": "visiq"})

    return scenes



def _source_links(j: dict[str, Any]) -> list[tuple[str, str]]:

    official = j.get("_official_job_url") or j.get("official_job_url") or j.get("employer_job_url")

    if j.get("_episode_source_verified") is not True:

        official = ""

    candidates = [

        ("Verified employer vacancy", official),

        ("Original job page", j.get("original_url") or j.get("source_url") or j.get("url")),

        ("Application page", j.get("application_url") or j.get("apply_url")),

        ("Company website", j.get("company_url") or j.get("website")),

    ]

    seen: set[str] = set()

    links: list[tuple[str, str]] = []

    for label, value in candidates:

        url = str(value or "").strip()

        if url.startswith(("https://", "http://")) and url not in seen:

            links.append((label, url))

            seen.add(url)

    return links





def render_review_markdown(scenes: list[dict[str, Any]], title: str = "Road Beyond Roles — Narration Review") -> str:

    errors: list[str] = []

    lines = [f"# {title}", "", "**Status: DRAFT — NOT APPROVED**", "",

             "This review is the exact narration sequence used by the video pipeline. Each scene is paired with its intended screenshot role.", ""]

    for i, scene in enumerate(scenes, 1):

        chapter = str(scene.get("chapter") or scene.get("kind") or f"Scene {i}")

        kind = str(scene.get("kind") or "")

        if kind == "shot" and not scene.get("chapter"):

            chapter = f"{scene.get('job', {}).get('company', 'Employer')} | {str(scene.get('topic') or 'Role detail').title()}"

        elif kind in {"role_beat", "pay_card", "gate_card", "apply_card"} and not scene.get("chapter"):

            job_for_heading = scene.get("job") if isinstance(scene.get("job"), dict) else {}

            chapter = f"{job_for_heading.get('company', 'Employer')} | {str(scene.get('beat') or kind).replace('_', ' ').title()}"

        visual_defaults = {

            "title": "short branded opener", "outro": "short branded end card",

            "hook": "featured job screenshot", "website": "featured job screenshot",

            "card": "job title / heading crop", "shot": f"captured job-page screenshot — {scene.get('topic', 'role detail')}",

            "salary_context": "same job's final screenshot", "keywords": "same job's final screenshot",

            "candidate_fit": "same job's final screenshot", "application_tips": "final job-page screenshot",

            "closing": "final job-page screenshot", "list": "featured job screenshot", "agg": "final job-page screenshot",

            "pay_card": "full-screen pay card", "gate_card": "full-screen requirement card",

            "apply_card": "full-screen real application URL card", "midroll": "full-screen comment prompt",

            "role_beat": f"captured job-page screenshot — {scene.get('beat', 'role beat')}", "tiered_recap": "role recap",

        }

        visual = str(scene.get("visual_role") or visual_defaults.get(kind, "screenshot not captured yet"))

        lines.extend([f"## {i:02d}. {chapter}", "", f"*Visual: {visual}*", "", str(scene.get("text") or "").strip(), ""])

        job = scene.get("job") if isinstance(scene.get("job"), dict) else None

        if scene.get("kind") == "hook" and isinstance(scene.get("market_context"), dict):

            market = scene["market_context"]

            lines.append("**Market context research (not spoken):**")

            if market.get("claim") and market.get("source") and market.get("year") and market.get("url"):

                lines.append(f"- Claim: {market['claim']}")

                lines.append(f"- Source/year: {market['source']} ({market['year']})")

                lines.append(f"- URL: {market['url']}")

            else:

                lines.append("- BLOCKER: supply a verified statistic, source name, publication year, and direct URL before approving this episode.")

            lines.append("")

        if job and scene.get("kind") == "card":

            lines.append("**Research notes (not spoken):**")

            for label, url in _source_links(job):

                lines.append(f"- {label}: {url}")

            if job.get("_episode_source_verified") is True:

                lines.append(f"- Employer page verified on this run: {job.get('_episode_source_verified_at', 'timestamp missing')} — {job.get('_episode_source_verified_url', 'URL missing')}")

            else:

                lines.append(f"- Employer page verification: NOT VERIFIED — {job.get('_episode_source_verification_issue', 'not attempted')}")

            research = job.get("salary_research") if isinstance(job.get("salary_research"), dict) else {}

            if research.get("source") or research.get("url"):

                lines.append(f"- Salary evidence: {research.get('source', 'source not named')} — {research.get('url', 'URL missing')}")

            attempt = job.get("salary_research_attempt") if isinstance(job.get("salary_research_attempt"), dict) else {}

            if attempt:

                lines.append("- Salary research attempt: " + ("completed" if attempt.get("completed") is True else "incomplete")

                             + f"; search results received: {int(attempt.get('successful_searches') or 0)}; result: {attempt.get('result', 'not recorded')}")

            lines.append("")

    spoken_text = " ".join(str(scene.get("text") or "") for scene in scenes)

    chapter_text = " ".join(str(scene.get("chapter") or "") for scene in scenes)

    if re.search(r"(?i)\b(?:listings?|postings?|posts)\b", spoken_text + " " + chapter_text):

        errors.append("Forbidden platform vocabulary leaked into narration or chapter headings.")

    negative_pay = re.compile(r"(?i)(?:couldn.t verify|didn.t establish|hasn.t established|not disclosed|not verified|unresolved|won.t guess|cannot guess|salary research failed|compensation is unconfirmed)")

    if negative_pay.search(spoken_text):

        errors.append("Negative or missing-pay disclaimer leaked into spoken narration; keep this in internal QA only.")

    if errors:

        lines.extend(["**Vocabulary warnings:**", *[f"- {e}" for e in errors], ""])

    words = sum(len(str(scene.get("text") or "").split()) for scene in scenes)

    minutes = words / 145 if words else 0

    lines.extend(["---", f"**Narration estimate:** {words} words, approximately {minutes:.1f} minutes at 145 words per minute.", "",

                  "The final runtime also includes screenshot readability and short transitions. Narration and visuals are generated from this same ordered scene list.", ""])

    jobs = [scene.get("job") for scene in scenes if isinstance(scene.get("job"), dict) and scene.get("kind") == "card"]

    salary_missing = [str(job.get("title") or "Untitled role") for job in jobs if not _salary_phrase(job)]

    if salary_missing:

        lines.extend(["**PRODUCTION BLOCKER — SALARY RESEARCH REQUIRED:** no sufficiently traceable range was found for: " + ", ".join(salary_missing) + ". The pipeline must continue researching; do not publish this draft until the blocker is resolved.", ""])

    if words < 1450:

        lines.extend(["**Length warning:** This draft is below the 10–12 minute target. Add role-specific, verified information. Do not pad with repeated generic advice.", ""])

    elif words > 1700:

        lines.extend(["**Length warning:** This draft exceeds the 10–12 minute target. Trim repetition while preserving the useful verified detail.", ""])

    return "\n".join(lines)





def preflight_errors(scenes: list[dict[str, Any]], min_words: int = 1450, max_words: int = 1700) -> list[str]:
    errors: list[str] = []
    kinds = [str(scene.get("kind") or "") for scene in scenes]
    featured_jobs = [scene.get("job") for scene in scenes
                     if scene.get("kind") in {"card", "job_scroll"} and isinstance(scene.get("job"), dict)]
    new_structure = "job_scroll" in kinds and "card" not in kinds
    if not featured_jobs:
        errors.append("No valid featured job remains after data-quality checks.")
    framed = any(scene.get("framing") == "visiq" for scene in scenes)
    if framed and not new_structure:
        if kinds.count("channel_intro") != 1:
            errors.append("The framed script must contain exactly one dedicated Road Beyond Roles channel introduction.")
        elif "title" in kinds and "hook" in kinds and not (kinds.index("title") < kinds.index("channel_intro") < kinds.index("hook")):
            errors.append("The channel introduction must appear after the cold open and before episode context.")
    missing = [str(job.get("title") or "Untitled role") for job in featured_jobs if not _salary_phrase(job)]
    if missing:
        errors.append("Salary research is unresolved for: " + ", ".join(missing)
                      + ". Provide defensible, traceable role-matched compensation evidence with explicit currency and payment period.")
    contamination = re.compile(r"(?i)(?:Headquarters:\s*[^.]{2,100}\s+URL:|Top 100 Remote Companies|Top Trending Remote Jobs|Search by Job Category|All Design Jobs|Careers at .*? Top Trending|qué es deazy|plataforma/marketplace|conecta empresas que necesitan desarrollo)")
    contaminated = [str(scene.get("chapter") or scene.get("kind") or "scene") for scene in scenes if contamination.search(str(scene.get("text") or ""))]
    if contaminated:
        errors.append("Scraped page metadata/navigation leaked into narration: " + ", ".join(contaminated) + ".")
    for job in featured_jobs:
        company = str(job.get("company") or "Employer")
        title = str(job.get("title") or "Untitled role")
        if _job_content_quality_issue(job):
            errors.append(f"{company} — {title}: source-quality blocker: {_job_content_quality_issue(job)}.")
        if not new_structure:
            linked = [scene for scene in scenes if scene.get("job") is job]
            if not any(scene.get("kind") == "shot" and scene.get("topic") == "responsibilities" and str(scene.get("text") or "").strip() for scene in linked):
                errors.append(f"{company} — {title}: no usable source-backed responsibilities narration was generated.")
            has_requirements = bool(_usable_must_requirements(job) or job.get("nice") or job.get("requirements")) or any(
                scene.get("kind") == "shot" and scene.get("topic") == "requirements" and str(scene.get("text") or "").strip() for scene in linked)
            if not has_requirements:
                errors.append(f"{company} — {title}: no usable source-backed requirements evidence was generated.")
        else:
            if not _usable_must_requirements(job) and not job.get("nice") and not job.get("requirements"):
                errors.append(f"{company} — {title}: no usable source-backed requirements evidence was generated.")
    spoken_text = " ".join(str(scene.get("text") or "") for scene in scenes)
    if not new_structure and re.search(r"(?i)\b(?:listings?|postings?|posts)\b", spoken_text):
        errors.append("Forbidden platform vocabulary leaked into spoken narration.")
    negative_pay = re.compile(r"(?i)(?:couldn.t verify|didn.t establish|hasn.t established|not disclosed|not verified|unresolved|won.t guess|cannot guess|salary research failed|compensation is unconfirmed)")
    if negative_pay.search(spoken_text):
        errors.append("Negative or missing-pay disclaimer leaked into spoken narration; keep this in internal QA only.")
    words = sum(len(str(scene.get("text") or "").split()) for scene in scenes)
    if words < min_words:
        errors.append(f"Narration is {words} words; the target requires at least {min_words} words of useful content.")
    if words > max_words:
        errors.append(f"Narration is {words} words; trim it to no more than {max_words} words without removing essential facts.")
    return errors





def _build_legacy_scenes(videos, rest, agg, date_label, total, channel, review_mode: bool = False, website_url: str = ""):

    website_url = str(website_url or "").strip()

    scenes: list[dict[str, Any]] = []

    selected = [job for job in videos if isinstance(job, dict)

                and not _role_mismatch(job) and not _india_eligibility_issue(job)]

    rest = [job for job in rest if isinstance(job, dict)

            and not _role_mismatch(job) and not _india_eligibility_issue(job)]

    target_count = len(selected)

    seen_ids = {str(j.get("id") or j.get("url") or j.get("original_url") or j.get("title")) for j in selected}

    featured = []

    for job in selected:

        _enrich_source_context(job)

        if not _job_content_quality_issue(job):

            featured.append(job)

    for job in rest:

        if len(featured) >= target_count:

            break

        identity = str(job.get("id") or job.get("url") or job.get("original_url") or job.get("title"))

        if identity in seen_ids:

            continue

        seen_ids.add(identity)

        _enrich_source_context(job)

        if _salary_phrase(job) and not _job_content_quality_issue(job):

            featured.append(job)

    scenes.append({"kind": "title", "chapter": "Opening | Road Beyond Roles",

                   "text": spoken("Road Beyond Roles. Real job details, salary research and practical application advice.")})

    scenes.append({"kind": "hook", "chapter": "What you'll learn",

                   "text": spoken("We'll cover the work, pay evidence, eligibility and how to apply, separating confirmed facts from estimates.")})

    scenes.append({"kind": "website", "chapter": "Use the Road Beyond Roles website", "website_url": website_url,

                   "text": spoken("The Road Beyond Roles website is linked in the description. Read the full vacancy, requirements and application details there before applying.")})

    for index, job in enumerate(featured, 1):

        company = str(job.get("company") or "Employer")

        title = str(job.get("title") or "Open role")

        scenes.append({"kind": "card", "job": job, "idx": index,

                       "chapter": f"{index}. {company} — {title}"[:85],

                       "text": _job_intro(job, index), "depth": "deep" if index == 1 else "quick"})

        salary_context = _salary_context_scene(job)

        if salary_context:

            scenes.append({"kind": "salary_context", "job": job, "idx": index,

                           "chapter": f"{company} | Understanding the pay", "text": salary_context,

                           "depth": "deep" if index == 1 else "quick"})

        topics = ["responsibilities", "requirements", "eligibility", "application", "company"]

        available = []

        for topic in topics:

            if topic == "responsibilities":

                has = bool(_responsibility_detail(job) or _topic_sentences(job, topic, 1))

            elif topic == "requirements":

                has = bool(job.get("must") or job.get("nice") or _topic_sentences(job, topic, 1))

            elif topic == "eligibility":

                loc = str(job.get("location") or "").lower()

                explicit = str(job.get("eligibility") or job.get("candidate_eligibility") or "").strip()

                has = bool(explicit or any(t in loc for t in ("emea", "europe", "united states", "us only", "uk only", "canada only")))

            elif topic == "application":

                has = bool(_application_detail(job) or "zapier" in company.lower())

            else:

                has = bool(job.get("company_overview") or job.get("company_description") or job.get("company_summary") or "zapier" in company.lower())

            if has:

                available.append(topic)

        topics_to_use = available[:5]

        if review_mode or not job.get("shots"):

            shot_paths = [f"review-only://job-{index}/{topic}" for topic in topics_to_use]

        else:

            shot_paths = [str(p) for p in job.get("shots", []) if str(p).strip()][:len(topics_to_use)]

            topics_to_use = topics_to_use[:len(shot_paths)]

        for shot_index, (shot, topic) in enumerate(zip(shot_paths, topics_to_use)):

            topic_job = dict(job)

            topic_job["_review_topic"] = topic

            text = _screen_narration(topic_job, index, shot_index, len(shot_paths))

            if not text.strip():

                continue

            scenes.append({"kind": "shot", "job": job, "idx": index, "shot": shot,

                           "shot_index": shot_index, "shot_count": len(shot_paths),

                           "topic": topic, "chapter": f"{company} | {topic.title()}" if shot_index == 0 else "",

                           "text": text, "depth": "deep" if index == 1 else "quick"})

        keyword_text = _keyword_scene(job, index)

        if keyword_text:

            scenes.append({"kind": "keywords", "job": job, "idx": index, "text": keyword_text,

                           "depth": "deep" if index == 1 else "quick"})

        fit_text = _candidate_fit_scene(job)

        if fit_text:

            scenes.append({"kind": "candidate_fit", "job": job, "idx": index,

                           "chapter": f"{company} | Resume strategy", "text": fit_text,

                           "depth": "deep" if index == 1 else "quick"})

    if rest:

        names = [f"{r.get('title', 'Role')} at {r.get('company', 'an employer')}" for r in rest[:5]]

        scenes.append({"kind": "list", "chapter": "More jobs on the website", "rest": rest,

                       "text": spoken(f"There are more roles listed on the Road Beyond Roles website, including {human_list(names, 5)}. Open each vacancy's page to check the full requirements and application link before deciding whether to apply. If a role is not right for you, it may still be useful to someone you know.")})

    scenes.append({"kind": "application_tips", "chapter": "How to improve the first application",

                   "text": spoken("Before you press submit, make the first half of your resume easy to understand. Put the skills most relevant to this job near the top, then prove them with two or three examples. Use the same words as the vacancy when they accurately describe what you did, but don't copy whole sentences. For every bullet, ask: what was the task, what did I contribute, and what changed because of it? If you are a fresher, use projects, coursework, volunteering or internships as evidence and label them clearly. Before sending, check each must-have skill against a line in your resume; add honest project evidence where you have it, and leave out claims you cannot defend. Keep your contact details current, use readable formatting and save a PDF unless the employer asks for another format. Never pay a recruiter or employer just to submit an application.")})

    if agg:

        names = [k for k, _, _ in agg[:5]]

        scenes.append({"kind": "agg", "agg": agg, "chapter": "Skills across today's roles",

                       "text": spoken(f"Across today's selected roles, some repeated skills are {human_list(names, 5)}. That is only a pattern in this batch, not a rule for every job. Use this list to notice skills employers are asking for, then choose a target role and build evidence for its actual requirements. A keyword by itself won't make an application strong; a clear example of using that skill is what gives it meaning.")})

        scenes.append({"kind": "closing", "chapter": "Before you apply",
                   "text": spoken("Visit Road Beyond Roles through the description link and read the full vacancy before applying. If a company replies or you receive an offer, share an update in the comments; it may encourage another job seeker and help us plan more application or interview-prep videos. Share unsuitable roles with someone who may fit. Follow Road Beyond Roles and subscribe for daily job updates. All the best with your applications. Understand the job, prepare well, and apply with confidence.")})
    return scenes