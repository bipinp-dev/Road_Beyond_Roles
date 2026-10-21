from pathlib import Path

print("=== media.py checks ===")
m = Path("media.py").read_text(encoding="utf-8")
checks = {
    "zoom smoothstep (60fps)": "min(on/max(1,{dur:.3f}*60),1)" in m,
    "input 60fps": '"-framerate", "60"' in m,
    "output 60fps": '"-r", "60", "-g", "60"' in m,
    "per-clip audio fades": "afade=t=in:st=0" in m,
    "segment_master_audio lead_pad param": "lead_pad_first_segment" in m,
    "segment pad only first clip": "if i == 0 and lead_pad_first_segment > 0" in m,
    "master_tts no longer pads": "return tts(text, out.with_suffix(\".mp3\"), backend, voice, rate, force=force)" in m,
}
for name, present in checks.items():
    print(f"  {'OK ' if present else 'MISSING'}  {name}")

print("\n=== media.py current zoom block ===")
import re
z = re.search(r"progress = .*?\n.{0,1200}?fps=\d+", m, re.DOTALL)
if z:
    print(z.group(0)[:1200])
else:
    print("(zoom block not found)")

print("\n=== media.py current audio chain block ===")
a = re.search(r"audio_chain = .*?apad=pad_dur=\{pad_value\}", m, re.DOTALL)
if a:
    print(a.group(0))
else:
    print("(audio chain not found)")

print("\n=== media.py segment_master_audio signature ===")
s = re.search(r"def segment_master_audio\([^)]+\)", m)
print(s.group(0) if s else "(not found)")

print("\n=== run_daily.py checks ===")
r = Path("run_daily.py").read_text(encoding="utf-8")
rchecks = {
    "routing: banner for title+closing": 'if kind in {"title", "closing"}:' in r and 'return banner, "banner"' in r,
    "routing: homepage for channel_intro+list": 'if kind in {"channel_intro", "list"}:' in r,
    "routing: no card heading crop": 'if kind == "card" and job and id(job) in heading_by_job:' not in r,
    "motion: all center via comment": "# Every scene uses the same smooth center zoom" in r,
    "homepage capture block": 'homepage_src: Path | None = None' in r,
    "title slide render": 'visuals.t_job_title_light(job' in r,
    "captions_path defined before write_srt": 'captions_path = build / "captions.srt"\n    media.write_srt' in r,
    "segment lead_pad_first_segment=3.0": "lead_pad_first_segment=3.0" in r,
}
for name, present in rchecks.items():
    print(f"  {'OK ' if present else 'MISSING'}  {name}")

print("\n=== run_daily.py current _choose_screenshot ===")
c = re.search(r"def _choose_screenshot\(scene, kind, job\):.*?return primary_final, \"primary_final\"", r, re.DOTALL)
if c:
    print(c.group(0)[:1500])
else:
    print("(not found)")

print("\n=== run_daily.py current motion-mode selection ===")
mm = re.search(r"visual_role = str\(sc\.get\(\"visual_role\"\) or \"\"\).*?motion_mode = \"center\"", r, re.DOTALL)
if mm:
    print(mm.group(0)[:800])
else:
    print("(not found)")

print("\n=== run_daily.py current write_srt line ===")
for i, line in enumerate(r.split("\n"), 1):
    if "write_srt" in line or ("captions_path" in line and "=" in line):
        print(f"  L{i}: {line.strip()}")

print("\n=== run_daily.py current segment_master_audio call ===")
for i, line in enumerate(r.split("\n"), 1):
    if "segment_master_audio(" in line and "def " not in line:
        print(f"  L{i}: {line.strip()}")
