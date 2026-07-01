#!/usr/bin/env python3
"""
Seek Gold Coast IT — daily git-scraper.

Scrapes every IT job advertised on Seek for the Gold Coast, fetches each job's
description via Seek's GraphQL endpoint, derives a keyword list from each job
title, and writes a single snapshot to data/latest.json. On a new day the
previous latest.json is rotated to data/<its-date>.json so git history + the
dated files form the time-series.

Standalone: depends only on `requests`. No database, no Scrapy.
"""

import argparse
import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# --- Seek endpoints ---------------------------------------------------------
SEARCH_URL = "https://www.seek.com.au/api/jobsearch/v5/search"
GRAPHQL_URL = "https://www.seek.com.au/graphql"

# --- What we scrape ---------------------------------------------------------
REGION = "Gold Coast"
WHERE = "All Gold Coast QLD"
CLASSIFICATION = "6281"  # Information & Communication Technology

# IT subclassification codes (6282-6303). Seek caps a plain classification
# search, so we sweep each subcategory and dedupe by job id.
IT_SUBCATS = [str(c) for c in range(6282, 6304)]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15"
    ),
    "Accept": "application/json",
}

# --- GraphQL description query ---------------------------------------------
_JOB_QUERY = (
    "query jobDetails($jobId: ID!) { "
    "jobDetails(id: $jobId) { job { title content(platform: WEB) location { label } } } "
    "}"
)

# --- Keyword extraction (titles only, no matching list) --------------------
# Generic noise to drop; whatever survives is a keyword verbatim.
STOP = set(
    """
    a an the of and or to for in on with at by from is are as was be & +
    senior junior lead head principal level i ii iii iv graduate entry mid
    new role roles job jobs opportunity opportunities career careers
    qld gold coast queensland australia australian
    expression interest eoi register casual vacation temp temporary
    full part time hybrid remote onsite permanent contract fixed term
    x2 amp
    """.split()
)
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.]*")


def extract_keywords(title: str) -> list:
    """Tokenize a job title into keywords. No curated list, no aliasing."""
    if not title:
        return []
    seen, out = set(), []
    for tok in _TOKEN_RE.findall(title.lower()):
        tok = tok.strip(".")
        if len(tok) < 2 or tok in STOP:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


# --- Scraping ---------------------------------------------------------------
def search_page(session, subcat, page):
    params = {
        "siteKey": "AU-Main",
        "sourcesystem": "houston",
        "where": WHERE,
        "page": page,
        "seekSelectAllPages": "true",
        "classification": CLASSIFICATION,
        "subclassification": subcat,
        "include": "seodata",
        "locale": "en-AU",
    }
    resp = session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_job(data):
    job = {
        "job_id": str(data.get("id")),
        "job_title": data.get("title", ""),
        "business_name": "",
        "work_type": "",
        "job_type": "",
        "pay_range": data.get("salaryLabel", ""),
        "area": "",
        "region": REGION,
        "url": f"https://www.seek.com.au/job/{data.get('id')}",
        "advertiser_id": None,
        "posted_date": data.get("listingDate", ""),
    }
    if data.get("advertiser"):
        job["advertiser_id"] = data["advertiser"].get("id")
        job["business_name"] = data["advertiser"].get("description", "")
    if data.get("workTypes"):
        job["work_type"] = data["workTypes"][0]
    if data.get("locations"):
        job["area"] = data["locations"][0].get("label", "")
    if data.get("classifications"):
        sub = data["classifications"][0].get("subclassification") or {}
        job["job_type"] = sub.get("description", "")
    return job


def scrape_jobs(session, limit=None, delay=0.3):
    """Sweep all IT subcategories, paginate, dedupe by job id."""
    jobs = {}
    for subcat in IT_SUBCATS:
        page = 1
        while True:
            try:
                raw = search_page(session, subcat, page)
            except requests.RequestException as e:
                print(f"  ! subcat {subcat} page {page}: {e}", file=sys.stderr)
                break

            page_size = (raw.get("solMetadata") or {}).get("pageSize", 20) or 20
            total = raw.get("totalCount", 0)
            total_pages = (total + page_size - 1) // page_size

            for data in raw.get("data", []):
                job = parse_job(data)
                jobs.setdefault(job["job_id"], job)

            if limit and len(jobs) >= limit:
                print(f"  limit {limit} reached", file=sys.stderr)
                return dict(list(jobs.items())[:limit])

            if page >= total_pages or page >= 25:
                break
            page += 1
            time.sleep(delay)
        time.sleep(delay)
    return jobs


def fetch_description(session, job_id, timeout=30):
    """Return (html, status) for a job via Seek's GraphQL endpoint."""
    payload = {
        "operationName": "jobDetails",
        "variables": {"jobId": str(job_id)},
        "query": _JOB_QUERY,
    }
    try:
        resp = session.post(GRAPHQL_URL, json=payload, headers=HEADERS, timeout=timeout)
    except requests.Timeout:
        return "", "timeout"
    except requests.RequestException:
        return "", "request_error"

    if resp.status_code == 429:
        return "", "rate_limited"
    if resp.status_code != 200:
        return "", "http_error"
    try:
        body = resp.json()
    except ValueError:
        return "", "invalid_json"
    if body.get("errors"):
        msg = str(body["errors"]).lower()
        if "rate_limited" in msg or "too many requests" in msg:
            return "", "rate_limited"
        return "", "graphql_error"

    job = ((body.get("data") or {}).get("jobDetails") or {}).get("job")
    if not job:
        return "", "not_found"
    return job.get("content") or "", "success"


def backfill_descriptions(session, jobs, delay=0.6):
    total = len(jobs)
    for i, (job_id, job) in enumerate(jobs.items(), 1):
        html, status = "", ""
        for attempt in range(3):
            html, status = fetch_description(session, job_id)
            if status not in ("rate_limited", "timeout", "http_error", "request_error"):
                break
            time.sleep(1.5 * (attempt + 1))
        job["job_description"] = html
        if i % 10 == 0 or i == total:
            print(f"  descriptions {i}/{total}", file=sys.stderr)
        time.sleep(delay)


# --- Snapshot assembly + rotation ------------------------------------------
def rotate_previous(data_dir: Path, today: str):
    """Move a prior-day latest.json to data/<its-date>.json."""
    latest = data_dir / "latest.json"
    if not latest.exists():
        return
    try:
        prev = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    prev_date = prev.get("date")
    if prev_date and prev_date != today:
        archived = data_dir / f"{prev_date}.json"
        shutil.move(str(latest), str(archived))
        print(f"  rotated previous snapshot -> {archived.name}", file=sys.stderr)


def write_manifest(data_dir: Path, today: str):
    dates = set()
    for p in data_dir.glob("*.json"):
        if p.name in ("latest.json", "manifest.json"):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
            dates.add(p.stem)
    dates.add(today)
    manifest = {
        "latest_date": today,
        "region": REGION,
        "dates": sorted(dates, reverse=True),
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def build_snapshot(jobs: dict, today: str) -> dict:
    tally = Counter()
    job_list = []
    for job in jobs.values():
        kws = extract_keywords(job["job_title"])
        job["keywords"] = kws
        tally.update(kws)
        job_list.append(job)

    total = len(job_list)
    keywords = [
        {"term": term, "count": count, "share": round(count / total, 4) if total else 0}
        for term, count in tally.most_common()
    ]
    job_list.sort(key=lambda j: j.get("posted_date") or "", reverse=True)
    return {
        "date": today,
        "region": REGION,
        "scraped_at": datetime.now(ZoneInfo("Australia/Brisbane")).isoformat(),
        "total_jobs": total,
        "keywords": keywords,
        "jobs": job_list,
    }


def main():
    ap = argparse.ArgumentParser(description="Seek Gold Coast IT git-scraper")
    ap.add_argument("--limit", type=int, default=None, help="cap jobs (testing)")
    ap.add_argument("--no-descriptions", action="store_true", help="skip GraphQL description fetch")
    ap.add_argument("--out", default=".", help="repo root (contains data/)")
    ap.add_argument("--delay", type=float, default=0.4, help="base politeness delay (s)")
    args = ap.parse_args()

    out_root = Path(args.out)
    data_dir = out_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo("Australia/Brisbane")).strftime("%Y-%m-%d")

    session = requests.Session()

    print(f"Scraping {REGION} IT jobs ...", file=sys.stderr)
    jobs = scrape_jobs(session, limit=args.limit, delay=args.delay)
    print(f"  {len(jobs)} unique jobs", file=sys.stderr)

    if not args.no_descriptions and jobs:
        print("Fetching descriptions ...", file=sys.stderr)
        backfill_descriptions(session, jobs, delay=max(args.delay, 0.6))
    else:
        for job in jobs.values():
            job["job_description"] = ""

    snapshot = build_snapshot(jobs, today)

    rotate_previous(data_dir, today)
    (data_dir / "latest.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(data_dir, today)

    print(
        f"Wrote {data_dir/'latest.json'} — {snapshot['total_jobs']} jobs, "
        f"{len(snapshot['keywords'])} distinct keywords",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
