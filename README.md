# Seek Gold Coast IT — daily keyword tracker

A tiny [git-scraper](https://simonwillison.net/2020/Oct/9/git-scraping/): a GitHub
Action scrapes every IT job on [Seek](https://www.seek.com.au/) for the **Gold Coast**
once a day, derives a keyword list from each job title, and commits a snapshot to
`data/latest.json`. Git history + the dated archive files are the time-series; a static
page (`index.html`, served via GitHub Pages) renders it.

No database, no server. The scraper depends only on `requests`.

## What it produces

`data/latest.json` — today's snapshot:

```json
{
  "date": "2026-07-01",
  "region": "Gold Coast",
  "total_jobs": 74,
  "keywords": [{"term": "engineer", "count": 12, "share": 0.16}, ...],
  "jobs": [
    {"job_id": "...", "posted_date": "...", "job_title": "...",
     "business_name": "...", "work_type": "...", "area": "...",
     "url": "https://www.seek.com.au/job/...",
     "job_description": "<html>", "keywords": ["cloud", "engineer"]}
  ]
}
```

Each day the previous `latest.json` is rotated to `data/<date>.json`, and
`data/manifest.json` lists the available snapshot dates.

Keywords are the raw tokens of each job **title** (stopwords and seniority noise
removed) — no curated tech list, no aliasing.

## Run locally

```bash
uv venv --python 3.11
uv pip install -r requirements.txt

uv run python scrape.py --limit 10        # quick test
uv run python scrape.py                    # full Gold Coast IT scrape

python -m http.server                      # then open http://localhost:8000
```

Flags: `--limit N`, `--no-descriptions`, `--out DIR`, `--delay SECONDS`.

## Automation

`.github/workflows/scrape.yml` runs daily at 06:00 AEST (and on manual dispatch),
installs deps with [uv](https://docs.astral.sh/uv/), runs the scraper, and commits
`data/` if anything changed.

Repo settings required once:
- **Actions → Workflow permissions → Read and write** (so the Action can commit).
- **Pages** enabled (source: `main` / root) to serve `index.html`.
