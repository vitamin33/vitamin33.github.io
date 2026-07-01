#!/usr/bin/env python3
"""Tiny stdlib-only GitHub API client shared by the metrics pipeline.

Exports:
    get_token()                     -> token from GITHUB_TOKEN (fallback GH_TOKEN)
    get_json(path_or_url, token)    -> parsed JSON (None on 202 / empty body)
    graphql(query, variables, token)-> GraphQL `data` dict
    list_owned_repos(login, token)  -> public, non-fork, non-archived owned repos

All requests send the recommended GitHub headers and retry once on 5xx or
network errors (after 2s). HTTP failures raise GitHubApiError with a
`.status` attribute so callers can tolerate 202/403/404 per-repo.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
GRAPHQL_URL = API_ROOT + "/graphql"
USER_AGENT = "vitamin33-profile-metrics (github.com/vitamin33/vitamin33.github.io)"
RETRY_DELAY_S = 2.0
PAGE_SLEEP_S = 0.15
REQUEST_TIMEOUT_S = 30


class GitHubApiError(Exception):
    """GitHub API failure. `status` holds the HTTP code (0 = network error)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def get_token() -> str | None:
    """Auth token from env: GITHUB_TOKEN, falling back to GH_TOKEN."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def _headers(token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(url: str, token: str | None, data: bytes | None = None) -> tuple[int, bytes]:
    """One GET/POST round trip with a single retry on 5xx / network error."""
    for attempt in (1, 2):
        req = urllib.request.Request(
            url, data=data, headers=_headers(token), method="POST" if data else "GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            if 500 <= err.code < 600 and attempt == 1:
                print(f"[gh_api] WARN: HTTP {err.code} for {url}, retrying in {RETRY_DELAY_S}s",
                      file=sys.stderr)
                time.sleep(RETRY_DELAY_S)
                continue
            snippet = ""
            try:
                snippet = err.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 - best-effort body read
                pass
            raise GitHubApiError(f"HTTP {err.code} for {url}: {snippet}", status=err.code) from err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            if attempt == 1:
                print(f"[gh_api] WARN: network error for {url} ({err}), retrying in {RETRY_DELAY_S}s",
                      file=sys.stderr)
                time.sleep(RETRY_DELAY_S)
                continue
            raise GitHubApiError(f"Network error for {url}: {err}", status=0) from err
    raise GitHubApiError(f"Request failed for {url}", status=0)  # pragma: no cover


def get_json(path_or_url: str, token: str | None):
    """GET a REST endpoint (full URL or path like '/repos/x/y'), return parsed JSON.

    Returns None when the API answers 202 (data still being computed) or with
    an empty body. Raises GitHubApiError on HTTP errors.
    """
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        url = path_or_url
    else:
        url = API_ROOT + (path_or_url if path_or_url.startswith("/") else "/" + path_or_url)
    status, body = _request(url, token)
    if status == 202 or not body.strip():
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise GitHubApiError(f"Bad JSON from {url}: {err}", status=status) from err


def graphql(query: str, variables: dict | None, token: str | None) -> dict:
    """POST a GraphQL query, return the `data` object. Raises on GraphQL errors."""
    if not token:
        raise GitHubApiError("GraphQL requires an auth token", status=401)
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    status, body = _request(GRAPHQL_URL, token, data=payload)
    try:
        doc = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise GitHubApiError(f"Bad JSON from GraphQL: {err}", status=status) from err
    if doc.get("errors"):
        messages = "; ".join(str(e.get("message", e)) for e in doc["errors"])
        raise GitHubApiError(f"GraphQL errors: {messages}", status=status)
    return doc.get("data") or {}


# Fields the downstream pipeline actually consumes.
_REPO_FIELDS = (
    "name", "full_name", "html_url", "description", "fork", "archived", "private",
    "stargazers_count", "forks_count", "language", "pushed_at", "default_branch",
)


def list_owned_repos(login: str, token: str | None) -> list[dict]:
    """Public, non-fork, non-archived repos owned by `login`, sorted by name.

    Uses the authenticated /user/repos?affiliation=owner listing when the token
    belongs to `login` (matches the push access traffic endpoints require),
    otherwise falls back to the public /users/{login}/repos listing.
    """
    base = f"/users/{login}/repos?type=owner&per_page=100"
    if token:
        try:
            me = get_json("/user", token) or {}
            if str(me.get("login") or "").lower() == login.lower():
                base = "/user/repos?affiliation=owner&per_page=100"
        except GitHubApiError as err:
            if err.status == 401:
                raise
            print(f"[gh_api] WARN: /user lookup failed ({err}); using public listing",
                  file=sys.stderr)

    repos: list[dict] = []
    page = 1
    while True:
        batch = get_json(f"{base}&page={page}", token)
        if not batch:
            break
        for repo in batch:
            if repo.get("private") or repo.get("fork") or repo.get("archived"):
                continue
            owner = str((repo.get("owner") or {}).get("login") or "")
            if owner.lower() != login.lower():
                continue
            repos.append({key: repo.get(key) for key in _REPO_FIELDS})
        if len(batch) < 100:
            break
        page += 1
        time.sleep(PAGE_SLEEP_S)
    repos.sort(key=lambda r: str(r.get("name") or "").lower())
    return repos
