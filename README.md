# vitamin33.github.io — Live Proof-of-Work Dashboard

**Self-updating GitHub metrics dashboard — scheduled ingest → git-as-datastore → static rebuild.**

[![Live Dashboard](https://img.shields.io/badge/live-vitamin33.github.io-2ea44f?logo=githubpages)](https://vitamin33.github.io/)
[![Metrics Pipeline](https://img.shields.io/badge/pipeline-Python%203.11%20stdlib%20only-3776ab?logo=python&logoColor=white)](pipeline/)

A zero-dependency data pipeline that turns my GitHub activity into a public, continuously updated
portfolio page. Built by [Vitalii Serbyn](https://www.linkedin.com/in/vitalii-serbyn/) — MLOps / GenAI-LLM
engineer. The dashboard is the product; **this repo is the proof** that I design, ship, and operate
small production data systems end to end.

## Why this exists

GitHub's traffic API (views, clones, referrers, popular paths) only retains a **rolling 14-day
window** — after that, the data is gone forever. There is no official way to see long-term trends
on your own repositories.

This pipeline fixes that:

- A scheduled GitHub Actions job snapshots the full 14-day window **twice daily**.
- Snapshots are **merged/upserted by date** into JSON files committed to this repo, so re-runs are
  idempotent and history accumulates indefinitely.
- A build step aggregates everything into a single `site/data.json`, which a static dashboard
  (GitHub Pages) renders — no server, no database, no external services.

## Architecture

```
              cron: 04:17 & 16:17 UTC  (+ manual workflow_dispatch)
                              │
                              ▼
                 ┌─────────────────────────┐
                 │  GitHub Actions runner  │
                 └───────────┬─────────────┘
                             │  GITHUB_TOKEN = METRICS_TOKEN secret
                             ▼
        ┌────────────────────────────────────────────┐
        │  GitHub REST + GraphQL APIs                │
        │  traffic (views/clones/referrers/paths),   │
        │  repo stats, languages, contributions      │
        └───────────┬────────────────────────────────┘
                    │
                    ▼
        ┌────────────────────────────────────────────┐
        │  merge / upsert by date  →  data/          │
        │  data/traffic/<repo>.json                  │
        │  data/stats_history.json                   │
        └───────────┬────────────────────────────────┘
                    │
                    ▼
        ┌────────────────────────────────────────────┐
        │  build derived artifacts                   │
        │  site/data.json      (dashboard contract)  │
        └───────────┬────────────────────────────────┘
                    │
                    ▼
          commit & push  →  GitHub Pages redeploy
                    │
                    ▼
          https://vitamin33.github.io/  (static dashboard)
```

### Components

| Path                  | What it does |
|-----------------------|--------------|
| `pipeline/`           | Python 3.11 stdlib-only scripts: `snapshot_traffic.py` (daily traffic upsert), `collect_stats.py` (followers/stars/forks history), `build_site_data.py` (aggregates everything into `site/data.json`). |
| `data/`               | The datastore. Per-repo traffic JSON plus profile stats history, committed to git — full audit trail of every data point ever collected. |
| `site/`               | Static dashboard (HTML/CSS/JS) served by GitHub Pages. Reads only `site/data.json`. |
| `.github/workflows/`  | Scheduled metrics workflow (ingest → build → commit) and Pages deployment. |
| `config.json`         | Single source of truth: profile identity, featured projects with impact statements, excluded repos, CTA links. |

## Design decisions

- **Twice-daily cadence vs. a 14-day window.** GitHub's scheduled workflows are best-effort — runs
  can be delayed or skipped under load. Two runs per day against a 14-day retention window means a
  single missed run costs nothing; the next run re-fetches the full window and upserts. Losing data
  would require ~14 consecutive days of failures.
- **Git as the datastore.** No external DB to provision, pay for, secure, or lose. Every data point
  is versioned, diffable, and auditable in commit history. At this scale (a handful of small JSON
  files, two writes a day) a database would be pure overhead.
- **Stdlib-only Python.** No `pip install` step means no dependency resolution, no supply-chain
  surface, no lockfile drift, and faster Actions runs. `urllib.request` + `json` cover everything a
  metrics ingest needs.
- **Idempotency everywhere.** Every script re-fetches the full available window and upserts by
  date. Re-running any job any number of times produces the same state — safe to retry, safe to
  backfill, safe to run manually.
- **Keepalive against Actions auto-disable.** GitHub disables scheduled workflows after 60 days
  without repo activity. Since each run commits fresh data, the pipeline keeps itself alive — and
  the workflow guards against the edge case anyway.
- **Graceful degradation.** Rate limits, 202 "stats being computed" responses, empty repos, and
  missing first-run data are all handled by skip-log-continue, never by crashing the run.

## Setup (run this for your own profile)

1. **Create the repo** named `<your-username>.github.io` (that exact name is what GitHub Pages
   serves at the root domain), or fork this one and rename it.
2. **Create a fine-grained PAT** with access to your owned repositories and permissions:
   - `Administration: read` (required by the traffic endpoints)
   - `Metadata: read`
3. **Add the token** as a repository secret named `METRICS_TOKEN`
   (Settings → Secrets and variables → Actions).
4. **Enable GitHub Pages** with source "GitHub Actions" (Settings → Pages).
5. **Edit `config.json`** — your login, headline, featured repos, and CTA links.
6. **Run the metrics workflow** manually once (Actions → metrics → Run workflow) to seed
   `data/` and build the site. After that, the schedule takes over.

## A note on the numbers

The dashboard's numbers start small and grow over time — **that is the point**. Traffic history
begins accumulating the day the pipeline first runs; nothing is backfilled, estimated, or
inflated. What you see is exactly what the pipeline has observed, with the raw data auditable in
this repo's commit history.
