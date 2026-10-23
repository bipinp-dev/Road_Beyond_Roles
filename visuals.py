"""Playwright-based visuals: live-posting screenshots, slides and thumbnail."""
import base64
import html
import logging
import re
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

log = logging.getLogger("visuals")
e = html.escape
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BAD_TITLES = ("just a moment", "access denied", "attention required", "captcha",
              "403", "404", "not found", "robot", "blocked")
COOKIE_BTN = re.compile(r"^(accept( all)?( cookies)?|agree|i agree|got it|allow all|ok|okay|close)$", re.I)

TIER_LABEL = {"A": "Based in the US", "B": "Remote - Worldwide", "C": "Remote - verify location"}
TIER_COLOR = {"A": "#22c55e", "B": "#3b82f6", "C": "#f59e0b"}

CSS = """
*{box-sizing:border-box;margin:0}
body{width:100vw;height:100vh;overflow:hidden;color:#f8fafc;
 font-family:'Segoe UI','Noto Sans','DejaVu Sans',Roboto,Arial,sans-serif;
 background:radial-gradient(1200px 700px at 15% 10%,#1e3a8a 0%,#0f172a 55%,#020617 100%);padding:80px 100px}
.brand{position:absolute;left:100px;bottom:48px;font-size:26px;color:#94a3b8;letter-spacing:.5px}
.date{position:absolute;right:100px;bottom:48px;font-size:26px;color:#94a3b8}
h1{font-size:120px;line-height:1.05;font-weight:800}
h2{font-size:72px;line-height:1.1;font-weight:800;max-width:1500px}
h3{font-size:34px;letter-spacing:3px;color:#94a3b8;margin:34px 0 16px;font-weight:700}
.sub{font-size:44px;color:#cbd5e1;margin-top:18px}
.chip{display:inline-block;padding:12px 26px;border-radius:999px;font-size:34px;font-weight:600;margin:0 14px 14px 0;
 background:#1e293b;border:2px solid #334155}
.must{background:#14532d;border-color:#22c55e}.nice{background:#1e3a8a;border-color:#3b82f6}
.soft{background:#334155;border-color:#64748b;font-size:28px}
.num{font-size:150px;font-weight:900;color:#38bdf8;line-height:1}
.row{display:flex;gap:30px;align-items:center;font-size:36px;padding:14px 0;border-bottom:1px solid #1e293b}
.bar{height:34px;border-radius:8px;background:linear-gradient(90deg,#38bdf8,#818cf8)}
.shot{position:absolute;inset:0;background:#000 center top/contain no-repeat}
.lower{position:absolute;left:0;right:0;bottom:0;padding:34px 100px;background:linear-gradient(transparent,#020617ee 40%);}
.live{display:inline-block;background:#dc2626;padding:6px 18px;border-radius:8px;font-weight:800;font-size:26px;margin-right:18px}
"""


def page(body: str, extra_css: str = "") -> str:
    return f"<html><head><meta charset='utf-8'><style>{CSS}{extra_css}</style></head><body>{body}</body></html>"


def foot(channel, date):
    return f"<div class='brand'>{e(channel)}</div><div class='date'>{e(date)}</div>"


def chips(items, cls=""):
    return "".join(f"<span class='chip {cls}'>{e(i)}</span>" for i in items)


# ---------------------------------------------------------------- templates
def t_title(n, agg, ctx):
    skills = chips([k for k, _, _ in agg[:5]], "must")
    return page(
        f"<div style='margin-top:70px'><h3 style='color:#38bdf8'>ROAD BEYOND ROLES</h3>"
        f"<h1 style='font-size:100px'>Today's Job<br>Opportunities</h1>"
        f"<div class='sub'>Real listings · Resume tips · Skill-building resources</div></div>"
        f"<div style='margin-top:46px'>{skills}</div>"
        + foot(ctx["channel"], ctx["date"])
    )


def t_card(j, idx, ctx):
    meta = [TIER_LABEL[j["tier"]]]
    if j["tier"] == "A":
        meta.append(j["location"].split(";")[0][:40])
    if j["experience"]:
        meta.append(j["experience"])
    if j["salary"]:
        meta.append(j["salary"])
    return page(f"<div class='num'>#{idx}</div><h2>{e(j['title'])}</h2><div class='sub'>{e(j['company'])}</div>"
                f"<div style='margin-top:46px'>{chips(meta)}</div>"
                f"<div style='margin-top:10px'><span class='chip' style='border-color:{TIER_COLOR[j['tier']]}'>"
                f"Posted {e(ctx['age'](j['hours_old']))}</span></div>" + foot(ctx["channel"], ctx["date"]))


def t_shot(j, idx, data_uri, ctx):
    return page(f"<div class='shot' style='background-image:url({data_uri})'></div>"
                f"<div class='lower'><span class='live'>LIVE POSTING</span>"
                f"<span style='font-size:40px;font-weight:700'>#{idx} {e(j['company'])} - {e(j['title'])}</span></div>")


def t_keywords(j, idx, ctx):
    body = f"<div class='sub' style='margin:0'>#{idx} {e(j['company'])} - {e(j['title'])}</div>"
    body += "<h3>RESUME KEYWORDS - MUST HAVE</h3>" + chips(j["must"][:8], "must")
    if j["nice"]:
        body += "<h3>NICE TO HAVE</h3>" + chips(j["nice"][:5], "nice")
    if j["soft"]:
        body += "<h3>ALSO MENTION</h3>" + chips(j["soft"], "soft")
    return page(body + foot(ctx["channel"], ctx["date"]))


def t_list(rest, ctx):
    rows = "".join(f"<div class='row'><b style='color:#38bdf8;width:60px'>{i}</b><span style='flex:1'>"
                   f"{e(r['title'][:60])}</span><span style='color:#94a3b8'>{e(r['company'][:28])}</span></div>"
                   for i, r in enumerate(rest[:9], 1))
    return page(f"<h2 style='font-size:64px;margin-bottom:30px'>More Fresh Jobs Today</h2>{rows}"
                f"<div class='sub' style='font-size:32px'>All links on the page in the description</div>"
                + foot(ctx["channel"], ctx["date"]))


def t_agg(agg, ctx):
    mx = max([p for _, _, p in agg] + [1])
    rows = "".join(f"<div class='row'><span style='width:360px'>{e(k)}</span>"
                   f"<div style='flex:1'><div class='bar' style='width:{max(4, int(100 * p / mx))}%'></div></div>"
                   f"<span style='width:120px;text-align:right;color:#94a3b8'>{p}%</span></div>" for k, _, p in agg[:8])
    return page(f"<h2 style='font-size:68px;margin-bottom:30px'>Most Requested Skills Today</h2>{rows}"
                + foot(ctx["channel"], ctx["date"]))


def t_resources(ctx):
    body = (
        "<div style='margin-top:95px'><h2>Make Your Next Application Stronger</h2>"
        "<div class='row' style='margin-top:42px'><span style='color:#38bdf8;width:390px'>RESUME TIPS</span>"
        "<span>Present relevant experience clearly and honestly</span></div>"
        "<div class='row'><span style='color:#38bdf8;width:390px'>FREE COURSES</span>"
        "<span>Build a skill you keep seeing in target roles</span></div>"
        "<div class='row'><span style='color:#38bdf8;width:390px'>KEYWORDS</span>"
        "<span>Use accurate terms and support them with evidence</span></div></div>"
    )
    return page(body + foot(ctx["channel"], ctx["date"]))


def t_outro(ctx, featured=None):
    featured = featured or []
    names = "".join(
        f"<div class='row'><span style='flex:1'>{e(j.get('title', 'Role'))}</span>"
        f"<span style='color:#94a3b8'>{e(j.get('company', 'Employer'))}</span></div>"
        for j in featured[:4]
    )
    return page(
        f"<div style='margin-top:75px'><h3 style='color:#38bdf8'>ROAD BEYOND ROLES</h3>"
        f"<h2>More Jobs On Our Website</h2>{names}"
        f"<div class='sub' style='margin-top:34px'>Share this video with someone who needs it</div></div>"
        + foot(ctx["channel"], ctx["date"])
    )


def t_thumb(n, agg, ctx):
    css = "body{padding:50px 60px}h1{font-size:150px;color:#fde047}.t{font-size:62px;font-weight:800;margin-top:10px}"
    return page(f"<h1>{n} NEW JOBS</h1><div class='t'>APPLY FROM THE US - NO VISA NEEDED</div>"
                f"<div style='margin-top:40px'>{chips([k for k, _, _ in agg[:3]], 'must')}</div>"
                f"<div class='sub' style='position:absolute;bottom:40px'>{e(ctx['date'])}</div>", css)


def t_job_lower_third(screenshot: Path, job: dict, index: int) -> str:
    """Wrap a captured vacancy screenshot with the same stable role lower-third on every beat."""
    data_uri = "data:image/png;base64," + base64.b64encode(Path(screenshot).read_bytes()).decode()
    company = e(str(job.get("company") or "Employer"))
    title = e(str(job.get("title") or "Role"))
    location = e(str(job.get("location") or "Remote — verify eligibility"))
    pay = e(str(job.get("salary") or job.get("researched_salary") or
                ((job.get("salary_research") or {}).get("range") if isinstance(job.get("salary_research"), dict) else "Pay evidence in narration")))
    body = (
        f"<div class='shot' style='background-image:url({data_uri});background-size:contain;background-color:#0b1220'></div>"
        "<div style='position:absolute;left:0;right:0;bottom:0;padding:28px 72px 34px;"
        "background:linear-gradient(transparent,#020617f5 24%);display:flex;align-items:flex-end;gap:36px'>"
        f"<div style='min-width:90px;font-size:50px;font-weight:900;color:#38bdf8'>#{index}</div>"
        f"<div style='flex:1'><div style='font-size:25px;color:#93c5fd;font-weight:800'>{company}</div>"
        f"<div style='font-size:36px;line-height:1.12;font-weight:800;margin-top:4px'>{title}</div>"
        f"<div style='font-size:22px;color:#cbd5e1;margin-top:8px'>{location}</div></div>"
        f"<div style='max-width:360px;font-size:27px;font-weight:800;color:#fef08a;text-align:right'>{pay}</div></div>"
    )
    return body


def t_job_title_light(job: dict, idx: int, ctx: dict) -> str:
    """Designed title card: white background, blue bold title, black company, gray meta."""
    e_ = html.escape
    company = e_(str(job.get("company") or "Employer"))
    title = e_(str(job.get("title") or "Open role"))
    location = e_(str(job.get("location") or ""))
    research = job.get("salary_research") if isinstance(job.get("salary_research"), dict) else {}
    salary = e_(str(research.get("range") or job.get("salary") or ""))
    period = e_(str(research.get("period") or ""))

    loc_html = f'<div style="font-size:42px;color:#475569;margin-top:32px;font-weight:500">{location}</div>' if location else ""
    pay_html = ""
    if salary:
        pay_html = f'<div style="font-size:44px;color:#0f172a;margin-top:24px;font-weight:700">{salary}'
        if period:
            pay_html += f' <span style="color:#64748b;font-weight:400">· {period}</span>'
        pay_html += "</div>"

    return f"""<html><head><meta charset="utf-8"><style>
* {{ margin:0; box-sizing:border-box; }}
html,body {{ background:#ffffff; width:100vw; height:100vh; font-family:'Segoe UI','Noto Sans',sans-serif; overflow:hidden; }}
</style></head><body>
<div style="position:absolute;inset:0;padding:120px 160px;display:flex;flex-direction:column;justify-content:center;">
  <div style="font-size:32px;color:#2563eb;font-weight:800;letter-spacing:10px">ROLE {idx:02d}</div>
  <div style="font-size:108px;color:#1e40af;font-weight:900;line-height:1.05;margin-top:48px;letter-spacing:-2px">{title}</div>
  <div style="font-size:60px;color:#0f172a;font-weight:700;margin-top:40px">{company}</div>
  {loc_html}
  {pay_html}
  <div style="position:absolute;left:160px;bottom:80px;font-size:26px;color:#94a3b8;letter-spacing:5px;font-weight:600">ROAD BEYOND ROLES</div>
</div></body></html>"""


def t_channel_intro(ctx: dict) -> str:
    """Render a brief branded channel introduction, distinct from the cold-open banner."""
    return page(
        "<div style='margin-top:105px'><div style='font-size:30px;letter-spacing:6px;color:#38bdf8;font-weight:900'>ROAD BEYOND ROLES</div>"
        "<h1 style='font-size:82px;line-height:1.05;margin-top:35px'>Real jobs.<br>Clear requirements.<br>Practical next steps.</h1>"
        "<div class='sub' style='font-size:31px;margin-top:28px'>Pay evidence · Eligibility · How to apply</div></div>"
        + foot(ctx["channel"], ctx["date"])
    )


def t_editorial_full_card(scene: dict, ctx: dict) -> str:
    """Three allowed full-screen card types plus the mid-roll prompt."""
    kind = str(scene.get("kind") or "")
    job = scene.get("job") if isinstance(scene.get("job"), dict) else {}
    company = e(str(job.get("company") or "Road Beyond Roles"))
    title = e(str(job.get("title") or scene.get("chapter") or "Road Beyond Roles"))
    raw = str(scene.get("card_text") or "")
    safe = e(raw)
    if kind == "pay_card":
        heading, eyebrow, color = "PAY EVIDENCE", f"{company} · {title}", "#fef08a"
        body_text = safe
        sub = "Check the payment unit and source before comparing rates."
    elif kind == "gate_card":
        heading, eyebrow, color = "THE REQUIREMENT THAT GATES YOU", f"{company} · {title}", "#93c5fd"
        body_text = safe
        sub = "Read the full official requirements before applying."
    elif kind == "apply_card":
        heading, eyebrow, color = "APPLY THROUGH THE REAL SOURCE", f"{company} · {title}", "#86efac"
        body_text = safe
        sub = "Check country eligibility; never pay for guaranteed selection."
    else:
        heading, eyebrow, color = "QUICK QUESTION", "ROAD BEYOND ROLES", "#fef08a"
        body_text = safe
        sub = "Put your answer in the comments."
    return (
        "<div style='position:absolute;inset:0;padding:110px 130px;background:radial-gradient(1100px 650px at 15% 10%,#1e3a8a,#0f172a 55%,#020617);display:flex;flex-direction:column;justify-content:center'>"
        f"<div style='font-size:28px;letter-spacing:4px;color:#94a3b8;font-weight:800'>{eyebrow}</div>"
        f"<div style='font-size:64px;line-height:1.08;font-weight:900;margin-top:26px;color:{color}'>{heading}</div>"
        f"<div style='font-size:54px;line-height:1.18;font-weight:800;margin-top:45px;overflow-wrap:anywhere'>{body_text}</div>"
        f"<div style='font-size:27px;color:#cbd5e1;margin-top:45px'>{e(sub)}</div>"
        f"<div style='position:absolute;left:130px;bottom:46px;font-size:24px;color:#94a3b8'>ROAD BEYOND ROLES</div>"
        "</div>"
    )

def t_narration_card(scene: dict, ctx: dict) -> str:
    """Readable branded slide for narration beats that should not show tiny webpage text."""
    kind = str(scene.get("kind") or "")
    beat = str(scene.get("beat") or "").casefold()
    job = scene.get("job") if isinstance(scene.get("job"), dict) else {}
    company = str(job.get("company") or "Road Beyond Roles")
    title = str(job.get("title") or "Today's opportunities")
    headings = {
        "hook": "WHY THESE ROLES MATTER",
        "website": "FIND THE ORIGINAL LISTING",
        "role_beat": {
            "skip": "WHO SHOULD SKIP IT",
            "opportunity": "THE WORK TO EVALUATE",
            "verdict": "EDITORIAL VERDICT",
            "transition": "NEXT ROLE",
            "loop_payoff": "THE KEY TAKEAWAY",
        }.get(beat, "ROLE BREAKDOWN"),
        "candidate_fit": "WHO SHOULD CONSIDER THIS ROLE",
        "salary_context": "UNDERSTAND THE PAY EVIDENCE",
        "application_tips": "HOW TO PREPARE YOUR APPLICATION",
        "closing": "BEFORE YOU APPLY",
        "tiered_recap": "QUICK RECAP",
        "midroll_followup": "YOUR NEXT STEP",
        "keywords": "SKILLS TO SHOW",
        "resources": "CAREER RESOURCES",
        "agg": "SKILLS IN DEMAND",
        "list": "MORE JOBS ON THE WEBSITE",
    }
    heading = headings.get(kind, "ROAD BEYOND ROLES")
    raw = str(scene.get("card_text") or scene.get("visual_summary") or scene.get("summary") or scene.get("text") or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    # The slide is a visual summary; the complete, approved wording remains in narration.
    if len(raw) > 245:
        boundary = max(raw.rfind(". ", 0, 245), raw.rfind("; ", 0, 245), raw.rfind(", ", 0, 245))
        cut = boundary if boundary >= 130 else raw.rfind(" ", 0, 242)
        raw = raw[:cut].rstrip(" ,;:") + "…" if cut > 0 else raw[:242].rstrip() + "…"
    safe_body = e(raw)
    safe_company = e(company)
    safe_title = e(title)
    subtitle = e(f"{company} · {title}" if job else f"{ctx.get('channel', 'Road Beyond Roles')} · {ctx.get('date', '')}")
    return page(
        "<div style='position:absolute;inset:0;padding:92px 120px 110px;"
        "background:radial-gradient(1100px 650px at 15% 10%,#1e3a8a,#0f172a 55%,#020617);"
        "display:flex;flex-direction:column;justify-content:center;overflow:hidden'>"
        f"<div style='font-size:27px;letter-spacing:4px;color:#38bdf8;font-weight:900'>{e(heading)}</div>"
        f"<div style='font-size:25px;color:#94a3b8;font-weight:700;margin-top:20px'>{subtitle}</div>"
        f"<div style='font-size:56px;line-height:1.12;font-weight:850;color:#f8fafc;margin-top:36px;"
        f"max-height:430px;overflow:hidden;overflow-wrap:anywhere'>{safe_body}</div>"
        f"<div style='position:absolute;left:120px;right:120px;bottom:44px;display:flex;justify-content:space-between;"
        f"font-size:22px;color:#94a3b8'><span>ROAD BEYOND ROLES</span><span>{e(str(ctx.get('date', '')))}</span></div>"
        "</div>"
    )


# ---------------------------------------------------------------- renderer
class Renderer:
    def __enter__(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        return self

    def __exit__(self, *a):
        self.browser.close()
        self.pw.stop()

    def png(self, html_str, path, w=1920, h=1080):
        pg = self.browser.new_page(viewport={"width": w, "height": h})
        pg.set_content(html_str, wait_until="load")
        pg.screenshot(path=str(path))
        pg.close()

    def grab_posting(self, url, prefix: Path, expected_title: str | None = None) -> list[str]:
        """Capture distinct page viewports and write an accurate screenshot manifest.

        Captures only publicly accessible pages; this does not bypass access controls.
        Scrolls through the full page, allowing lazy-loaded content to appear, then
        records each screenshot's actual scroll position and page/viewport dimensions.
        """
        import hashlib
        import math

        out: list[str] = []
        records: list[dict] = []
        prefix.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = prefix.with_suffix(".json")
        ctx = self.browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=UA, locale="en-IN"
        )
        pg = ctx.new_page()
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else 0

            # GitHub Pages may serve its HTML shell before client-side data renders.
            expected = (expected_title or "").strip().casefold()
            deadline = time.monotonic() + (15 if expected else 3)
            body_text = ""
            while True:
                try:
                    body_text = pg.locator("body").inner_text(timeout=5000).casefold()
                except Exception:
                    body_text = ""
                if expected and expected in body_text:
                    break
                if time.monotonic() >= deadline:
                    break
                pg.wait_for_timeout(500)

            title = (pg.title() or "").casefold()
            if expected and expected not in body_text:
                log.warning(
                    "Job title did not render: expected=%r, page_title=%r, status=%s, "
                    "body_excerpt=%r, url=%s",
                    expected_title, title, status, body_text[:500], url,
                )
                return []
            if status in {401, 403, 404, 429} or any(
                bad in title or bad in body_text[:5000] for bad in BAD_TITLES
            ):
                log.warning("Blocked/error page (%s), skipping screenshots: %s", status, url)
                return []

            # Hide common consent overlays without attempting to defeat protection.
            pg.add_style_tag(content="""
                [id*='cookie' i],[class*='cookie' i],[id*='consent' i],[class*='consent' i],
                [role='dialog'],[aria-modal='true'] { max-height:0!important; overflow:hidden!important; }
            """)
            try:
                pg.get_by_role("button", name=COOKIE_BTN).first.click(timeout=1200)
                pg.wait_for_timeout(300)
            except Exception:
                pass

            # Walk the page in small increments first so lazy-loaded sections can load.
            # Re-measure height while scrolling because pages often grow as content loads.
            viewport = pg.evaluate("({width: window.innerWidth, height: window.innerHeight})")
            viewport_h = max(1, int(viewport["height"]))
            settle_step = max(350, int(viewport_h * 0.65))
            previous_height = 0
            stable_rounds = 0
            y = 0
            for _ in range(80):
                pg.evaluate("(pos) => window.scrollTo(0, pos)", y)
                pg.wait_for_timeout(350)
                height = int(pg.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
                if height == previous_height:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                previous_height = height
                bottom = max(0, height - viewport_h)
                if y >= bottom and stable_rounds >= 2:
                    break
                y = min(y + settle_step, bottom)
                if y >= bottom:
                    pg.wait_for_timeout(450)
                    latest = int(pg.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
                    y = min(y + settle_step, max(0, latest - viewport_h))

            # Re-read final dimensions, then choose enough positions to cover the full
            # page. A cap protects against runaway pages; spacing expands to retain coverage.
            page_size = pg.evaluate("({width: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth), height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)})")
            total_h = max(viewport_h, int(page_size["height"]))
            max_shots = 5
            bottom = max(0, total_h - viewport_h)
            if bottom == 0:
                positions = [0]
            else:
                count = min(max_shots, max(2, math.ceil(bottom / max(1, int(viewport_h * 0.68))) + 1))
                interval = bottom / (count - 1)
                positions = sorted({int(round(i * interval)) for i in range(count)} | {bottom})

            seen: set[str] = set()
            for requested_y in positions:
                pg.evaluate("(pos) => window.scrollTo(0, pos)", requested_y)
                pg.wait_for_timeout(450)
                # Give common lazy-loading pages one chance to settle and refresh dimensions.
                actual_y = int(pg.evaluate("window.scrollY"))
                current_h = int(pg.evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"))
                actual_y = min(actual_y, max(0, current_h - viewport_h))
                png = pg.screenshot(full_page=False, animations="disabled")
                digest = hashlib.sha1(png).hexdigest()
                if digest in seen:
                    log.debug("Skipping duplicate viewport at scroll=%d for %s", actual_y, url)
                    continue
                seen.add(digest)
                image_path = prefix.with_name(f"{prefix.name}_{len(out):02}.png")
                image_path.write_bytes(png)
                out.append(str(image_path))
                records.append({
                    "sequence": len(records),
                    "path": str(image_path),
                    "scroll_position": actual_y,
                    "viewport_width": int(viewport["width"]),
                    "viewport_height": viewport_h,
                    "page_width": int(page_size["width"]),
                    "page_height": total_h,
                    "sha1": digest,
                })

            if not out:
                log.warning("No distinct screenshots captured for %s", url)
                return []

            manifest = {
                "url": url,
                "status": status,
                "page_title": pg.title() or "",
                "expected_title": expected_title or "",
                "viewport": {"width": int(viewport["width"]), "height": viewport_h},
                "page": {"width": int(page_size["width"]), "height": total_h},
                "screenshot_count": len(records),
                "capture_strategy": "adaptive_full_page_viewport_sequence",
                "screenshots": records,
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info(
                "Captured %d distinct screenshots across %dpx page (%s): %s",
                len(out), total_h, status, url,
            )
        except Exception as ex:
            log.warning("Screenshot failed for %s: %s", url, ex)
        finally:
            ctx.close()
        return out

    def grab_homepage(self, url: str, out_dir: Path) -> Path | None:
        """Capture the site homepage with a long wait for client-rendered content."""
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "homepage_00.png"
        ctx = self.browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=UA, locale="en-IN"
        )
        pg = ctx.new_page()
        try:
            resp = pg.goto(url, wait_until="networkidle", timeout=25000)
            status = resp.status if resp else 0
            pg.wait_for_timeout(2500)
            try:
                body = pg.locator("body").inner_text(timeout=5000)
            except Exception:
                body = ""
            log.info("Homepage %s: status=%s body_len=%d", url, status, len(body))
            png = pg.screenshot(full_page=False, animations="disabled")
            if len(png) < 30_000:
                log.warning("Homepage screenshot too small (%d bytes) — likely blank", len(png))
                return None
            target.write_bytes(png)
            return target
        except Exception as exc:
            log.warning("Homepage capture failed for %s: %s", url, exc)
            return None
        finally:
            ctx.close()

    def grab_section_screenshots(self, url: str, prefix: Path,
                                  sections: dict[str, list[str]]) -> dict[str, str]:
        """Scroll to each section heading and screenshot that section.

        Returns {section_name: png_path} only for sections actually found.
        """
        out: dict[str, str] = {}
        ctx = self.browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=UA, locale="en-IN"
        )
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(2500)
            pg.add_style_tag(content="""
                [id*='cookie' i],[class*='cookie' i],[id*='consent' i],[class*='consent' i],
                [role='dialog'],[aria-modal='true'] { max-height:0!important; overflow:hidden!important; }
            """)
            for section_name, variants in sections.items():
                found_y = None
                for variant in variants:
                    for tag in ("h1", "h2", "h3", "h4", "strong"):
                        try:
                            loc = pg.locator(tag).filter(has_text=variant).first
                            if loc.count() > 0:
                                box = loc.bounding_box(timeout=1200)
                                if box:
                                    page_y = pg.evaluate("() => window.scrollY")
                                    found_y = max(0, int(box["y"] + page_y - 80))
                                    break
                        except Exception:
                            pass
                    if found_y is not None:
                        break
                if found_y is None:
                    log.info("Section '%s' not found on %s", section_name, url)
                    continue
                pg.evaluate("(y) => window.scrollTo(0, y)", found_y)
                pg.wait_for_timeout(600)
                png = pg.screenshot(full_page=False, animations="disabled")
                path = prefix.with_name(f"{prefix.name}_{section_name}.png")
                path.write_bytes(png)
                out[section_name] = str(path)
                log.info("Section '%s' captured at y=%d", section_name, found_y)
        except Exception as exc:
            log.warning("Section capture failed for %s: %s", url, exc)
        finally:
            ctx.close()
        return out


    def grab_full_and_sections(self, url: str, prefix: Path,
                                 section_hints: dict[str, list[str]]) -> dict:
        """One navigation. Full-page PNG + section Y positions on the page."""
        out = {"full_path": "", "full_height": 0, "sections": {}}
        ctx = self.browser.new_context(
            viewport={"width": 1920, "height": 1080}, user_agent=UA, locale="en-IN"
        )
        pg = ctx.new_page()
        try:
            pg.goto(url, wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(2200)
            pg.add_style_tag(content="[role='dialog'],[aria-modal='true'],"
                                    "[id*='cookie' i],[class*='cookie' i],"
                                    "[id*='consent' i],[class*='consent' i] "
                                    "{display:none!important;max-height:0!important}")
            page_h = int(pg.evaluate(
                "Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"
            ))
            full_png = pg.screenshot(full_page=True, animations="disabled")
            prefix.parent.mkdir(parents=True, exist_ok=True)
            full_path = prefix.with_name(f"{prefix.name}_full.png")
            full_path.write_bytes(full_png)
            out["full_path"] = str(full_path)
            out["full_height"] = min(page_h, 5500)
            log.info("Full page: %s (%dpx)", full_path.name, page_h)

            for name, variants in section_hints.items():
                try:
                    found_y = pg.evaluate("""(variants) => {
                        const lower = variants.map(v => v.toLowerCase());
                        const tags = ['h1','h2','h3','h4','h5','h6','strong','b','p'];
                        const els = [];
                        for (const tag of tags) {
                            els.push(...document.querySelectorAll(tag));
                        }
                        // Pass 1: exact/near-start match on short elements
                        for (const el of els) {
                            const raw = (el.textContent || '').trim();
                            if (!raw || raw.length > 120) continue;
                            const lc = raw.toLowerCase();
                            for (const v of lower) {
                                if (lc === v || lc.startsWith(v) ||
                                    (lc.includes(v) && lc.indexOf(v) < 20)) {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.height > 0) {
                                        return Math.max(0, Math.round(rect.top + window.scrollY - 100));
                                    }
                                }
                            }
                        }
                        // Pass 2: relaxed
                        for (const el of els) {
                            const raw = (el.textContent || '').trim();
                            if (!raw || raw.length > 200) continue;
                            const lc = raw.toLowerCase();
                            for (const v of lower) {
                                if (lc.includes(v)) {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.height > 0) {
                                        return Math.max(0, Math.round(rect.top + window.scrollY - 100));
                                    }
                                }
                            }
                        }
                        return null;
                    }""", variants)
                except Exception as exc:
                    log.warning("Section JS eval failed for %s: %s", name, exc)
                    found_y = None
                if found_y is not None:
                    out["sections"][name] = int(found_y)
                    log.info("  Section '%s' at y=%d", name, found_y)
                else:
                    log.info("  Section '%s' not found", name)
        except Exception as ex:
            log.warning("grab_full_and_sections failed: %s", ex)
        finally:
            ctx.close()
        return out


    def render_generated(self, body: str, path: Path, extra_css: str = "",
                         w: int = 1920, h: int = 1080):
        """Render original educational content as a screenshot."""
        self.png(page(body, extra_css), path, w, h)


def render_scene(r: Renderer, sc: dict, path: Path, ctx: dict, n_jobs: int, agg):
    k = sc["kind"]
    if k == "title":
        h = t_title(n_jobs, agg, ctx)
    elif k == "card":
        h = t_card(sc["job"], sc["idx"], ctx)
    elif k == "shot":
        uri = "data:image/png;base64," + base64.b64encode(Path(sc["shot"]).read_bytes()).decode()
        h = t_shot(sc["job"], sc["idx"], uri, ctx)
    elif k == "keywords":
        h = t_keywords(sc["job"], sc["idx"], ctx)
    elif k == "list":
        h = t_list(sc["rest"], ctx)
    elif k == "agg":
        h = t_agg(sc["agg"], ctx)
    elif k == "resources":
        h = t_resources(ctx)
    elif k == "outro":
        h = t_outro(ctx, sc.get("featured"))
    else:
        raise ValueError(f"Unsupported narration scene kind: {k}")
    r.png(h, path)


def render_thumbnail(r: Renderer, path: Path, n_jobs: int, agg, ctx):
    r.png(t_thumb(n_jobs, agg, ctx), path, 1280, 720)
