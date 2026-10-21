from pathlib import Path

v = Path("visuals.py").read_text(encoding="utf-8")

print("=== visuals.py ===")
for name, ok in {
    "grab_homepage defined": "def grab_homepage(self" in v,
    "grab_section_screenshots defined": "def grab_section_screenshots(self" in v,
    "grab_section uses networkidle": 'wait_until="networkidle"' in v,
    "grab_homepage uses networkidle": 'wait_until="networkidle"' in v,
    "grab_section waits 2500ms": "pg.wait_for_timeout(2500)" in v,
}.items():
    print(f"  {'OK  ' if ok else 'MISS'} {name}")

r = Path("run_daily.py").read_text(encoding="utf-8")

print("\n=== run_daily.py ===")
for name, ok in {
    "calls grab_homepage": "r.grab_homepage(" in r,
    "calls grab_section_screenshots": "r.grab_section_screenshots(" in r,
    "homepage_src variable": "homepage_src: Path | None = None" in r,
    "_choose uses homepage_src": "if homepage_src and homepage_src.is_file():" in r,
    "_choose uses job sections dict": 'if topic and topic in sections:' in r,
}.items():
    print(f"  {'OK  ' if ok else 'MISS'} {name}")
