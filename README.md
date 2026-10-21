# Road Beyond Roles - screenshot-first career content pipeline

This package supports the Road Beyond Roles production model:

- fresh India-eligible jobs
- internships
- apprenticeships
- career courses/certifications
- resume/ATS education
- assessment practice
- interview questions/preparation
- weekly career giveaway/value videos
- screenshot-only visuals
- local/free Edge TTS
- one complete master narration for educational content
- FFmpeg assembly
- GitHub content manifests
- optional YouTube upload

## Daily jobs

The daily runner calls:

    python run_daily.py --push

The production run publishes `docs/` to the configured GitHub remote,
waits for the GitHub Pages URL derived from that remote to become reachable,
and only then captures screenshots from the deployed Road Beyond Roles
`job.html?id=...` pages. It does not use the original job-board URL as the
video visual source.

The daily feed therefore uses the India calendar day based on the original
posting timestamp. `updated_at` is not used as a substitute for an original
posting date.

A day with one valid job is allowed to produce one video.

## Educational / weekly content

Create a JSON file using `content_type`:

    resume
    ats
    assessment
    interview
    career
    course
    internship
    apprenticeship
    giveaway

Example:

```json
{
  "content_id": "weekly-resume-001",
  "content_type": "resume",
  "title": "5 Resume Mistakes to Fix",
  "intro": "Here are five resume mistakes that can weaken an application.",
  "sections": [
    {"heading": "Mistake 1", "body": "Using generic bullets.", "narration": "Avoid generic bullets. Show the result of your work."}
  ],
  "source_urls": [],
  "evidence": ["Original educational content"],
  "tags": ["resume", "ats", "career"]
}
```

Run:

    python run_daily.py --content weekly_resume.json --tts silent

or with free Edge TTS:

    python run_daily.py --content weekly_resume.json

The educational pipeline renders original HTML scenes to PNG screenshots,
creates one complete narration, segments it for timing, assembles the
screenshot video with FFmpeg, and writes the content manifest/screenshots
under `docs/content/<content_id>/`.

## Existing daily automation

`daily.yml` remains the canonical workflow file in this package. It installs
Playwright Chromium and FFmpeg and runs the production pipeline with `--push`.
The repository must have GitHub Pages configured to publish the `docs/`
directory. The pipeline fails closed if the deployed Pages site cannot be
verified.

## Safety

The scraper uses public sources and does not bypass CAPTCHA, bot challenges,
or access controls. If a source is blocked, it is skipped.

Always verify job, internship, apprenticeship, course, assessment and
interview information against the underlying source before publishing.
## Road Beyond Roles brand website

The GitHub Pages site uses the same visual identity as the Road Beyond Roles YouTube channel:

- `docs/assets/rbr-logo.jpg` — channel/profile logo used in the website header.
- `docs/assets/rbr-youtube-banner.jpg` — channel banner used as the website masthead.
- `pages.py` generates the branded homepage, archive, and job-detail pages.
- The YouTube channel CTA is wired to `https://www.youtube.com/@roadbeyondrole`.

The website remains a static GitHub Pages site using HTML/CSS/vanilla JavaScript and the existing generated JSON job data.
