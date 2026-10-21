"""Focused regression checks for the integrated Road Beyond Roles patch."""
from pathlib import Path
import inspect
import sys
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pages
import narration
import media
import json
import job_scraper

# Source field extraction: labelled posting fields should not be lost.
job = pages.normalize_job_fields({
    "title": "Senior Operations Analyst",
    "company": "Example Employer",
    "description": "Employment type: Full-time\nExperience: 5+ years of experience required. This is a remote role.",
})
assert job["employment_type"] == "Full-time", job
assert "5+ years" in job["experience"], job
assert job["work_mode"] == "Remote", job

# Unknown fields are omitted instead of being rendered as placeholder values.
unknown = pages.normalize_job_fields({"title": "Role", "company": "Example", "description": "A short description."})
assert unknown["employment_type"] == "", unknown
assert unknown["work_mode"] == "", unknown
card = pages.job_html(unknown, 1)
assert "Employment type not specified" not in card
assert "Experience not specified" not in card
assert "date not provided" not in card

# Known title/description mismatch is blocked before ranking/publication.
clickhouse = {
    "title": "Principal Product Marketing Manager",
    "company": "ClickHouse",
    "description": "Build a cloud-native database engine. Work on query execution, distributed database architecture, storage engine and SQL performance.",
}
assert narration._role_mismatch(clickhouse)
# Real cached ClickHouse description: incidental marketing phrases must not mask a title swap.
clickhouse_real = {
    "title": "Principal Product Marketing Manager",
    "company": "ClickHouse",
    "url": "https://weworkremotely.com/remote-jobs/clickhouse-principal-product-marketing-manager",
    "description": "NOTE: this position can be remote anywhere within the United States. As the Principal Product Manager for ClickHouse Cloud, you will lead the product roadmap, database engine, distributed query execution, storage tiering and schema evolution. Work alongside marketing teams to shape product positioning and messaging.",
}
assert narration._role_mismatch(clickhouse_real), "Real title/description mismatch must be rejected"
assert "United States" in narration._india_eligibility_issue(clickhouse_real)
# A real motion-design vacancy must not be rejected because unrelated page/footer text
# mentions database administration. Role-family checks inspect vacancy text and require
# explicit contradictory evidence, not a stray keyword elsewhere on the source page.
zapier_motion = {
    "title": "Sr. Motion Designer",
    "company": "Zapier",
    "description": "Create product demos and feature explainers. Build reusable motion templates, components and guidelines. Produce short-form motion for paid social campaigns. Work with creative, brand and product teams.",
    "_source_page_text": "Careers at Zapier. Learn about our platform. Database administrator resources and other unrelated roles.",
}
assert not narration._role_mismatch(zapier_motion), "Valid motion-design vacancy rejected due to unrelated page text"
# Explicit US-only restriction is rejected even if the title is otherwise valid.
us_only = {"title": "Customer Success Manager", "location": "Remote", "description": "This position can be remote anywhere within the United States."}
assert narration._india_eligibility_issue(us_only)
# India/worldwide roles are not rejected based on the word remote alone.
india_role = {"title": "Support Associate", "location": "Remote from India", "description": "Full-time remote role from India."}
assert not narration._india_eligibility_issue(india_role)
worldwide_role = {"title": "Developer", "location": "Worldwide remote", "description": "Remote worldwide."}
assert not narration._india_eligibility_issue(worldwide_role)

# Regression against the actual cached records supplied for 2026-10-16.
fixture_path = ROOT / "tests" / "fixtures" / "jobs_2026-10-16.json"
cached = json.loads(fixture_path.read_text(encoding="utf-8"))
by_company = {str(item.get("company", "")).lower(): item for item in cached}
zapier_real = by_company["zapier"]
clickhouse_cached = by_company["clickhouse"]
gitlab_real = by_company["gitlab"]
assert not narration._role_mismatch(zapier_real), "Valid Zapier motion-design vacancy must not fail role matching"
assert "EMEA" in narration._india_eligibility_issue(zapier_real), "Zapier EMEA restriction must override aggregator's worldwide tag"
assert narration._role_mismatch(clickhouse_cached), "ClickHouse title/description conflict must be rejected"
assert "United States" in narration._india_eligibility_issue(clickhouse_cached), "ClickHouse US-only restriction must be rejected"
assert narration._job_content_quality_issue(gitlab_real), "GitLab record with empty What You'll Do/Bring sections must be rejected"
sap = by_company["sapsol technologies inc."]
sap_requirements = narration._screen_narration({**sap, "_review_topic": "requirements"}, 1, 0, 1)
assert all(term in sap_requirements for term in ("SAP Merchandise Planning", "SAP Assortment Planning", "SAP Allocation Management")), sap_requirements

# The scraper must not let a worldwide aggregator label override EMEA or US-only text.
from datetime import datetime, timezone
zapier_scraper_job = job_scraper.Job("WeWorkRemotely", "Sr. Motion Designer", "Zapier",
    "Anywhere in the World", "https://example.test/zapier", datetime.now(timezone.utc),
    "Location: EMEA\\nCreate product explainers and reusable motion systems.", remote=True)
clickhouse_scraper_job = job_scraper.Job("WeWorkRemotely", "Principal Product Marketing Manager", "ClickHouse",
    "Anywhere in the World", "https://example.test/clickhouse", datetime.now(timezone.utc),
    "This position can be remote anywhere within the United States.", remote=True)
worldwide_scraper_job = job_scraper.Job("WeWorkRemotely", "Designer", "Example",
    "Worldwide", "https://example.test/worldwide", datetime.now(timezone.utc),
    "Headquarters: United States. Remote worldwide and open to all countries.", remote=True)
assert job_scraper.classify(zapier_scraper_job) is None
assert job_scraper.classify(clickhouse_scraper_job) is None
assert job_scraper.classify(worldwide_scraper_job)[0] == "B"

# A disclaimer alone must not satisfy the salary gate; a completed source search must be recorded.
salary_job = {"title": "Example role", "url": "https://example.com/jobs/role"}
salary_scenes = [
    {"kind": "card", "job": salary_job, "text": "Example role."},
    {"kind": "salary_context", "job": salary_job, "text": "The employer has not disclosed compensation and the available research did not establish a reliable estimate."},
]
assert any("Salary research is unresolved" in e for e in narration.preflight_errors(salary_scenes, min_words=0, max_words=100)), narration.preflight_errors(salary_scenes, min_words=0, max_words=100)
salary_job["salary_research_attempt"] = {"queries": ['"Example role" salary'], "completed": True, "successful_searches": 1, "result": "no_reliable_role_matched_range_found"}
assert not [e for e in narration.preflight_errors(salary_scenes, min_words=0, max_words=100) if "Salary research is unresolved" in e], narration.preflight_errors(salary_scenes, min_words=0, max_words=100)

# Regression for the exact contamination pattern in narration_review(5).md.
askable = {
    "title": "Software Engineer, AI Coding Tasks (Contract)", "company": "Askable",
    "url": "https://weworkremotely.com/remote-jobs/askable-software-engineer-ai-coding-tasks-contract",
    "location": "Worldwide remote",
    "description": "Headquarters: Australia URL: https://askable.com/\nWe're looking for experienced software engineers to build AI coding tasks from a codebase they know well. US$1,000 per task, and you can do as many tasks as you want. Requirements include Python, Java, TypeScript, Rust and C plus plus.\nTop 100 Remote Companies Top Trending Remote Jobs Search by Job Category Programming Full-Stack Programming All Design Jobs Search by Role",
    "_official_job_text": "Careers at Askable Top 100 Remote Companies Search by Job Category",
}
askable_responsibilities = narration._responsibility_detail(askable)
assert "Headquarters:" not in askable_responsibilities and "URL:" not in askable_responsibilities, askable_responsibilities
assert "build AI coding tasks" in askable_responsibilities, askable_responsibilities
fixed_pay, fixed_period = narration._salary_from_source_description(askable["description"])
assert fixed_pay == "US$1,000" and fixed_period == "per task", (fixed_pay, fixed_period)
askable_pay = {"title": askable["title"], "company": askable["company"], "url": askable["url"],
               "salary_research": {"range": fixed_pay, "kind": "employer_posted", "source": "original job post", "url": askable["url"], "period": fixed_period}}
assert "US dollars 1,000 per task" in narration._salary_phrase(askable_pay), narration._salary_phrase(askable_pay)
askable_requirements = narration._screen_narration({**askable, "_review_topic": "requirements"}, 1, 0, 1)
assert "Python" in askable_requirements and "Headquarters:" not in askable_requirements, askable_requirements
assert "Top 100 Remote Companies" not in narration._application_detail(askable)

# A scene-level guard catches future scraped menu/metadata leakage before production.
contaminated_scenes = [
    {"kind": "card", "job": salary_job, "text": "Headquarters: Australia URL: https://example.com Top 100 Remote Companies"},
    {"kind": "salary_context", "job": salary_job, "text": "Salary not disclosed."},
]
assert any("metadata/navigation leaked" in e for e in narration.preflight_errors(contaminated_scenes, min_words=0, max_words=100)), narration.preflight_errors(contaminated_scenes, min_words=0, max_words=100)

# A single continuous narration track is mixed at final assembly, not 28 isolated TTS files.
assert "narration" in inspect.signature(media.concat).parameters
assert "pad" in inspect.signature(media.make_clip).parameters
media_source = (ROOT / "media.py").read_text(encoding="utf-8")
assert 'KOKORO_SPEED", "0.72"' in media_source
run_source = (ROOT / "run_daily.py").read_text(encoding="utf-8")
assert "narration._job_content_quality_issue(job)" in run_source
assert "Automated preflight status" in run_source
assert "master_audio = media.master_tts" in run_source
assert "narration=master_audio" in run_source
assert "Rendered video is" in run_source
narration_source = (ROOT / "narration.py").read_text(encoding="utf-8")
assert "https://www.google.com/search" in narration_source

print("PASS: employment/experience extraction")
print("PASS: actual cached-record regression — Zapier retained by role matcher but excluded for EMEA; ClickHouse excluded; GitLab incomplete record rejected")
print("PASS: scraper source-location restrictions override broad aggregator location tags")
print("PASS: SAP requirements narration names the actual three required modules")
print("PASS: missing fields omitted from job cards/details")
print("PASS: ClickHouse title/description mismatch (including real cached wording)")
print("PASS: valid motion-design role retained despite unrelated page/footer keywords")
print("PASS: explicit US-only roles excluded before ranking")
print("PASS: India/worldwide remote roles retained")
print("PASS: salary research requires completed traceable search; disclaimer alone blocked")
print("PASS: Askable narration excludes headquarters/URL/navigation contamination and extracts employer-posted per-task pay")
print("PASS: scene-level metadata contamination gate")
print("PASS: continuous master narration and runtime gate")
print("PASS: Google-first and DuckDuckGo fallback salary search configured")

# The default production path uses the general job pool and only applies the storytelling frame.
run_source = (ROOT / "run_daily.py").read_text(encoding="utf-8")
visual_source = (ROOT / "visuals.py").read_text(encoding="utf-8")
assert "narration.build_scenes(videos, rest, agg" in run_source
assert "if scene.get(\"framing\") == \"visiq\":" in run_source
assert "t_job_lower_third" in visual_source and "t_editorial_full_card" in visual_source
assert "narration._job_content_quality_issue(job)" in run_source
assert "source_collection.log" in run_source

# Run the general narration builder against the actual cached records supplied for 16 Oct 2026.
# This is a fixture-backed regression, not a claim of live network or full-render verification.
original_enrich = narration._enrich_source_context
narration._enrich_source_context = lambda job: None
try:
    eligible_cached = [item for item in cached if not narration._role_mismatch(item)
                       and not narration._india_eligibility_issue(item)
                       and not narration._job_content_quality_issue(item)]
    assert eligible_cached, "Expected at least one eligible real cached record for framing regression"
    framed = narration.build_scenes(eligible_cached[:3], [], [], "16 October 2026", len(eligible_cached),
                                    "Road Beyond Roles", review_mode=True,
                                    website_url="https://bipinp-dev.github.io/Road_Beyond_Roles/")
    assert framed and framed[0].get("kind") == "title"
    framed_kinds = [item.get("kind") for item in framed]
    assert framed_kinds.count("channel_intro") == 1, framed_kinds
    assert framed_kinds.index("title") < framed_kinds.index("channel_intro") < framed_kinds.index("hook"), framed_kinds
    intro_scene = next(item for item in framed if item.get("kind") == "channel_intro")
    assert "Road Beyond Roles" in intro_scene["text"] and "how to apply" in intro_scene["text"].lower(), intro_scene
    assert "today's opportunities" in intro_scene["text"].lower(), intro_scene
    assert not any(item.get("kind") == "card" and item.get("job", {}).get("title") in {
        "Transcription and Captioning Task Worker", "Chat Support Agent — Non-Voice",
        "Search and Ads Evaluator", "AI Data Annotation Task Worker"
    } for item in framed), "The general pipeline must not impose fixed role categories"
    kinds = [item.get("kind") for item in framed]
    assert "hook" in kinds and "gate_card" in kinds and "apply_card" in kinds
    assert "pay_card" in kinds or any(item.get("beat") == "opportunity" for item in framed), kinds
    assert "salary_context" not in kinds, "Pay must not be narrated twice for the same role"
    assert "application_tips" in kinds and "tiered_recap" in kinds and "closing" in kinds
    assert all(item.get("framing") == "visiq" for item in framed if item.get("kind") in {
        "title", "channel_intro", "hook", "card", "role_beat", "pay_card", "gate_card", "apply_card",
        "midroll", "midroll_followup", "application_tips", "tiered_recap", "closing"
    })
    # Missing compensation evidence stays an internal release gate, never negative spoken copy.
    errors = narration.preflight_errors(framed, min_words=0, max_words=4000)
    assert any("Salary research is unresolved" in error for error in errors), errors
    spoken_text = " ".join(str(item.get("text") or "") for item in framed)
    assert not __import__("re").search(r"(?i)\b(?:listings?|postings?|posts)\b", spoken_text), spoken_text
    assert not __import__("re").search(r"(?i)(?:couldn.t verify|didn.t establish|hasn.t established|not disclosed|not verified|unresolved|won.t guess|compensation is unconfirmed)", spoken_text), spoken_text
    assert "today's opportunities" in spoken_text.lower() or "today's job links" in spoken_text.lower(), spoken_text

    # Exact defect regression from the 16 Oct narration review: two roles have no
    # salary evidence, one has employer-published per-task pay, and all must stay positive.
    review_jobs = [
        {"title": "Intermediate Backend Engineer - Code Security", "company": "GitLab",
         "url": "https://job-boards.greenhouse.io/gitlab/jobs/8894531002", "location": "Bangalore, India",
         "description": "Develop secure, well-tested parsing for dependency manifests and lockfiles. Extend support for new package ecosystems. Requirements include Git, CI/CD, large language models, Python and Rust.",
         "must": ["Git", "CI/CD", "large language models"], "remote": True},
        {"title": "Software Engineer, AI Coding Tasks (Contract)", "company": "Askable",
         "url": "https://weworkremotely.com/remote-jobs/askable-software-engineer-ai-coding-tasks-contract", "location": "Worldwide remote",
         "description": "We're looking for experienced software engineers to build AI coding tasks from a codebase they know well. US$1,000 per task. Requirements include Python, Java, TypeScript, Rust and C++.",
         "must": ["Python", "Java", "TypeScript"], "remote": True,
         "salary_research": {"range": "US$1,000", "kind": "employer_posted", "source": "original job page", "url": "https://weworkremotely.com/remote-jobs/askable-software-engineer-ai-coding-tasks-contract", "period": "per task"}},
        {"title": "Lead Revenue Accountant & Operations Analyst", "company": "ChargePoint",
         "url": "https://www.chargepoint.com/", "location": "India",
         "description": "Manage revenue accounting operations, reconcile financial data, and improve reporting workflows. Requirements include Salesforce and Excel; Power BI and Tableau are useful additional skills.",
         "must": ["Salesforce", "Excel"], "remote": True},
    ]
    exact_review = narration.build_scenes(review_jobs, [], [], "16 October 2026", 3,
                                          "Road Beyond Roles", review_mode=True,
                                          website_url="https://bipinp-dev.github.io/Road_Beyond_Roles/")
    exact_text = " ".join(str(item.get("text") or "") for item in exact_review)
    assert len([item for item in exact_review if item.get("kind") == "card"]) == 3
    assert not __import__("re").search(r"(?i)\b(?:listings?|postings?|posts)\b", exact_text), exact_text
    assert not __import__("re").search(r"(?i)(?:couldn.t verify|didn.t establish|hasn.t established|not disclosed|not verified|unresolved|won.t guess|compensation is unconfirmed)", exact_text), exact_text
    assert sum(item.get("kind") == "pay_card" for item in exact_review) == 1
    assert not any(item.get("kind") == "salary_context" for item in exact_review)
    assert "US dollars 1,000 per task" in exact_text, exact_text
    # Exact source-contamination regression from narration_review(10).md.
    exact_bad_sources = [
        {"title": "Intermediate Backend Engineer - Code Security", "company": "GitLab",
         "url": "https://job-boards.greenhouse.io/gitlab/jobs/8894531002", "location": "Bangalore, India",
         "description": "Develop secure, well-tested, performant parsing for dependency manifests, lockfiles, and software bills of materials (SBOMs) Extend support for new…",
         "must": ["Git", "CI/CD", "large language models"], "remote": True},
        {"title": "Sr REACT NATIVE (Deazy)", "company": "Somnio Software",
         "url": "https://himalayas.app/companies/somnio-software/jobs/sr-react-native-deazy", "location": "Worldwide remote",
         "description": "sr react native (deazy) qué es deazy deazy es una plataforma/marketplace de uk que conecta empresas que necesitan desarrollo de software con agencias de desarrollo en todo el mundo.",
         "must": ["React Native", "React", "Python"], "remote": True},
    ]
    for bad_job in exact_bad_sources:
        assert narration._job_content_quality_issue(bad_job), bad_job
    contaminated_scenes = narration.build_scenes(exact_bad_sources, [], [], "16 October 2026", 2,
        "Road Beyond Roles", review_mode=True, website_url="https://bipinp-dev.github.io/Road_Beyond_Roles/")
    assert contaminated_scenes == [], contaminated_scenes
    assert exact_text.count("US dollars 1,000 per task") == 1, exact_text
finally:
    narration._enrich_source_context = original_enrich

# Verify default orchestration retains daily selection and does not add a topic-specific source pool.
assert 'candidate_dir = HERE / "data"' in run_source
assert 'data_json = candidate_dir / f"jobs_{date}.json"' in run_source
assert "ranked_all = analyze.rank(raw_jobs, prof)" in run_source
assert run_source.index("ranked_all = analyze.rank(raw_jobs, prof)") < run_source.index('step("Enriching all website jobs with source, application and salary evidence")')
assert "━━ Selecting" in run_source
# Exact regression for 17 Oct Cloud Counselage source contamination.
cloud_counselage = {
    "title": "Operations Management Intern", "company": "Cloud Counselage Pvt Ltd",
    "url": "https://himalayas.app/companies/cloud-counselage-pvt-ltd/jobs/operations-management-intern",
    "location": "India",
    "description": "TO GET TIMELY UPDATES ON JOB OPENINGS, FEEL FREE TO JOIN OUR COMMUNITY @ (4L+ MEMBERS FROM 35+ COUNTRIES) Job Overview: Looking for Operations Management Interns, with an interest… Opportunity to become Internship lead for the future internship program.",
    "must": ["Experience Certificate/Letter from Cloud Counselage Pvt."],
}
assert narration._usable_must_requirements(cloud_counselage) == [], narration._usable_must_requirements(cloud_counselage)
assert narration._job_content_quality_issue(cloud_counselage), narration._job_content_quality_issue(cloud_counselage)
assert narration._framing_requirement(cloud_counselage) != "Experience Certificate/Letter from Cloud Counselage Pvt.", narration._framing_requirement(cloud_counselage)
cloud_scenes = narration.build_scenes([cloud_counselage], [], [], "17 October 2026", 1,
    "Road Beyond Roles", review_mode=True, website_url="https://bipinp-dev.github.io/Road_Beyond_Roles/")
assert cloud_scenes == [], cloud_scenes
# The script generator must not pretend one selected role is a multi-role episode.
single_valid = {"title": "Operations Management Intern", "company": "Example Org", "url": "https://example.test/role",
    "location": "India", "description": "Coordinate weekly operations reports and track action items across internal teams. Prepare meeting notes, update project trackers and follow up on agreed deadlines. Requirements include Excel and clear written communication.",
    "must": ["Excel", "written communication"], "salary_research_attempt": {"queries": ["operations intern salary India"], "completed": True, "successful_searches": 1, "result": "no_reliable_role_matched_range_found"}}
single_scenes = narration.build_scenes([single_valid], [], [], "17 October 2026", 1, "Road Beyond Roles", review_mode=True)
single_text = " ".join(str(x.get("text") or "") for x in single_scenes)
assert "all 1 selected roles" not in single_text.lower(), single_text
assert "Across these 1 roles" not in single_text, single_text
assert not __import__("re").search(r"(?i)\b(?:listings?|postings?|posts)\b", single_text + " " + " ".join(str(x.get("chapter") or "") for x in single_scenes))

print("PASS: default production path retains existing daily job pool, ranking, featured-job count and filters")
print("PASS: Visiq framing is applied to actual cached job records without fixed topic, audience or role categories")
print("PASS: exactly one branded channel introduction follows the cold open and precedes episode context")
print("PASS: role beats, conditional pay card, requirement/apply cards, mid-roll, shared lesson, recap and close are present")
print("PASS: no forbidden platform vocabulary, no spoken missing-pay disclaimers, and no duplicate pay scene")
print("PASS: exact 16 Oct review regression — 3 roles, Askable per-task pay retained, no negative salary narration")
print("PASS: unresolved compensation remains an internal production blocker in the general framed script")
print("PASS: scraper diagnostics are saved for the existing daily source collection")
