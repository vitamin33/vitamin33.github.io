#!/usr/bin/env python3
"""Snapshot GitHub traffic (views, clones, referrers, paths) for owned repos.

GitHub's traffic API only retains a rolling 14-day window, so this script runs
daily (GitHub Actions) and upserts into data/traffic/<repo>.json — history
accumulates forever. Idempotent: re-running on the same day rewrites the same
keys with identical results.

Run from repo root:  python3 pipeline/snapshot_traffic.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_api import GitHubApiError, get_json, get_token, list_owned_repos  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
TRAFFIC_DIR = os.path.join(ROOT, "data", "traffic")
SLEEP_S = 0.15                 # be gentle between API calls
MAX_SNAPSHOT_DATES = 30        # referrers/paths: keep only latest N snapshot dates
TOLERATED_STATUSES = (202, 403, 404)


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as err:
        print(f"WARN: could not read {path} ({err}); starting fresh", file=sys.stderr)
        return default


def save_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def upsert_daily(bucket: dict, items) -> int:
    """Upsert traffic items ({timestamp,count,uniques}) by date. Returns new dates."""
    added = 0
    for item in items or []:
        # timestamps arrive like "2026-07-01T00:00:00Z" — keep the date part only
        date = str(item.get("timestamp") or "")[:10]
        if len(date) != 10:
            continue
        if date not in bucket:
            added += 1
        bucket[date] = {
            "count": int(item.get("count") or 0),
            "uniques": int(item.get("uniques") or 0),
        }
    return added


def snapshot_repo(login: str, repo_name: str, token: str, today: str) -> dict | None:
    """Fetch all four traffic endpoints for one repo and upsert its JSON file.

    Returns a small summary dict, or None if the repo was skipped (202/403/404).
    """
    endpoints = {
        "views": f"/repos/{login}/{repo_name}/traffic/views?per=day",
        "clones": f"/repos/{login}/{repo_name}/traffic/clones?per=day",
        "referrers": f"/repos/{login}/{repo_name}/traffic/popular/referrers",
        "paths": f"/repos/{login}/{repo_name}/traffic/popular/paths",
    }
    fetched: dict = {}
    for key, path in endpoints.items():
        try:
            fetched[key] = get_json(path, token)
        except GitHubApiError as err:
            if err.status in TOLERATED_STATUSES:
                print(f"WARN: {repo_name}: {key} returned HTTP {err.status}; skipping repo",
                      file=sys.stderr)
                return None
            raise
        if fetched[key] is None:  # 202 (still computing) or empty body
            print(f"WARN: {repo_name}: {key} returned no data (202/empty); skipping repo",
                  file=sys.stderr)
            return None
        time.sleep(SLEEP_S)

    path = os.path.join(TRAFFIC_DIR, f"{repo_name}.json")
    doc = load_json(path, {})
    doc.setdefault("repo", repo_name)
    for key in ("views", "clones", "referrers", "paths"):
        if not isinstance(doc.get(key), dict):
            doc[key] = {}

    new_views = upsert_daily(doc["views"], (fetched.get("views") or {}).get("views"))
    new_clones = upsert_daily(doc["clones"], (fetched.get("clones") or {}).get("clones"))

    referrers = [
        {
            "referrer": str(r.get("referrer") or ""),
            "count": int(r.get("count") or 0),
            "uniques": int(r.get("uniques") or 0),
        }
        for r in (fetched.get("referrers") or [])
    ]
    popular_paths = [
        {
            "path": str(p.get("path") or ""),
            "title": str(p.get("title") or ""),
            "count": int(p.get("count") or 0),
            "uniques": int(p.get("uniques") or 0),
        }
        for p in (fetched.get("paths") or [])
    ]
    doc["referrers"][today] = referrers
    doc["paths"][today] = popular_paths

    # Keep only the latest N snapshot dates for referrers/paths.
    for key in ("referrers", "paths"):
        for stale in sorted(doc[key])[:-MAX_SNAPSHOT_DATES]:
            del doc[key][stale]

    save_json(path, doc)
    summary = {
        "views_days": len(doc["views"]),
        "new_views_days": new_views,
        "clones_days": len(doc["clones"]),
        "new_clones_days": new_clones,
        "referrers": len(referrers),
        "paths": len(popular_paths),
    }
    print(f"{repo_name}: views_days={summary['views_days']} (+{new_views}), "
          f"clones_days={summary['clones_days']} (+{new_clones}), "
          f"referrers={summary['referrers']}, paths={summary['paths']}")
    return summary


def main() -> int:
    token = get_token()
    if not token:
        print("ERROR: no GITHUB_TOKEN (or GH_TOKEN) in environment", file=sys.stderr)
        return 1

    config = load_json(CONFIG_PATH, {})
    login = str(config.get("login") or "vitamin33")
    exclude = set(config.get("exclude_repos") or [])

    try:
        repos = list_owned_repos(login, token)
    except GitHubApiError as err:
        print(f"ERROR: could not list repos for {login}: {err}", file=sys.stderr)
        return 1

    targets = [r for r in repos if r.get("name") not in exclude]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Snapshotting traffic for {len(targets)} repo(s) "
          f"({len(repos) - len(targets)} excluded) — {today}")

    processed = skipped = 0
    for repo in targets:
        name = str(repo.get("name") or "")
        if not name:
            continue
        try:
            result = snapshot_repo(login, name, token, today)
        except GitHubApiError as err:
            print(f"WARN: {name}: {err}; skipping repo", file=sys.stderr)
            result = None
        if result is None:
            skipped += 1
        else:
            processed += 1

    print(f"Total: {processed} repo(s) snapshotted, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
