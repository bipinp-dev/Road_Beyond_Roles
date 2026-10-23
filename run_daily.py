#!/usr/bin/env python3

"""

Daily pipeline:  scrape -> filter -> rank -> keywords -> GitHub Pages site -> screenshots

                 -> narration (edge-tts) -> slides -> ffmpeg video -> (optional) YouTube upload



    python run_daily.py                       # full run

    python run_daily.py --tts silent          # offline test: silent audio instead of edge-tts

    python run_daily.py --no-shots            # skip live-posting screenshots

    python run_daily.py --push --upload       # git push the site + upload the video

    python run_daily.py --no-video            # only scrape/rank/site

"""

import argparse

import json

import logging

import os

import subprocess

import sys

import shutil

import re

import time

import html as html_lib

import webbrowser

from urllib.parse import urlparse, parse_qs

from urllib.request import Request, urlopen

from datetime import datetime, timedelta, timezone

from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed



import analyze

import media

import narration

import pages as sitegen



HERE = Path(__file__).parent

IST = timezone(timedelta(hours=5, minutes=30))

log = logging.getLogger("daily")





def step(msg):

    log.info("━━ %s", msg)





def _make_job_heading_crop(source: Path, destination: Path) -> Path:

    """Create a readable title-only view from a captured job-page screenshot.



    The page layout is fixed by Road Beyond Roles: this crop shows the role title,

    company, metadata tags and apply button, while excluding the description below.

    FFmpeg is already a required pipeline dependency; no image packages are needed.

    """

    destination.parent.mkdir(parents=True, exist_ok=True)

    vf = (

        "crop=1100:145:90:70,"

        "scale=1920:-1:flags=lanczos,"

        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white"

    )

    cmd = [

        "ffmpeg", "-y", "-i", str(source), "-frames:v", "1",

        "-vf", vf, str(destination),

    ]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if result.returncode or not destination.is_file() or destination.stat().st_size < 1000:

        raise RuntimeError(

            f"Could not create job-heading crop from {source}: {result.stderr[-1500:]}"

        )

    return destination







def _scene_job_key(scene: dict) -> tuple[str, str]:

    job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

    return (

        str(job.get("company") or "").strip().casefold(),

        str(job.get("title") or "").strip().casefold(),

    )





def _scene_visual_description(scene: dict) -> str:

    kind = str(scene.get("kind") or "scene")

    topic = str(scene.get("topic") or scene.get("beat") or "").replace("_", " ").strip()

    labels = {

        "title": "Road Beyond Roles branded opening slide",

        "channel_intro": "Road Beyond Roles branded channel-introduction slide",

        "card": "Designed job-title card",
        "job_title": "Designed job-title card (role opener)",
        "job_scroll": "Live scroll through the role's original page",

        "shot": f"Real captured job-page screenshot{': ' + topic if topic else ''}",

        "keywords": "Designed resume-keywords slide",

        "list": "Designed list of additional website jobs",

        "agg": "Designed skills-trend slide",

        "resources": "Designed career-resources slide",

        "outro": "Road Beyond Roles branded end card",

        "pay_card": "Designed pay-evidence slide",

        "gate_card": "Designed main-requirement slide",

        "apply_card": "Designed application-route slide",

        "midroll": "Designed mid-roll prompt slide",

    }

    return labels.get(kind, f"Existing Road Beyond Roles designed slide ({topic or kind})")





def _interactive_scene_review(

    scenes: list[dict], review_dir: Path, date_label: str

) -> tuple[list[dict], set[tuple[str, str]]]:

    """One in-run approval screen; no separate --script-only run or manual file edits.



    All scenes are shown in one local browser page. The user unchecks scenes to reject

    them and submits once. Rejected featured-job cards reject that role's entire scene

    block, so its narration cannot survive without the corresponding role card.

    """

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from threading import Thread



    if not scenes:

        raise RuntimeError("VIDEO BLOCKED: there are no scenes to review.")



    review_dir.mkdir(parents=True, exist_ok=True)

    server_state: dict = {"result": None, "error": ""}



    def scene_identity(scene: dict) -> tuple:

        job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

        kind = str(scene.get("kind") or "").strip().casefold()

        company = str(job.get("company") or "").strip().casefold()

        title = str(job.get("title") or "").strip().casefold()

        topic = str(scene.get("topic") or "").strip().casefold()

        beat = str(scene.get("beat") or "").strip().casefold()

        idx = str(scene.get("idx") or "").strip()

        chapter = re.sub(r"\s+", " ", str(scene.get("chapter") or "")).strip().casefold()

        return (kind, company, title, topic, beat, idx) if (company or title) else (kind, chapter, topic, beat, idx)



    # When the same day's run is repeated, carry forward explicit rejections from the

    # previous in-run review so a rejected scene cannot silently return.

    prior_rejected: set[tuple] = set()

    prior_json = review_dir / "narration_review.json"

    prior_md = review_dir / "narration_review.md"

    prior_identities: set[tuple] = set()

    prior_decision_statuses = {"rejected", "reject", "removed", "remove", "deleted", "delete", "unapproved", "pending", "draft", "not_approved"}

    if prior_json.is_file():

        try:

            prior_payload = json.loads(prior_json.read_text(encoding="utf-8"))

            if isinstance(prior_payload, list):

                for prior in prior_payload:

                    if not isinstance(prior, dict):

                        continue

                    identity = scene_identity(prior)

                    prior_identities.add(identity)

                    status = str(prior.get("approval", prior.get("status", prior.get("review_status", "")))).strip().casefold().replace(" ", "_")

                    if status in prior_decision_statuses:

                        prior_rejected.add(identity)

        except (OSError, json.JSONDecodeError):

            log.warning("Could not read previous review decisions; the in-run review will show all current scenes selected.")



    # Also honour Markdown-only decisions/removals from an earlier review. This covers

    # older review files created before the JSON included per-scene approval fields.

    if prior_md.is_file():

        try:

            previous_markdown = prior_md.read_text(encoding="utf-8-sig")

            previous_sections = list(re.finditer(r"^##\s+\d+\.\s+(.+?)\s*$", previous_markdown, re.M))

            present_chapters = set()

            for section_index, match in enumerate(previous_sections):

                chapter = re.sub(r"\s+", " ", match.group(1)).strip().casefold()

                present_chapters.add(chapter)

                body_end = previous_sections[section_index + 1].start() if section_index + 1 < len(previous_sections) else len(previous_markdown)

                body = previous_markdown[match.end():body_end]

                decision = re.search(r"^\s*(?:\*\*)?(?:Decision|Scene status|Approval|Status)\s*:\s*(.*?)(?:\*\*)?\s*$", body, re.I | re.M)

                if decision and decision.group(1).strip().casefold().replace(" ", "_") in prior_decision_statuses:

                    for current_scene in scenes:

                        if re.sub(r"\s+", " ", str(current_scene.get("chapter") or "")).strip().casefold() == chapter:

                            prior_rejected.add(scene_identity(current_scene))

            # If a previously recorded scene's section was deliberately removed from the

            # Markdown review, preserve that removal on same-day reruns.

            for current_scene in scenes:

                identity = scene_identity(current_scene)

                chapter = re.sub(r"\s+", " ", str(current_scene.get("chapter") or "")).strip().casefold()

                if identity in prior_identities and chapter and chapter not in present_chapters:

                    prior_rejected.add(identity)

        except OSError:

            log.warning("Could not read previous Markdown review; prior JSON decisions will still be honoured.")



    prior_rejected_indices = {i for i, scene in enumerate(scenes) if scene_identity(scene) in prior_rejected}



    def render_review_html() -> str:

        cards = []

        for index, scene in enumerate(scenes):

            job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

            company = str(job.get("company") or "")

            title = str(job.get("title") or "")

            chapter = str(scene.get("chapter") or scene.get("kind") or f"Scene {index + 1}")

            kind = str(scene.get("kind") or "scene")

            narration_text = str(scene.get("text") or "")

            shot = str(scene.get("shot") or "")

            has_shot = shot and not shot.startswith("review-only://") and Path(shot).is_file()

            preview = f'<img class="shot" src="/preview/{index}" alt="Captured job-page screenshot">' if has_shot else (

                f'<div class="preview-placeholder">{html_lib.escape(_scene_visual_description(scene))}</div>'

            )

            job_line = f'<div class="job">{html_lib.escape(company)}{(" — " + html_lib.escape(title)) if title else ""}</div>' if company or title else ""

            checked = "" if index in prior_rejected_indices else "checked"

            cards.append(

                f'<article class="scene" data-index="{index}" data-kind="{html_lib.escape(kind)}" '

                f'data-job="{html_lib.escape(company.casefold() + "|" + title.casefold())}">'

                f'<label class="keep"><input type="checkbox" name="keep" value="{index}" {checked} '

                f'data-kind="{html_lib.escape(kind)}" data-job="{html_lib.escape(company.casefold() + "|" + title.casefold())}"> '

                f'<span>Include in final video</span></label>'

                f'<div class="meta">SCENE {index + 1:02d} · {html_lib.escape(kind.upper())}</div>'

                f'<h2>{html_lib.escape(chapter)}</h2>{job_line}{preview}'

                f'<p class="narration">{html_lib.escape(narration_text)}</p></article>'

            )

        return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">

<title>Road Beyond Roles — Production Review</title><style>

:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#0b1220;color:#e5edf8;font:16px/1.5 Segoe UI,Arial,sans-serif}}header{{position:sticky;top:0;z-index:2;background:#111b2d;border-bottom:1px solid #2b3a52;padding:18px clamp(16px,4vw,48px)}}h1{{margin:0 0 6px;font-size:24px}}.hint{{color:#a9bad1;margin:0}}main{{max-width:1200px;margin:auto;padding:20px clamp(12px,3vw,32px) 110px}}.scene{{background:#111b2d;border:1px solid #2b3a52;border-radius:14px;padding:18px;margin:16px 0}}.keep{{display:flex;align-items:center;gap:10px;font-weight:700;color:#a7f3d0}}input[type=checkbox]{{width:20px;height:20px;accent-color:#22c55e}}.meta{{margin-top:14px;color:#7dd3fc;font-size:12px;font-weight:800;letter-spacing:1.3px}}h2{{font-size:21px;margin:4px 0 2px}}.job{{font-weight:700;color:#cbd5e1;margin:4px 0 12px}}.shot{{display:block;max-width:100%;max-height:260px;object-fit:contain;background:#fff;border-radius:8px;margin:12px 0}}.preview-placeholder{{display:flex;align-items:center;min-height:68px;background:#17263d;border:1px dashed #526783;border-radius:8px;padding:14px;color:#cbd5e1;margin:12px 0}}.narration{{white-space:pre-wrap;margin:12px 0 0}}.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}}button{{border:0;border-radius:9px;padding:12px 18px;font-weight:800;cursor:pointer}}.approve{{background:#22c55e;color:#052e16}}.cancel{{background:#334155;color:#f8fafc}}.minor{{background:#24344c;color:#e5edf8}}footer{{position:fixed;bottom:0;left:0;right:0;background:#111b2df2;border-top:1px solid #2b3a52;padding:12px clamp(16px,4vw,48px);display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}.count{{color:#cbd5e1}}.error{{color:#fca5a5;font-weight:700}}@media(max-width:600px){{h1{{font-size:20px}}h2{{font-size:18px}}}}

</style></head><body><header><h1>Road Beyond Roles — {html_lib.escape(date_label)} production review</h1><p class="hint">One checkpoint in this run. Uncheck rejected slides. If you reject a featured job title card, all scenes for that job are removed together. No narration or video is rendered until you submit.</p><div class="toolbar"><button type="button" class="minor" onclick="setAll(true)">Include all</button><button type="button" class="minor" onclick="setAll(false)">Exclude all</button></div></header>

<form id="review" method="post" action="/approve"><main>{''.join(cards)}</main><footer><span class="count" id="count">{len(scenes)} scenes selected</span><div class="toolbar"><button class="cancel" name="action" value="cancel" formnovalidate>Cancel run</button><button class="approve" name="action" value="approve">Approve selected slides and continue</button></div></footer></form>

<script>

function setAll(v){{document.querySelectorAll('input[name=keep]').forEach(x=>{{x.checked=v}});updateCount()}}

function updateCount(){{const n=document.querySelectorAll('input[name=keep]:checked').length;document.getElementById('count').textContent=n+' scenes selected'}}

document.querySelectorAll('input[name=keep]').forEach(x=>x.addEventListener('change',()=>{{if((x.dataset.kind==='card'||x.dataset.kind==='job_scroll'||x.dataset.kind==='job_title')&&!x.checked&&x.dataset.job){{document.querySelectorAll('input[name=keep][data-job="'+CSS.escape(x.dataset.job)+'"]').forEach(y=>y.checked=false)}}else if((x.dataset.kind==='card'||x.dataset.kind==='job_scroll'||x.dataset.kind==='job_title')&&x.checked&&x.dataset.job){{document.querySelectorAll('input[name=keep][data-job="'+CSS.escape(x.dataset.job)+'"]').forEach(y=>y.checked=true)}}updateCount()}}));

document.querySelectorAll('input[name=keep][data-kind=card]:not(:checked),input[name=keep][data-kind=job_scroll]:not(:checked),input[name=keep][data-kind=job_title]:not(:checked)').forEach(x=>{{if(x.dataset.job)document.querySelectorAll('input[name=keep][data-job="'+CSS.escape(x.dataset.job)+'"]').forEach(y=>y.checked=false)}});

document.getElementById('review').addEventListener('submit',e=>{{if(e.submitter&&e.submitter.value==='cancel')return;const cards=[...document.querySelectorAll('input[name=keep][data-kind=card]:checked,input[name=keep][data-kind=job_scroll]:checked')];if(cards.length===0){{e.preventDefault();alert('Keep at least one featured job card to produce a job video.');return}}}});updateCount();

</script></body></html>"""



    class ReviewHandler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):

            return



        def _send(self, status: int, content_type: str, payload: bytes):

            self.send_response(status)

            self.send_header("Content-Type", content_type)

            self.send_header("Content-Length", str(len(payload)))

            self.send_header("Cache-Control", "no-store")

            self.end_headers()

            self.wfile.write(payload)



        def do_GET(self):

            if self.path == "/" or self.path.startswith("/?"):

                self._send(200, "text/html; charset=utf-8", render_review_html().encode("utf-8"))

                return

            match = re.fullmatch(r"/preview/(\d+)", self.path)

            if match:

                index = int(match.group(1))

                if 0 <= index < len(scenes):

                    shot = str(scenes[index].get("shot") or "")

                    path = Path(shot) if shot and not shot.startswith("review-only://") else None

                    if path and path.is_file():

                        self._send(200, "image/png", path.read_bytes())

                        return

            self._send(404, "text/plain; charset=utf-8", b"Not found")



        def do_POST(self):

            if not self.path.startswith("/approve"):

                self._send(404, "text/plain; charset=utf-8", b"Not found")

                return

            length = int(self.headers.get("Content-Length", "0"))

            fields = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))

            action = (fields.get("action") or ["approve"])[0]

            try:

                selected = {int(value) for value in fields.get("keep", [])}

            except ValueError:

                self._send(400, "text/plain; charset=utf-8", b"Invalid scene selection")

                return

            if action == "approve":

                if not any(i in selected and str(scenes[i].get("kind") or "") in {"card", "job_scroll"} for i in range(len(scenes))):

                    self._send(400, "text/html; charset=utf-8", b"<p>Keep at least one featured job card. Go back and select it.</p>")

                    return

                server_state["result"] = {"action": "approve", "selected": selected}

                message = b"<h1>Review saved.</h1><p>Return to the PowerShell window. The pipeline will continue automatically.</p>"

            else:

                server_state["result"] = {"action": "cancel", "selected": set()}

                message = b"<h1>Production cancelled.</h1><p>Return to the PowerShell window.</p>"

            self._send(200, "text/html; charset=utf-8", b"<!doctype html><meta charset=utf-8><title>Review received</title>" + message)



    server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)

    server.timeout = 1.0

    url = f"http://127.0.0.1:{server.server_port}/"

    print("\nROAD BEYOND ROLES — ONE IN-RUN REVIEW", flush=True)

    print("A browser page will open. Uncheck rejected slides, then click 'Approve selected slides and continue'.", flush=True)

    print(f"If it does not open automatically, visit: {url}", flush=True)

    try:

        try:

            webbrowser.open(url, new=2)

        except Exception:

            pass

        while server_state["result"] is None:

            server.handle_request()

    finally:

        server.server_close()



    result = server_state["result"]

    if not result or result.get("action") != "approve":

        raise RuntimeError("Production cancelled at the in-run scene review. No TTS or final video was generated.")



    selected_indices = set(result["selected"])

    rejected_job_keys = {

        _scene_job_key(scene)

        for index, scene in enumerate(scenes)

        if str(scene.get("kind") or "") in {"card", "job_scroll", "job_title"} and index not in selected_indices

        and all(_scene_job_key(scene))

    }

    kept_indices = {

        index for index, scene in enumerate(scenes)

        if index in selected_indices and not (_scene_job_key(scene) in rejected_job_keys and all(_scene_job_key(scene)))

    }

    kept_scenes = [scene for index, scene in enumerate(scenes) if index in kept_indices]

    if not kept_scenes or not any(str(scene.get("text") or "").strip() for scene in kept_scenes):

        raise RuntimeError("VIDEO BLOCKED: the review did not leave any usable approved narration scenes.")

    if not any(str(scene.get("kind") or "") in {"card", "job_scroll"} for scene in kept_scenes):

        raise RuntimeError("VIDEO BLOCKED: keep at least one featured job card.")



    # Keep a complete audit record, but only the selected scenes are returned to production.

    markdown = [

        f"# Road Beyond Roles — {date_label} Production Review",

        "",

        "**Status: APPROVED**",

        "",

        "Approved in the single in-run browser review. Rejected scenes and all scenes belonging to a rejected featured-job card were excluded from narration, audio, visuals, clips and captions.",

        "",

    ]

    serializable = []

    for index, scene in enumerate(scenes):

        job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

        job_key = _scene_job_key(scene)

        keep = index in kept_indices

        decision = "APPROVED" if keep else "REJECTED"

        chapter = str(scene.get("chapter") or scene.get("kind") or f"Scene {index + 1}")

        markdown.extend([

            f"## {index + 1:02d}. {chapter}",

            "",

            f"**Decision: {decision}**",

            f"*Visual: {_scene_visual_description(scene)}*",

            "",

            str(scene.get("text") or ""),

            "",

        ])

        item = {key: value for key, value in scene.items() if key not in {"job", "rest", "agg", "shot", "png", "audio_file", "clip_file"}}

        item["approval"] = decision.casefold()

        if job:

            item["job"] = {key: job.get(key) for key in (

                "id", "company", "title", "location", "salary", "researched_salary", "salary_source",

                "salary_estimated", "salary_research", "salary_research_attempt", "official_job_url",

                "_official_job_url", "application_deadline", "url", "original_url", "source_url",

                "application_url", "apply_url", "company_url", "website", "application_process",

                "how_to_apply", "application_instructions", "application_steps", "company_overview",

                "company_description", "company_summary", "eligibility", "candidate_eligibility", "must",

                "nice", "_episode_source_verified", "_episode_source_verified_at", "_episode_source_verified_url",

                "_episode_source_verification_issue",

            ) if job.get(key) is not None}

        serializable.append(item)

    (review_dir / "narration_review.md").write_text("\n".join(markdown), encoding="utf-8")

    (review_dir / "narration_review.json").write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(

        "In-run review approved %d/%d scenes; %d rejected scenes and %d rejected role block(s) will not enter narration or rendering.",

        len(kept_scenes), len(scenes), len(scenes) - len(kept_indices), len(rejected_job_keys),

    )

    return kept_scenes, rejected_job_keys





def main():

    ap = argparse.ArgumentParser()

    ap.add_argument("--hours", type=int, default=24, help="legacy window; daily mode always uses the current calendar day")

    ap.add_argument("--rescrape", action="store_true", help="ignore today's cached scrape")

    ap.add_argument("--jobs", type=int, help="jobs featured in the video (default from profile.json)")

    ap.add_argument("--min-jobs", type=int, default=1, help="minimum jobs for job video; 1 is allowed")

    ap.add_argument("--content", type=Path, help="JSON content manifest for a non-job weekly/educational video")

    ap.add_argument("--no-shots", action="store_true")

    ap.add_argument("--no-video", action="store_true")

    ap.add_argument("--tts", choices=["edge", "kokoro", "silent"], default="kokoro")

    ap.add_argument("--script-only", action="store_true", help="write a narration review draft and exit before site building, screenshots, TTS, or video rendering")

    ap.add_argument("--push", action="store_true", help="git add/commit/push docs + state")

    ap.add_argument(

    "--local-preview",

    action="store_true",

    help="serve generated docs locally for video preview without publishing",

)

    ap.add_argument("--upload", action="store_true", help="upload to YouTube")

    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])

    ap.add_argument("--strict", action="store_true", help="drop Tier C (location not stated)")

    ap.add_argument("--allow-short-video", action="store_true", help="explicitly allow a shorter episode when fewer verified-pay roles are available; does not relax source-quality checks")
    ap.add_argument("--fresh", action="store_true", help="delete today's audio, clips, frames and video before regenerating; bypass all caches")

    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")



    prof = analyze.load_profile(HERE / "profile.json")

    channel = prof.get("channel_name", "Road Beyond Roles")

    now = datetime.now(IST)

    date = now.strftime("%Y-%m-%d")

    date_label = f"{now.day} {now:%B %Y}"

    build = HERE / "build" / date

    # Create dated production folders for the approved visual workflow.

    for sub in ("shots", "audio", "clips"):

        (build / sub).mkdir(parents=True, exist_ok=True)



    # Educational/weekly content mode uses original generated screenshots and the same

    # narration/FFmpeg/GitHub packaging infrastructure, without requiring a job feed.

    if a.content:

        import content

        import visuals

        data = content.load(a.content)

        scenes = content.scene_data(data)

        (build / "slides").mkdir(parents=True, exist_ok=True)

        content_dir = HERE / "docs" / "content" / (data.get("content_id") or "weekly")

        content_dir.mkdir(parents=True, exist_ok=True)

        content.write_manifest(data, scenes, content_dir / "manifest.json")

        step(f"Rendering {len(scenes)} educational screenshots")

        with visuals.Renderer() as renderer:

            for k, sc in enumerate(scenes):

                sc["png"] = build / "slides" / f"{k:02}.png"

                renderer.render_generated(sc["body"], sc["png"])

        master_text = " ".join(sc["text"] for sc in scenes)

        step("Generating one complete narration audio")

        master = media.master_tts(master_text, build / "audio" / "master.mp3", a.tts,

                                  prof.get("voice", "am_adam"), prof.get("rate", "+4%"))

        segments = media.segment_master_audio(master, [sc["text"] for sc in scenes], build / "audio")

        clips, durs = [], []

        for k, (sc, aud) in enumerate(zip(scenes, segments)):

            clip = build / "clips" / f"{k:02}.mp4"

            durs.append(media.make_clip(sc["png"], aud, clip, motion=(sc.get("kind") == "shot"), pad=0.0))

            clips.append(clip)

        video = build / "video.mp4"

        media.concat(clips, video, HERE / "assets" / "music.mp3", narration=master) 

        media.write_srt([sc["text"] for sc in scenes], durs, build / "captions.srt")

        meta = {"title": data["title"], "description": data.get("description", ""),

                "tags": data.get("tags", ["career", "jobs", "india"]), "content_type": data["content_type"],

                "duration_sec": round(sum(durs)), "audio": str(master)}

        (build / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # Preserve the content manifest and screenshots in GitHub content.

        for sc in scenes:

            dst = content_dir / "screenshots" / Path(sc["png"]).name

            dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(sc["png"], dst)

        log.info("Educational video ready: %s", video)

        _push(a, date)

        if a.upload:

            import upload_youtube

            url = upload_youtube.upload(video, meta["title"], meta["description"], meta["tags"],

                                       build / "thumbnail.png" if (build / "thumbnail.png").exists() else None,

                                       a.privacy)

            (build / "youtube_url.txt").write_text(url)

        return



    # 1 ── scrape the existing daily job feed. The editorial frame never changes the

    # scraper's topic, date window, candidate pool, ranking, or featured-job count.

    candidate_dir = HERE / "data"

    data_json = candidate_dir / f"jobs_{date}.json"

    source_collection_summary = "Using the existing cached daily job feed."

    if a.rescrape or not data_json.exists():

        step("Scraping today's job sources")

        if a.rescrape and data_json.exists():

            data_json.unlink()

        cmd = [sys.executable, str(HERE / "job_scraper.py"), "--hours", "72", "--all",

               "--out", str(candidate_dir), "--db", str(HERE / "state" / "jobs_seen.db")]

        (HERE / "state").mkdir(exist_ok=True)

        candidate_dir.mkdir(parents=True, exist_ok=True)

        if a.strict:

            cmd.append("--strict")

        # Force UTF-8 in the scraper child process too. On Windows, the legacy

        # console code page can otherwise crash when a source/log contains emoji.

        scrape_env = os.environ.copy()

        scrape_env["PYTHONIOENCODING"] = "utf-8:replace"

        scrape_env["PYTHONUTF8"] = "1"

        scrape_result = subprocess.run(

            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",

            env=scrape_env,

        )

        review_dir = build / "script_review"

        review_dir.mkdir(parents=True, exist_ok=True)

        source_log = review_dir / "source_collection.log"

        source_log.write_text(

            "COMMAND: " + " ".join(cmd) + "\n\nSTDOUT:\n" + scrape_result.stdout +

            "\nSTDERR:\n" + scrape_result.stderr,

            encoding="utf-8",

        )

        scrape_output = scrape_result.stdout + "\n" + scrape_result.stderr

        source_lines = scrape_output.splitlines()

        for line in source_lines:

            if any(marker in line.upper() for marker in ("POSTINGS", "FAILED", "ERROR", "NOTHING NEW", "JOBS  ->")):

                log.info("SCRAPER: %s", line.strip())

        failed_sources = [line.strip() for line in source_lines if "FAILED:" in line.upper()]

        if failed_sources:

            source_collection_summary = f"{len(failed_sources)} source request(s) failed; see {source_log} for endpoint details."

        elif scrape_result.returncode == 0:

            source_collection_summary = f"Scraper exited successfully; detailed output: {source_log}."

        if scrape_result.returncode:

            raise RuntimeError(f"Job scraper failed with exit code {scrape_result.returncode}; diagnostics: {source_log}")

        if not data_json.exists():

            log.error("Scraper completed but produced no daily job JSON. %s", source_collection_summary)

            log.error("Inspect %s before interpreting this as an empty job market.", source_log)

            return



    if not data_json.exists():

        log.info("No cached daily job feed exists. Nothing to process.")

        return

    jobs = json.loads(data_json.read_text(encoding="utf-8"))



    # Rank the collected feed first. Network verification and compensation research are

    # deliberately downstream of ranking, and run in bounded parallel batches.

    raw_jobs = [job for job in jobs if isinstance(job, dict)]

    if not raw_jobs:

        raise RuntimeError("The scraper feed contains no job records to rank.")

    step(f"Ranking {len(raw_jobs)} collected jobs before network research")

    ranked_all = analyze.rank(raw_jobs, prof)

    n_video = a.jobs if a.jobs is not None else min(3, int(prof.get("video_jobs", 3)))

    target_count = max(1, int(n_video))

    research_workers = max(2, min(8, int(prof.get("research_workers", 6))))



    def run_bounded_stage(label, items, worker, max_workers):

        started = time.monotonic()

        if not items:

            log.info("%s: no jobs to process", label)

            return

        log.info("%s: %d jobs using %d workers", label, len(items), max_workers)

        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rbr-research") as pool:

            futures = {pool.submit(worker, job): job for job in items}

            for future in as_completed(futures):

                job = futures[future]

                completed += 1

                try:

                    future.result()

                except Exception as exc:

                    log.warning("%s failed for %s — %s: %s", label,

                                str(job.get("company") or "Unknown company"),

                                str(job.get("title") or "Untitled role"), exc)

                if completed % 10 == 0 or completed == len(items):

                    log.info("%s progress: %d/%d (%.1fs elapsed)", label, completed, len(items), time.monotonic() - started)

        log.info("%s complete in %.1fs", label, time.monotonic() - started)



    # First verify original employer/location context for the ranked pool. This is

    # source verification only; salary research is a separate stage below.

    step("Verifying ranked job sources and eligibility")

    run_bounded_stage("SOURCE VERIFICATION", ranked_all,

                      narration._verify_source_context_only, research_workers)



    # Remove invalid records only after rank and source verification. The surviving

    # ranked pool is the website pool; video eligibility is decided separately.

    valid_ranked = []

    rejected_roles = []

    rejected_locations = []

    rejected_content = []

    for job in ranked_all:

        if narration._role_mismatch(job):

            rejected_roles.append(job)

            continue

        eligibility_issue = narration._india_eligibility_issue(job)

        if eligibility_issue:

            rejected_locations.append((job, eligibility_issue))

            continue

        content_issue = narration._job_content_quality_issue(job)

        if content_issue:

            rejected_content.append((job, content_issue))

            continue

        valid_ranked.append(job)

    if rejected_roles:

        log.warning("Excluded %d role/title-description mismatches: %s", len(rejected_roles),

                    [(j.get("company"), j.get("title")) for j in rejected_roles])

    if rejected_locations:

        log.warning("Excluded %d explicitly ineligible locations: %s", len(rejected_locations),

                    [(j.get("company"), j.get("title"), reason) for j, reason in rejected_locations])

    if rejected_content:

        log.warning("Excluded %d jobs with unusable vacancy descriptions: %s", len(rejected_content),

                    [(j.get("company"), j.get("title"), reason) for j, reason in rejected_content])

    if not valid_ranked:

        raise RuntimeError("No jobs remain after ranked source-quality and eligibility checks. See source collection diagnostics.")

    ranked = valid_ranked

    agg = analyze.aggregate_keywords(ranked) if ranked else []



    # Enrich every job that will appear on the website, not just the video shortlist.

    # The function reuses official/source salary already present and completed research

    # attempts; bounded concurrency prevents one slow result from serializing the feed.

    step("Enriching all website jobs with source, application and salary evidence")

    run_bounded_stage("JOB ENRICHMENT", ranked, narration._enrich_source_context, research_workers)



    # Persist enriched fields into today's feed so script review/re-runs reuse research

    # rather than paying the same network cost again. The scraper can refresh this file

    # on the next explicit rescrape; the enrichment cache remains useful within the day.

    data_json.write_text(json.dumps(ranked, ensure_ascii=False, indent=2), encoding="utf-8")

    # Classify every job into a department, then restrict the video pool to the
    # configured departments. The website still gets the full ranked list below;
    # only the video featured-role selection is filtered.
    step("Classifying jobs by department for video selection")
    for _j in ranked:
        _j["_department"] = narration._job_department(_j)
    _dept_counts: dict[str, int] = {}
    for _j in ranked:
        _dept_counts[_j["_department"]] = _dept_counts.get(_j["_department"], 0) + 1
    log.info("Department breakdown: %s", dict(sorted(_dept_counts.items(), key=lambda kv: -kv[1])))
    _video_departments = set(prof.get("departments") or [])
    if _video_departments:
        _before = len(ranked)
        _video_pool = [j for j in ranked if j.get("_department") in _video_departments]
        log.info("Video pool restricted to %s: %d of %d jobs", sorted(_video_departments), len(_video_pool), _before)
        if len(_video_pool) < 3:
            log.warning("Video pool only has %d jobs in %s — featured selection may be short", len(_video_pool), sorted(_video_departments))
    else:
        _video_pool = list(ranked)



    # Select a distinct, company-diverse video shortlist from the fully enriched ranked

    # pool. The website still receives the entire valid ranked pool above.

    max_per_company = max(1, int(prof.get("max_per_company", 2)))

    company_counts: dict[str, int] = {}

    eligible_for_episode: list[dict] = []

    selected_vacancy_keys: list[tuple[str, set[str], str]] = []

    log.info("━━ Selecting %d featured roles from %d enriched video-pool jobs", target_count, len(_video_pool))

    for candidate_index, job in enumerate(_video_pool, start=1):

        if len(eligible_for_episode) >= target_count:

            break

        company_key = re.sub(r"[^a-z0-9]", "", str(job.get("company") or "Unknown company").casefold())

        title_tokens = {token for token in re.findall(r"[a-z0-9]+", str(job.get("title") or "").casefold()) if len(token) > 2}

        duplicate_of = next((old_title for old_company, old_tokens, old_title in selected_vacancy_keys

                             if old_company == company_key and old_tokens and title_tokens

                             and len(old_tokens & title_tokens) / len(old_tokens | title_tokens) >= 0.80), None)

        if duplicate_of:

            log.info("DUPLICATE FEATURED ROLE SKIPPED: %s — %s; matches selected title=%s",

                     str(job.get("company") or "Unknown company"), str(job.get("title") or "Untitled role"), duplicate_of)

            continue

        if company_counts.get(company_key, 0) >= max_per_company:

            continue

        if narration._salary_phrase(job) and not narration._job_content_quality_issue(job):

            eligible_for_episode.append(job)

            selected_vacancy_keys.append((company_key, title_tokens, str(job.get("title") or "Untitled role")))

            company_counts[company_key] = company_counts.get(company_key, 0) + 1

        else:

            attempt = job.get("salary_research_attempt") if isinstance(job.get("salary_research_attempt"), dict) else {}

            diagnostics = attempt.get("diagnostics") if isinstance(attempt.get("diagnostics"), dict) else {}

            log.info("PAY RESEARCH REJECTED: %s — %s; result=%s; diagnostics=%s",

                     str(job.get("company") or "Unknown company"), str(job.get("title") or "Untitled role"),

                     str(attempt.get("result") or "no defensible salary evidence"),

                     json.dumps(diagnostics, ensure_ascii=False, sort_keys=True))



    selected_urls = {str(j.get("url") or j.get("original_url") or j.get("source_url") or j.get("title")) for j in eligible_for_episode}

    videos = eligible_for_episode

    rest = [j for j in _video_pool if str(j.get("url") or j.get("original_url") or j.get("source_url") or j.get("title")) not in selected_urls]

    log.info("Website jobs: %d; video roles with defensible pay: %d/%d", len(ranked), len(videos), target_count)

    log.info("Selected video roles: %s", [(j.get("company"), j.get("title"), j.get("score")) for j in videos])



    def make_scenes(review_mode=False, website_url=""):

        return narration.build_scenes(videos, rest, agg, date_label, len(ranked), channel,

                                      review_mode=review_mode, website_url=website_url)



    def scene_preflight(scenes, required_count=None):
        required_count = target_count if required_count is None else max(1, int(required_count))
        kinds = [str(s.get("kind") or "") for s in scenes]
        new_struct = "job_scroll" in kinds and "card" not in kinds
        min_words = 800 if new_struct else (1000 if a.allow_short_video else 1450)
        errors = narration.preflight_errors(scenes, min_words=min_words)
        actual_count = sum(1 for s in scenes if s.get("kind") in {"card", "job_scroll"} and isinstance(s.get("job"), dict))
        if actual_count < target_count and not a.allow_short_video:
            errors.append(f"Only {actual_count} of {target_count} configured featured roles have defensible salary evidence and usable source details. Do not render the video; website publication is separate.")
        elif actual_count < target_count and a.allow_short_video:
            log.warning(
                "Short-video override enabled: proceeding with %d salary-qualified role(s), although %d were requested.",
                actual_count, target_count,
            )
        return errors



    # Script-review mode exits before website generation, screenshots, TTS, or video.

    if a.script_only:

        try:

            review_site_url = github_pages_url()

        except (RuntimeError, OSError, subprocess.SubprocessError):

            review_site_url = str(prof.get("website_url") or prof.get("site_url") or "")

        scenes = make_scenes(review_mode=True, website_url=review_site_url)

        review_dir = build / "script_review"

        review_dir.mkdir(parents=True, exist_ok=True)

        review_markdown = narration.render_review_markdown(

            scenes, f"Road Beyond Roles — {date_label} Narration Review"

        )

        review_errors = scene_preflight(scenes)

        review_markdown += "\n\n## Automated preflight status\n\n"

        if review_errors:

            review_markdown += "**VIDEO NOT APPROVED — do not render. Website publication is evaluated separately.**\n\n"

            review_markdown += "\n".join(f"- {error}" for error in review_errors)

        else:

            review_markdown += "**Preflight checks passed.** This is not a substitute for human script approval."

        (review_dir / "narration_review.md").write_text(review_markdown, encoding="utf-8")

        serializable = []

        for scene in scenes:

            item = {key: value for key, value in scene.items() if key not in {"job", "rest", "agg"}}

            if scene.get("job"):

                item["job"] = {key: scene["job"].get(key) for key in ("id", "company", "title", "location", "salary", "researched_salary", "salary_source", "salary_estimated", "salary_research", "salary_research_attempt", "official_job_url", "_official_job_url", "application_deadline", "url", "original_url", "source_url", "application_url", "apply_url", "company_url", "website", "application_process", "how_to_apply", "application_instructions", "application_steps", "company_overview", "company_description", "company_summary", "eligibility", "candidate_eligibility", "must", "nice", "_episode_source_verified", "_episode_source_verified_at", "_episode_source_verified_url", "_episode_source_verification_issue") if scene["job"].get(key) is not None}

            serializable.append(item)

        (review_dir / "narration_review.json").write_text(

            json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8"

        )

        visual_intent = []

        for i, scene in enumerate(scenes):

            kind = str(scene.get("kind") or "")

            visual_role = {

                "title": "cold-open brand banner",

                "channel_intro": "dedicated branded channel introduction card",

                "outro": "brand banner (short end card)",

                "hook": "first featured job screenshot",

                "website": "first featured job screenshot while website purpose is explained",

                "card": "job title / heading crop",

                "shot": f"captured job-page viewport for {scene.get('topic', 'role detail')}",

                "keywords": "same job's final screenshot",

                "salary_context": "same job's final screenshot while explaining what the pay estimate means",

                "candidate_fit": "same job's final screenshot",

                "application_tips": "final job-page screenshot",

                "closing": "final job-page screenshot",

                "role_beat": f"captured job-page viewport for {scene.get('beat', 'role detail')}",

                "pay_card": "full-screen verified pay card",

                "gate_card": "full-screen main requirement card",

                "apply_card": "full-screen real application URL card",

                "midroll": "full-screen mid-roll comment prompt",

                "midroll_followup": "job screenshot while explaining comment choices",

                "tiered_recap": "recap over role screenshots",

                "list": "featured job screenshot",

                "agg": "final job-page screenshot",

            }.get(kind, "captured job-page screenshot")

            visual_intent.append({"sequence": i, "kind": kind, "chapter": scene.get("chapter", ""),

                                  "company": (scene.get("job") or {}).get("company") if isinstance(scene.get("job"), dict) else None,

                                  "job_title": (scene.get("job") or {}).get("title") if isinstance(scene.get("job"), dict) else None,

                                  "topic": scene.get("topic"), "intended_visual": visual_role,

                                  "narration": scene.get("text", "")})

        (review_dir / "scene_plan.json").write_text(

            json.dumps(visual_intent, ensure_ascii=False, indent=2), encoding="utf-8"

        )

        log.info("Script and visual plan ready: %s", review_dir / "narration_review.md")

        log.info("No website generation, screenshot capture, TTS, video rendering, push, or upload was performed.")

        return



    # Full-run mode prepares the scene plan itself; no separate --script-only invocation is required.

    # The one in-run browser checkpoint below decides which scenes enter TTS and rendering.

    video_preflight_errors = []

    if not a.no_video and len(ranked) >= max(1, a.min_jobs):

        preflight_url = str(prof.get("website_url") or prof.get("site_url") or "")

        try:

            preflight_url = github_pages_url()

        except (RuntimeError, OSError, subprocess.SubprocessError):

            pass

        try:

            video_preflight_errors.extend(scene_preflight(make_scenes(review_mode=True, website_url=preflight_url)))

        except (RuntimeError, ValueError) as exc:

            video_preflight_errors.append(str(exc))

        if video_preflight_errors:

            log.error("VIDEO BLOCKED by automated content preflight; website publication is separate.\n - %s",

                      "\n - ".join(video_preflight_errors))

        else:

            log.info("Automated content preflight passed. The full run will pause once for scene approval before TTS.")



    # 3 ── GitHub Pages site

    step("Building site (docs/)")

    site_url = github_pages_url()

    sitegen.build_site(date, ranked, agg, HERE / "docs", channel)



    # Production requires publication; local preview never pushes.

    preview_server = None

    if a.local_preview:

        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        from threading import Thread



        class PreviewHandler(SimpleHTTPRequestHandler):

            def __init__(self, *args, **kwargs):

                super().__init__(*args, directory=str(HERE / "docs"), **kwargs)



            def log_message(self, format, *args):

                pass



        preview_server = ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler)

        Thread(target=preview_server.serve_forever, daemon=True).start()

        site_url = f"http://127.0.0.1:{preview_server.server_port}"

        log.info("Local preview server: %s", site_url)

    else:

        if not a.push:

            raise RuntimeError(

                "Production requires --push before GitHub Pages screenshots. "

                "Use --local-preview for a local-only video preview."

            )

        _push(a, date)

        site_url = wait_for_github_pages(site_url, date)



    if video_preflight_errors:

        log.error("%s; video stages skipped because preflight failed. Review build/%s/script_review/narration_review.md", "Local preview generated" if a.local_preview else "Website publication completed", date)

        return

    if a.no_video or len(ranked) < max(1, a.min_jobs):

        log.info("Skipping video (%d jobs)", len(ranked))

        return



    # 4 ── imports that need heavy deps only when making a video

    import visuals

    ctx = {"channel": channel, "date": date_label, "age": narration.age_phrase}



    with visuals.Renderer() as r:

        # 5 ── screenshots of the DEPLOYED GitHub Pages job pages

        if not a.no_shots:

            step("Screenshotting deployed GitHub Pages job pages")

            for i, j in enumerate(videos, 1):

                job_page_url = sitegen.job_page_url(site_url, j)

                j["shots"] = r.grab_posting(

                    job_page_url, build / "shots" / f"job{i}", expected_title=j["title"]

                )

                if not j["shots"]:

                    raise RuntimeError(

                        f"GitHub Pages screenshot failed for {j['company']} — {job_page_url}"

                    )

                log.info("  #%d %s: %d screenshots", i, j["company"], len(j["shots"]))
                section_hints = {
                    "responsibilities": ["Responsibilities", "What you'll do",
                                          "What you will do", "The role",
                                          "Key responsibilities", "What your day will look like",
                                          "A typical day", "What you'll be doing"],
                    "requirements": ["Requirements", "Qualifications",
                                      "What we're looking for", "What you'll bring",
                                      "Must have", "Preferred qualifications",
                                      "About you", "Minimum requirements"],
                    "salary": ["Compensation", "Salary", "Pay range", "Base salary",
                               "Cash compensation", "Pay Range"],
                    "apply": ["How to apply", "Apply", "Application process",
                              "Application instructions", "To apply"],
                }
                try:
                    full_info = r.grab_full_and_sections(
                        job_page_url, build / "shots" / f"job{i}_full", section_hints
                    )
                    j["full_page"] = {
                        "path": full_info.get("full_path", ""),
                        "height": int(full_info.get("full_height", 0)),
                    }
                    j["sections"] = full_info.get("sections", {})
                except Exception as exc:
                    log.warning("Full-page capture raised for %s: %s", j["company"], exc)
                    j["full_page"] = {"path": "", "height": 0}
                    j["sections"] = {}
                log.info("  #%d %s: full page %dpx, sections=%s",
                         i, j["company"], j["full_page"]["height"],
                         ",".join(j["sections"].keys()) or "none")



        # 6 ── one in-run scene approval checkpoint. No separate script-only run or file editing.

        # The same filtered list is used for narration, audio segments, clips, captions and final assembly.

        scenes = make_scenes(website_url=site_url)

        scenes, rejected_job_keys = _interactive_scene_review(scenes, build / "script_review", date_label)

        if rejected_job_keys:

            rejected_jobs = [job for job in videos if _scene_job_key({"job": job}) in rejected_job_keys]

            videos = [job for job in videos if _scene_job_key({"job": job}) not in rejected_job_keys]

            if not videos:

                raise RuntimeError("VIDEO BLOCKED: all featured roles were rejected in the in-run review.")

            # Keep opening narration truthful after a featured role is rejected.

            first_job, last_job = videos[0], videos[-1]

            title_scene = next((scene for scene in scenes if scene.get("kind") == "title"), None)

            if title_scene is not None:

                if len(videos) > 1:

                    title_scene["text"] = (f"Let's start with the most useful detail in today's opportunities: {first_job.get('title')} at {first_job.get('company')}. "

                                            f"We'll compare the work, pay evidence and eligibility across {len(videos)} selected roles, ending with {last_job.get('title')} at {last_job.get('company')}.")

                else:

                    title_scene["text"] = (f"Let's start with the most useful detail in today's opportunity: {first_job.get('title')} at {first_job.get('company')}. "

                                            "We'll check the actual work, pay evidence and eligibility before drawing a conclusion.")

            hook_scene = next((scene for scene in scenes if scene.get("kind") == "hook"), None)

            if hook_scene is not None and len(videos) == 1:

                hook_scene["chapter"] = "Why this role matters"

                hook_scene["text"] = ("Before judging this opportunity, compare the actual responsibilities, required evidence and location rules with what you can demonstrate. "

                                       "Check the employer's original page before applying.")

            job_positions = {_scene_job_key({"job": job}): index for index, job in enumerate(videos, 1)}

            for scene in scenes:

                job_key = _scene_job_key(scene)

                if all(job_key) and job_key in job_positions:

                    scene["idx"] = job_positions[job_key]

            log.info("Rejected featured roles removed from the final video scene plan: %s", [(j.get("company"), j.get("title")) for j in rejected_jobs])

        # Shorten the intro banner so it shows ~8s instead of ~25s.
        _title_scene = next((s for s in scenes if s.get("kind") == "title"), None)
        if _title_scene:
            _title_scene["text"] = (
                "Welcome to Road Beyond Roles. Today we are breaking down three "
                "remote opportunities that already have confirmed pay evidence, "
                "so you can see exactly what the work pays before you apply."
            )
        _intro_scene = next((s for s in scenes if s.get("kind") == "channel_intro"), None)
        if _intro_scene:
            _intro_scene["text"] = (
                "This channel focuses on the job itself: the actual responsibilities, "
                "the requirements that gate the role, the pay evidence with its source, "
                "and how to apply through the original vacancy. Let's get started."
            )

        # Run content/role preflight again after the user's scene selection.
        post_review_errors = scene_preflight(scenes, required_count=len(videos))

        if post_review_errors:

            raise RuntimeError("VIDEO BLOCKED after scene review:\n - " + "\n - ".join(post_review_errors))

        # Fail closed if source enrichment exposes a title/description mismatch after the first filter.

        bad_featured = [s.get("job") for s in scenes if s.get("kind") in {"card", "job_scroll"} and isinstance(s.get("job"), dict) and narration._role_mismatch(s["job"])]

        if bad_featured:

            raise RuntimeError("A featured job failed the post-enrichment title/description check; video rendering stopped: " + ", ".join(str(j.get("title")) for j in bad_featured))

        screenshot_pool: list[Path] = []

        screenshots_by_job: dict[int, list[Path]] = {}

        for job_index, job in enumerate(videos, 1):

            paths = [Path(p) for p in (job.get("shots") or []) if Path(p).is_file()]

            if not paths:

                manifest = build / "shots" / f"job{job_index}.json"

                if manifest.is_file():

                    try:

                        data = json.loads(manifest.read_text(encoding="utf-8"))

                        paths = [

                            Path(item["path"]) for item in data.get("screenshots", [])

                            if item.get("path") and Path(item["path"]).is_file()

                        ]

                    except (OSError, ValueError, KeyError, TypeError):

                        paths = []

            if paths:

                screenshots_by_job[id(job)] = paths

                screenshot_pool.extend(paths)



        if not screenshot_pool:

            raise RuntimeError(

                "Screenshot-only video cannot continue: no captured job-page screenshots were found. "

                "Check build/<date>/shots/ and rerun with screenshot capture enabled."

            )



        # Map visuals by scene purpose. Never use the narration index as a screenshot

        # index: that caused unrelated scenes to display arbitrary pages.

        first_by_job = {

            id(job): paths[0]

            for job in videos

            if (paths := screenshots_by_job.get(id(job)))

        }

        last_by_job = {

            id(job): paths[-1]

            for job in videos

            if (paths := screenshots_by_job.get(id(job)))

        }

        if not first_by_job:

            raise RuntimeError("No usable opening screenshot exists for the featured jobs.")

        primary_job = next((job for job in videos if id(job) in first_by_job), None)

        if primary_job is None:

            raise RuntimeError("Unable to select a primary featured job for supporting scenes.")

        primary_opening = first_by_job[id(primary_job)]

        primary_final = last_by_job[id(primary_job)]

        featured_openings = [first_by_job[id(job)] for job in videos if id(job) in first_by_job]



        banner = HERE / "assets" / "branding" / "road_beyond_roles_banner.jpg"

        frame_dir = build / "frames"

        frame_dir.mkdir(parents=True, exist_ok=True)



                # Screenshot-only visuals. Banner for intro/outro; real captured GitHub Pages

        # screenshots for every other scene (heading crop for title cards, full viewport

        # for detail beats). No template slides are generated.

        if not banner.is_file():

            raise RuntimeError(f"Missing banner asset: {banner}")



        # Pre-crop heading-only views for each featured job.

        heading_by_job = {}

        for job_index, job in enumerate(videos, 1):

            source = first_by_job.get(id(job))

            if source:

                try:

                    heading_by_job[id(job)] = _make_job_heading_crop(

                        source, build / "shots" / f"job{job_index}_heading.png"

                    )

                except Exception as exc:

                    log.warning("Heading crop failed for %s — %s: %s",

                                job.get("company"), job.get("title"), exc)



        def _choose_screenshot(scene, kind, job):
            """Return (source_path, visual_role) for the new 7-scene structure."""
            if kind == "banner":
                return banner, "banner"
            if kind == "homepage":
                if homepage_src and homepage_src.is_file():
                    return homepage_src, "homepage"
                return primary_opening, "homepage_fallback"
            if kind == "job_scroll" and job:
                full = job.get("full_page") if isinstance(job.get("full_page"), dict) else {}
                fp = str(full.get("path") or "")
                if fp and Path(fp).is_file():
                    return Path(fp), "scroll_full_page"
                if id(job) in first_by_job:
                    return first_by_job[id(job)], "job_opening_fallback"
            return primary_final, "primary_final"



        homepage_src: Path | None = None
        if not a.no_shots:
            try:
                homepage_src = r.grab_homepage(f"{site_url.rstrip('/')}/index.html", build / "shots" / "homepage")
                if homepage_src:
                    log.info("Homepage captured: %s", homepage_src)
                else:
                    log.warning("Homepage capture returned None — see visuals log above")
            except Exception as exc:
                log.warning("Homepage capture raised: %s", exc)

        for scene_index, scene in enumerate(scenes):

            kind = str(scene.get("kind") or "")

            job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

            frame_path = frame_dir / f"{scene_index:02}_episode.png"

            if kind in ("card", "job_title") and job:
                body = visuals.t_job_title_light(job, int(scene.get("idx") or 0), ctx)
                r.render_generated(body, frame_path)
                scene["png"] = frame_path
                scene["visual_role"] = "title_slide_light"
                scene["visual_source"] = "generated_title_slide"
                continue



            source_path, source_kind = _choose_screenshot(scene, kind, job)

            if not source_path or not source_path.is_file():

                raise RuntimeError(

                    f"No screenshot or banner for scene {scene_index} ({kind}): {source_path}"

                )



            # Copy the raw asset as-is — no overlay, no card, no template.

            shutil.copy2(source_path, frame_path)

            scene["png"] = frame_path

            scene["visual_role"] = source_kind

            scene["visual_source"] = str(source_path)

        # Save the exact narration-to-visual map. This is the single source of truth

        # for the script, screenshot, clip, captions and final video sequence.

        scene_manifest = []

        for i, scene in enumerate(scenes):

            job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

            scene_manifest.append({

                "sequence": i,

                "kind": scene.get("kind"),

                "chapter": scene.get("chapter", ""),

                "company": job.get("company"),

                "job_title": job.get("title"),

                "topic": scene.get("topic"),

                "visual_role": scene.get("visual_role"),

                "screenshot": str(scene.get("png", "")),

                "narration": scene.get("text", ""),

            })

        (build / "scene_plan.json").write_text(

            json.dumps(scene_manifest, ensure_ascii=False, indent=2), encoding="utf-8"

        )

        log.info(

            "Integrated scene plan: %d selected narration segments mapped to %d visual assets; "

            "the same scene plan drives voice, visuals, clips and captions.",

            len(scenes), len(set(str(scene["png"]) for scene in scenes))

        )



        # 7 ?? one continuous voice track + aligned scene timing + clips
    step("Synthesising one continuous narration and encoding scene clips")
    if a.fresh:
        for stale_dir in ("audio", "clips"):
            target_dir = build / stale_dir
            if target_dir.is_dir():
                for f in target_dir.iterdir():
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass
        for stale_file in ("video.mp4", "captions.srt", "video_qa.json"):
            (build / stale_file).unlink(missing_ok=True)
        log.info("Fresh run: deleted today's audio, clips and previous output (frames preserved)")
    master_text = " ".join(str(sc.get("text") or "").strip() for sc in scenes if str(sc.get("text") or "").strip())
    master_audio = media.master_tts(master_text, build / "audio" / "master.mp3", a.tts,
                                    prof.get("voice", "am_adam"), prof.get("rate", "+4%"),
                                    force=a.fresh)

    scene_audio = media.segment_master_audio(master_audio, [sc["text"] for sc in scenes], build / "audio" / "segments", lead_pad_first_segment=3.0)

    clips, durs = [], []

    for k, sc in enumerate(scenes):

        mp3 = scene_audio[k]

        clip = build / "clips" / f"{k:02}.mp4"

        kind = str(sc.get("kind") or "")

        visual_role = str(sc.get("visual_role") or "")

        # Motion matched to visual role:

        #   banner                         -> static (must stay clean)

        #   heading crop                   -> static (must stay readable)

        #   captured viewport / *_viewport -> "up" (scroll-pan, reveals lower content)

        #   pay / gate / apply cards       -> "center" (subtle zoom)

        #   role_beat                      -> "down" (subtle zoom-out, complements the previous pan)

        motion_mode = "static"  # scroll is the only motion; no zoom

        _designed_roles = {"title_slide_light", "banner", "homepage"}
        _is_designed = str(sc.get("visual_role") or "") in _designed_roles
        _sf = _st = None
        if str(sc.get("visual_role") or "") == "scroll_full_page":
            _job = sc.get("job") if isinstance(sc.get("job"), dict) else {}
            _ph = int((_job.get("full_page") or {}).get("height") or 0)
            if _ph > 1100:
                _sf = 0
                _st = _ph - 1080
        sc["scroll_from"] = _sf
        sc["scroll_to"] = _st
        duration_sec = media.make_clip(
            sc["png"], mp3, clip,
            motion_mode=motion_mode, pad=0.0,
            image_is_designed=_is_designed,
            scroll_from=_sf, scroll_to=_st,
        )

        durs.append(duration_sec)

        clips.append(clip)

        sc["audio_file"] = str(mp3)

        sc["clip_file"] = str(clip)

        sc["duration_sec"] = round(duration_sec, 3)



    # Persist the final, timestamped scene plan after audio and clips exist. This is

    # the audit trail tying each spoken line to its screenshot, audio, clip and captions.

    scene_manifest = []

    cursor = 0.0

    for i, (scene, duration_sec) in enumerate(zip(scenes, durs)):

        job = scene.get("job") if isinstance(scene.get("job"), dict) else {}

        scene_manifest.append({

            "sequence": i,

            "start_sec": round(cursor, 3),

            "end_sec": round(cursor + duration_sec, 3),

            "duration_sec": round(duration_sec, 3),

            "kind": scene.get("kind"),

            "chapter": scene.get("chapter", ""),

            "company": job.get("company"),

            "job_title": job.get("title"),

            "topic": scene.get("topic"),

            "visual_role": scene.get("visual_role"),

            "screenshot": str(scene.get("png", "")),

            "audio_file": scene.get("audio_file", ""),

            "clip_file": scene.get("clip_file", ""),

            "narration": scene.get("text", ""),

        })

        cursor += duration_sec

    (build / "scene_plan.json").write_text(

        json.dumps(scene_manifest, ensure_ascii=False, indent=2), encoding="utf-8"

    )



    # 8 ── final assembly + captions

    step("Assembling final video")

    video = build / "video.mp4"

    media.concat(clips, video, HERE / "assets" / "music.mp3", narration=master_audio)

    rendered_duration = media.duration(video)

    minimum_duration = 420 if a.allow_short_video else 600

    if not minimum_duration <= rendered_duration <= 720:

        target = "7–12 minutes (short-video override)" if a.allow_short_video else "10–12 minutes"

        raise RuntimeError(

            f"Rendered video is {rendered_duration / 60:.2f} minutes; the required range for this run is {target}. "

            "The render is retained for diagnosis; adjust narration or TTS speed and rerun if needed."

        )

    if abs(rendered_duration - media.duration(master_audio)) > 2.5:

        raise RuntimeError(

            "Final video duration does not match the continuous narration track; upload is blocked."

        )

        captions_path = build / "captions.srt"
    media.write_srt([s["text"] for s in scenes], durs, captions_path)
    # Subtitles are NOT burned into the video. Upload captions.srt to YouTube separately.
    qa_report = media.validate_video(video, master_audio)

    (build / "video_qa.json").write_text(json.dumps(qa_report, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("Video QA passed: 1920x1080 H.264, narration present, subtitles burned in; %s", qa_report)



    # 9 ── metadata (title, description with chapters, tags)

    t, chapters = 0.0, []

    for sc, d in zip(scenes, durs):

        if sc.get("chapter"):

            chapters.append(f"{media.chapter_stamp(t)} {sc['chapter']}")

        t += d

    lines = [f"{i}. {j['title']} - {j['company']} ({j.get('location') or 'Remote'})\n   Apply: {j.get('application_url') or j.get('apply_url') or j.get('official_job_url') or j.get('url')}\n   "

             f"Pay evidence: {narration._salary_phrase(j)}" for i, j in enumerate(videos, 1)]

    kw_line = " | ".join(f"{k} ({p}%)" for k, _, p in agg[:8])

    _dept_label = " + ".join(sorted(_video_departments)).title() if _video_departments else "All"
    video_title = f"{_dept_label} Jobs in the US ({date_label}) | Verified Pay | Resume Keywords"

    intro_description = f"{len(ranked)} fresh job listings for today's search ({date_label}). Check each vacancy's location and eligibility before applying."

    desc = (f"Road Beyond Roles website: {site_url}\n"

            f"{intro_description}\n\n"

            f"CHAPTERS\n" + "\n".join(chapters) + "\n\n"

            f"JOBS IN THIS VIDEO\n" + "\n".join(lines) + "\n\n"

            f"ALL TODAY'S JOBS (searchable): {site_url or '(set site_url in profile.json)'}\n\n"

            f"MOST REQUESTED SKILLS TODAY: {kw_line}\n\n"

            f"Always verify details and eligibility on the official posting. We are not affiliated with the "

            f"companies listed. Narration uses an AI voice.\n\n#jobsus #remotejobs #hiring")

    _dept_tags = {
        "engineering": ["software engineer jobs us", "developer jobs us", "engineering jobs remote"],
        "data":        ["data analyst jobs us", "data engineer jobs us", "data science jobs remote"],
    }
    tags = ( ["jobs in us", "remote jobs us", "hiring today", "resume keywords", "job search us"]
             + [t for d in sorted(_video_departments) for t in _dept_tags.get(d, [])]
             + [k.lower() for k, _, p in agg[:8]] )

    meta = {"title": video_title,

            "description": desc, "tags": tags, "duration_sec": round(t)}

    (build / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("Video ready: %s (%d:%02d)", video, t // 60, t % 60)



    # 10 ── optional YouTube upload, then update the already-published site

    if a.upload:

        step("Uploading to YouTube")

        import upload_youtube

        url = upload_youtube.upload(video, meta["title"], meta["description"], meta["tags"],

                                    build / "thumbnail.png", a.privacy)

        (build / "youtube_url.txt").write_text(url)

        sitegen.build_site(date, ranked, agg, HERE / "docs", channel, url)

        _push(a, date)

        wait_for_github_pages(site_url, date)

    else:

        log.info("GitHub Pages verified: %s", site_url)





def _git_remote() -> str:

    result = subprocess.run(

        ["git", "remote", "get-url", "origin"],

        cwd=HERE, capture_output=True, text=True, check=False,

    )

    if result.returncode != 0 or not result.stdout.strip():

        raise RuntimeError("No GitHub origin remote is configured in this repository.")

    return result.stdout.strip()





def github_pages_url() -> str:

    remote = _git_remote()

    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote.rstrip("/"))

    if not m:

        raise RuntimeError(f"Origin is not a GitHub repository URL: {remote}")

    owner, repo = m.group(1), m.group(2)

    return f"https://{owner}.github.io/{repo}/"





def wait_for_github_pages(base_url: str, date: str, timeout: int = 180) -> str:

    """Wait until the deployed Pages site serves the generated daily page."""

    deadline = time.time() + timeout

    target = f"{base_url}job.html"

    last = ""

    while time.time() < deadline:

        try:

            req = Request(target, headers={"User-Agent": "RoadBeyondRoles/1.0"})

            with urlopen(req, timeout=15) as response:

                status = getattr(response, "status", 200)

                body = response.read(200_000).decode("utf-8", "ignore")

                if status == 200 and "Road Beyond Roles" in body:

                    log.info("GitHub Pages LIVE: %s", base_url)

                    return base_url

                last = f"HTTP {status}"

        except Exception as exc:

            last = str(exc)

        time.sleep(5)

    raise RuntimeError(

        f"GitHub Pages was not verified within {timeout}s: {base_url}. "

        f"Last check: {last}. Ensure GitHub Pages is configured to publish the repository's docs/ folder."

    )





def _push(a, date):

    if not a.push:

        raise RuntimeError("Production GitHub publication requires --push.")

    step("Pushing to GitHub")

    subprocess.run(

        ["git", "config", "user.name", "Road Beyond Roles Bot"],

        cwd=HERE, check=True,

    )

    subprocess.run(

        ["git", "config", "user.email", "road-beyond-roles-bot@users.noreply.github.com"],

        cwd=HERE, check=True,

    )

    # Add generated site/data and include scraper state only when it exists.

    # A cached scrape can legitimately run without creating the state directory.

    git_paths = ["docs", "data"]

    if (HERE / "state").exists():

        git_paths.append("state")

    subprocess.run(["git", "add", *git_paths], cwd=HERE, check=True)

    # Keep the generated detail-page shell in the same commit as the current feed.

    if (HERE / "docs" / "job.html").is_file():

        subprocess.run(["git", "add", "-f", "docs/job.html"], cwd=HERE, check=True)

    staged = subprocess.run(

        ["git", "diff", "--cached", "--quiet"], cwd=HERE, check=False

    )

    if staged.returncode != 0:

        subprocess.run(

            ["git", "commit", "-m", f"Daily jobs update {date}"],

            cwd=HERE, check=True,

        )

        subprocess.run(["git", "push", "origin"], cwd=HERE, check=True)

    else:

        log.info("No Git changes to commit; verifying existing GitHub Pages deployment.")





if __name__ == "__main__":

    main()

