"""Reusable Road Beyond Roles educational-content toolkit.

Creates structured manifests and screenshot-ready scenes for resume, ATS,
assessment, interview, course, internship, apprenticeship, and weekly-value
content. It does not fetch or invent external facts.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

TEMPLATES = {
    "resume": ("Resume Improvement", "resume"),
    "ats": ("ATS / Resume Keywords", "ats"),
    "assessment": ("Assessment Practice", "assessment"),
    "interview": ("Interview Questions", "interview"),
    "career": ("Career Guide", "career"),
    "course": ("Career Course", "course"),
    "internship": ("Internship", "internship"),
    "apprenticeship": ("Apprenticeship", "apprenticeship"),
    "giveaway": ("Weekly Career Giveaway", "giveaway"),
}

def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("content JSON must contain an object")
    return data

def validate(data: dict[str, Any]) -> None:
    kind = data.get("content_type")
    if kind not in TEMPLATES:
        raise ValueError(f"unsupported content_type: {kind!r}")
    if not data.get("title"):
        raise ValueError("content title is required")
    if kind in {"assessment", "interview"} and not data.get("items"):
        raise ValueError(f"{kind} content requires an items list")

def _esc(s: Any) -> str:
    import html
    return html.escape(str(s))

def scene_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    validate(data)
    kind = data["content_type"]
    scenes: list[dict[str, Any]] = [{
        "kind": "generated",
        "chapter": "Intro",
        "title": data["title"],
        "kicker": TEMPLATES[kind][0],
        "text": data.get("intro") or f"Today we are covering {data['title']}.",
        "body": data.get("intro") or f"<h1>{_esc(data['title'])}</h1><p>{_esc(TEMPLATES[kind][0])}</p>",
    }]
    if kind in {"assessment", "interview"}:
        for i, item in enumerate(data["items"], 1):
            q = item.get("question", "")
            answer = item.get("answer", "")
            explanation = item.get("explanation", "")
            scenes.append({
                "kind": "generated", "chapter": f"{i}. {q[:55]}",
                "title": q, "kicker": f"Question {i}",
                "text": f"Question {i}. {q} " +
                        (f"The answer is {answer}. {explanation}" if answer else ""),
                "body": (
                    f"<div class='sub'>{_esc(data['title'])}</div>"
                    f"<h2>{_esc(q)}</h2>"
                    + (f"<h3>ANSWER</h3><p>{_esc(answer)}</p>" if answer else "")
                    + (f"<h3>EXPLANATION</h3><p>{_esc(explanation)}</p>" if explanation else "")
                ),
            })
    else:
        for section in data.get("sections", []):
            heading = section.get("heading", "Key point")
            body = section.get("body", "")
            scenes.append({
                "kind": "generated",
                "chapter": heading[:70],
                "title": heading,
                "kicker": TEMPLATES[kind][0],
                "text": section.get("narration") or f"{heading}. {body}",
                "body": f"<h2>{_esc(heading)}</h2><p>{_esc(body)}</p>",
            })
    scenes.append({
        "kind": "generated", "chapter": "Takeaway",
        "title": "Key Takeaway", "kicker": TEMPLATES[kind][0],
        "text": data.get("outro") or "Use these points to prepare more effectively.",
        "body": f"<h2>Key Takeaway</h2><p>{_esc(data.get('outro') or 'Use these points to prepare more effectively.')}</p>",
    })
    return scenes

def write_manifest(data: dict[str, Any], scenes: list[dict[str, Any]], out: Path) -> None:
    manifest = {
        "content_id": data.get("content_id") or re.sub(r"[^a-z0-9]+", "-", data["title"].lower()).strip("-"),
        "content_type": data["content_type"],
        "title": data["title"],
        "source_urls": data.get("source_urls", []),
        "evidence": data.get("evidence", []),
        "scenes": [{"sequence": i, "chapter": s["chapter"], "text": s["text"]} for i, s in enumerate(scenes)],
        "screenshot_only": True,
        "audio_mode": "single_master",
    }
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
