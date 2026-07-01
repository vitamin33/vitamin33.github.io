#!/usr/bin/env python3
"""Collect daily profile stats (followers, repos, stars, forks) into
data/stats_history.json. One entry per calendar date, upserted — safe to
re-run any number of times per day.

Run from repo root:  python3 pipeline/collect_stats.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_api import GitHubApiError, get_json, get_token, list_owned_repos  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
HISTORY_PATH = os.path.join(ROOT, "data", "stats_history.json")


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


def main() -> int:
    token = get_token()
    if not token:
        print("ERROR: no GITHUB_TOKEN (or GH_TOKEN) in environment", file=sys.stderr)
        return 1

    config = load_json(CONFIG_PATH, {})
    login = str(config.get("login") or "vitamin33")
    exclude = set(config.get("exclude_repos") or [])

    try:
        user = get_json(f"/users/{login}", token) or {}
        repos = list_owned_repos(login, token)
    except GitHubApiError as err:
        print(f"ERROR: could not fetch profile stats for {login}: {err}", file=sys.stderr)
        return 1

    repos = [r for r in repos if r.get("name") not in exclude]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "followers": int(user.get("followers") or 0),
        "following": int(user.get("following") or 0),
        "public_repos": int(user.get("public_repos") or 0),
        "total_stars": sum(int(r.get("stargazers_count") or 0) for r in repos),
        "total_forks": sum(int(r.get("forks_count") or 0) for r in repos),
    }

    history = load_json(HISTORY_PATH, {})
    snapshots = history.get("snapshots")
    if not isinstance(snapshots, list):
        snapshots = []
    snapshots = [s for s in snapshots if isinstance(s, dict) and s.get("date") != today]
    snapshots.append(entry)
    snapshots.sort(key=lambda s: str(s.get("date") or ""))
    save_json(HISTORY_PATH, {"snapshots": snapshots})

    print(f"{today}: followers={entry['followers']}, following={entry['following']}, "
          f"public_repos={entry['public_repos']}, stars={entry['total_stars']}, "
          f"forks={entry['total_forks']} ({len(snapshots)} snapshot(s) total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
