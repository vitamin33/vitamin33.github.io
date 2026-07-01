#!/usr/bin/env python3
"""Build site/data.json — the single contract between the pipeline and the
static dashboard. Reads config.json plus everything under data/, fetches live
metadata (languages, contributions, featured repos) and writes one JSON file.

Works on first run: tolerates a data/ dir that only has today's snapshot (or
nothing at all). Exits non-zero only on total failure (auth / repo listing).

Run from repo root:  python3 pipeline/build_site_data.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_api import GitHubApiError, get_json, get_token, graphql, list_owned_repos  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
TRAFFIC_DIR = os.path.join(ROOT, "data", "traffic")
HISTORY_PATH = os.path.join(ROOT, "data", "stats_history.json")
OUT_PATH = os.path.join(ROOT, "site", "data.json")
SLEEP_S = 0.15
TOP_REFERRERS = 8
TOP_PATHS = 8
TOP_LANGUAGES = 8
TOP_REPOS = 6

CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

CONTRIB_LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as err:
        print(f"WARN: could not read {path} ({err}); using default", file=sys.stderr)
        return default


def save_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_traffic_docs() -> list[dict]:
    docs = []
    for path in sorted(glob.glob(os.path.join(TRAFFIC_DIR, "*.json"))):
        doc = load_json(path, None)
        if isinstance(doc, dict) and doc.get("repo"):
            docs.append(doc)
    return docs


def build_traffic_series(docs: list[dict]) -> list[dict]:
    """Aggregate views/clones across ALL repos per date, full history, asc."""
    per_date: dict = defaultdict(lambda: {"views": 0, "uniques": 0, "clones": 0})
    for doc in docs:
        views = doc.get("views") or {}
        for date, entry in views.items():
            if isinstance(entry, dict):
                per_date[date]["views"] += int(entry.get("count") or 0)
                per_date[date]["uniques"] += int(entry.get("uniques") or 0)
        clones = doc.get("clones") or {}
        for date, entry in clones.items():
            if isinstance(entry, dict):
                per_date[date]["clones"] += int(entry.get("count") or 0)
    return [
        {"date": date, "views": per_date[date]["views"],
         "uniques": per_date[date]["uniques"], "clones": per_date[date]["clones"]}
        for date in sorted(per_date)
    ]


def latest_snapshot_items(doc: dict, key: str) -> list:
    """Items from a repo's most recent referrers/paths snapshot date."""
    snapshots = doc.get(key) or {}
    if not isinstance(snapshots, dict) or not snapshots:
        return []
    latest = max(snapshots)
    items = snapshots.get(latest)
    return items if isinstance(items, list) else []


def aggregate_referrers(docs: list[dict]) -> list[dict]:
    agg: dict = {}
    for doc in docs:
        for item in latest_snapshot_items(doc, "referrers"):
            name = str(item.get("referrer") or "")
            slot = agg.setdefault(name, {"referrer": name, "count": 0, "uniques": 0})
            slot["count"] += int(item.get("count") or 0)
            slot["uniques"] += int(item.get("uniques") or 0)
    ranked = sorted(agg.values(), key=lambda r: (-r["count"], r["referrer"]))
    return ranked[:TOP_REFERRERS]


def aggregate_paths(docs: list[dict]) -> list[dict]:
    agg: dict = {}
    for doc in docs:
        for item in latest_snapshot_items(doc, "paths"):
            key = str(item.get("path") or "")
            slot = agg.setdefault(key, {"path": key, "title": str(item.get("title") or ""),
                                        "count": 0, "uniques": 0})
            slot["count"] += int(item.get("count") or 0)
            slot["uniques"] += int(item.get("uniques") or 0)
    ranked = sorted(agg.values(), key=lambda p: (-p["count"], p["path"]))
    return ranked[:TOP_PATHS]


def top_repos_14d(docs: list[dict], cutoff: str) -> list[dict]:
    rows = []
    for doc in docs:
        views = uniques = 0
        for date, entry in (doc.get("views") or {}).items():
            if date >= cutoff and isinstance(entry, dict):
                views += int(entry.get("count") or 0)
                uniques += int(entry.get("uniques") or 0)
        if views > 0:
            rows.append({"repo": str(doc.get("repo") or ""), "views": views, "uniques": uniques})
    rows.sort(key=lambda r: (-r["views"], r["repo"]))
    return rows[:TOP_REPOS]


def fetch_languages(login: str, repos: list[dict], token: str) -> list[dict]:
    """Byte-weighted language mix across processed repos, top N, pct of total."""
    totals: dict = defaultdict(int)
    for repo in repos:
        name = str(repo.get("name") or "")
        if not name:
            continue
        try:
            langs = get_json(f"/repos/{login}/{name}/languages", token) or {}
        except GitHubApiError as err:
            print(f"WARN: languages for {name} failed ({err}); skipping", file=sys.stderr)
            continue
        for lang, size in langs.items():
            try:
                totals[lang] += int(size)
            except (TypeError, ValueError):
                continue
        time.sleep(SLEEP_S)
    grand_total = sum(totals.values())
    if grand_total <= 0:
        return []
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_LANGUAGES]
    return [{"name": name, "pct": round(size * 100.0 / grand_total, 2)} for name, size in ranked]


def fetch_contributions(login: str, token: str) -> dict:
    """Last 365 days of contributions via GraphQL. Tolerates non-auth failures."""
    now = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    variables = {
        "login": login,
        "from": (now - timedelta(days=365)).strftime(fmt),
        "to": now.strftime(fmt),
    }
    try:
        data = graphql(CONTRIB_QUERY, variables, token)
    except GitHubApiError as err:
        if err.status == 401:
            raise
        print(f"WARN: contributions query failed ({err}); using empty calendar", file=sys.stderr)
        return {"total": 0, "days": []}
    calendar = (((data.get("user") or {}).get("contributionsCollection") or {})
                .get("contributionCalendar") or {})
    days = []
    for week in calendar.get("weeks") or []:
        for day in (week or {}).get("contributionDays") or []:
            date = str(day.get("date") or "")
            if not date:
                continue
            days.append({
                "date": date,
                "count": int(day.get("contributionCount") or 0),
                "level": CONTRIB_LEVELS.get(str(day.get("contributionLevel") or "NONE"), 0),
            })
    days.sort(key=lambda d: d["date"])
    return {"total": int(calendar.get("totalContributions") or 0), "days": days}


def build_featured(config: dict, repo_by_name: dict, login: str, token: str) -> list[dict]:
    """Join config.featured with live repo metadata."""
    featured = []
    for item in config.get("featured") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("repo") or "")
        if not name:
            continue
        meta = repo_by_name.get(name)
        if meta is None:
            try:
                meta = get_json(f"/repos/{login}/{name}", token) or {}
            except GitHubApiError as err:
                print(f"WARN: featured repo {name} not fetchable ({err}); using defaults",
                      file=sys.stderr)
                meta = {}
            time.sleep(SLEEP_S)
        pushed_at = str(meta.get("pushed_at") or "")[:10] or None
        featured.append({
            "name": name,
            "url": meta.get("html_url") or f"https://github.com/{login}/{name}",
            "description": meta.get("description") or "",
            "impact": str(item.get("impact") or ""),
            "tags": list(item.get("tags") or []),
            "stars": int(meta.get("stargazers_count") or 0),
            "pushed_at": pushed_at,
        })
    return featured


def main() -> int:
    token = get_token()
    if not token:
        print("ERROR: no GITHUB_TOKEN (or GH_TOKEN) in environment", file=sys.stderr)
        return 1

    config = load_json(CONFIG_PATH, {})
    login = str(config.get("login") or "vitamin33")
    exclude = set(config.get("exclude_repos") or [])

    try:
        repos = [r for r in list_owned_repos(login, token) if r.get("name") not in exclude]
    except GitHubApiError as err:
        print(f"ERROR: could not list repos for {login}: {err}", file=sys.stderr)
        return 1
    repo_by_name = {str(r.get("name")): r for r in repos}

    # Profile numbers: live first, stats history as fallback.
    history = load_json(HISTORY_PATH, {})
    snapshots = history.get("snapshots") if isinstance(history, dict) else None
    latest_stats = snapshots[-1] if isinstance(snapshots, list) and snapshots else {}
    followers = int(latest_stats.get("followers") or 0)
    public_repos = int(latest_stats.get("public_repos") or 0)
    try:
        user = get_json(f"/users/{login}", token) or {}
        followers = int(user.get("followers") or 0)
        public_repos = int(user.get("public_repos") or 0)
    except GitHubApiError as err:
        print(f"WARN: /users/{login} failed ({err}); using stats history fallback",
              file=sys.stderr)

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    cutoff_14d = (now - timedelta(days=13)).strftime("%Y-%m-%d")

    traffic_docs = load_traffic_docs()
    series = build_traffic_series(traffic_docs)
    last_14 = [p for p in series if p["date"] >= cutoff_14d]

    contributions = fetch_contributions(login, token)
    languages = fetch_languages(login, repos, token)
    stars_total = sum(int(r.get("stargazers_count") or 0) for r in repos)

    data = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": {
            "login": login,
            "name": str(config.get("name") or login),
            "headline": str(config.get("headline") or ""),
            "avatar_url": f"https://github.com/{login}.png",
            "followers": followers,
            "public_repos": public_repos,
        },
        "kpis": {
            "views_14d": sum(p["views"] for p in last_14),
            "uniques_14d": sum(p["uniques"] for p in last_14),
            "clones_14d": sum(p["clones"] for p in last_14),
            "views_total_tracked": sum(p["views"] for p in series),
            "stars_total": stars_total,
            "followers": followers,
            "contributions_365d": contributions["total"],
            "tracking_since": series[0]["date"] if series else today,
        },
        "traffic_series": series,
        "referrers": aggregate_referrers(traffic_docs),
        "popular_paths": aggregate_paths(traffic_docs),
        "languages": languages,
        "contributions": contributions,
        "top_repos_14d": top_repos_14d(traffic_docs, cutoff_14d),
        "featured": build_featured(config, repo_by_name, login, token),
        "cta": config.get("cta") or {},
    }

    save_json(OUT_PATH, data)
    print(f"Wrote {os.path.relpath(OUT_PATH, ROOT)}: "
          f"{len(series)} tracked day(s), {len(traffic_docs)} repo traffic file(s), "
          f"views_14d={data['kpis']['views_14d']}, "
          f"contributions_365d={data['kpis']['contributions_365d']}, "
          f"{len(languages)} language(s), {len(data['featured'])} featured repo(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
