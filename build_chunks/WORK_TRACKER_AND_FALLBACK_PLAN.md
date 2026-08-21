# Work Tracker + Model Tiered Fallback — Comprehensive Plan

## Executive Summary
Two interconnected systems:
1. **Work Tracker** — Centralized observability DB + dashboard for ALL agents (Hermes, Aegis, future)
2. **Model Tiered Fallback** — Unified router shared by Hermes + Aegis with OpenRouter free-tier chain

---

## 1. OPENROUTER CONFIGURATION REQUIREMENTS

### What YOU need to do on OpenRouter side:
| Action | Required? | Notes |
|--------|-----------|-------|
| **Enable all 6 free models** in your OpenRouter dashboard | **YES** | Models must be "activated" in your account before API calls work |
| **Set default model** to `nvidia/nemotron-3-ultra-550b-a55b:free` | Optional | Fallback handled in code, but good to have default |
| **Monitor usage** at https://openrouter.ai/activity | **YES** | Track daily request count across all models |
| **API Key** with appropriate permissions | **YES** | Single key works for all free models |
| **Rate limit awareness** | **YES** | 1000 req/day **per model** OR **per account**? Check docs — typically per account |

### Critical OpenRouter Gotcha:
> **Free tier limits are typically PER ACCOUNT, not per model.**
> If you hit 1000 requests on Nemotron, Llama-405B will ALSO return 429.
> **Strategy**: Track total requests in our router, pause ALL tiers at 950, resume at midnight UTC.

---

## 2. UNIFIED MODEL ROUTER — Shared by Hermes + Aegis

### Architecture: Single Source of Truth
```
┌─────────────────────────────────────────────────────────────┐
│                    ModelRouter (singleton)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Tier Chain  │  │ Token       │  │ Circuit Breaker     │  │
│  │ Manager     │  │ Accountant  │  │ & Rate Limiter      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│         │                │                    │              │
│         └────────────────┼────────────────────┘              │
│                          ▼                                   │
│              ┌───────────────────────┐                       │
│              │  Work Tracker Client  │──→ Central DB        │
│              │  (logs every request) │                       │
│              └───────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
         ▲                              ▲
         │                              │
    Hermes                          Aegis
  (profile)                        (Oracle)
```

### Implementation Location
- **Shared library**: `aegis/lib/model_router.py` (importable by both)
- **Hermes integration**: Via profile config → `model_router` plugin
- **Aegis integration**: `OracleAgent` uses `ModelRouter` directly

### Tier Chain (Validated Free Models, Aug 2026)
```python
TIER_CHAIN = [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free",    "ctx": 128_000, "tokenizer": "cl100k_base", "priority": "complex"},
    {"id": "meta-llama/llama-3.1-405b-instruct:free",    "ctx": 128_000, "tokenizer": "llama3",      "priority": "complex"},
    {"id": "google/gemma-2-27b-it:free",                 "ctx": 8_192,   "tokenizer": "gemma",       "priority": "fast"},
    {"id": "mistralai/mistral-nemo:free",                "ctx": 128_000, "tokenizer": "mistral",     "priority": "long_ctx"},
    {"id": "qwen/qwen-2.5-72b-instruct:free",            "ctx": 32_768,  "tokenizer": "qwen",        "priority": "multilingual"},
    {"id": "meta-llama/llama-3.1-70b-instruct:free",     "ctx": 128_000, "tokenizer": "llama3",      "priority": "fallback"},
]
```

---

## 3. WORK TRACKER — Centralized Observability Database

### Why Database (Not Flat Files)?
| Requirement | Flat Files | SQLite/PostgreSQL |
|-------------|------------|-------------------|
| Multiple writers (Hermes + Aegis + CLI) | ❌ Race conditions | ✅ ACID |
| Concurrent reads (dashboard + cron) | ❌ Locking issues | ✅ MVCC |
| Time-range queries | ❌ Full scan | ✅ Indexed |
| Aggregations (SUM, AVG, GROUP BY) | ❌ Manual | ✅ Native |
| Schema evolution | ❌ Painful | ✅ Migrations |
| **Verdict** | **NO** | **YES** |

### Database Schema (SQLite for simplicity, upgradeable to Postgres)
```sql
-- Core tables
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,           -- UUID
    agent           TEXT NOT NULL,              -- 'hermes', 'aegis', 'cli'
    profile         TEXT,                       -- 'default', 'aegis-prod'
    project         TEXT,                       -- 'aegis', 'work-tracker', etc.
    goal            TEXT,                       -- Free text: what was the objective?
    started_at      TIMESTAMP NOT NULL,
    ended_at        TIMESTAMP,
    status          TEXT DEFAULT 'active',      -- 'active', 'completed', 'aborted'
    metadata        JSON                        -- Extensible
);

CREATE TABLE requests (
    id              TEXT PRIMARY KEY,           -- UUID
    session_id      TEXT REFERENCES sessions(id),
    model           TEXT NOT NULL,              -- Full model ID
    tier            INTEGER NOT NULL,           -- 0=primary, 1=fallback1, etc.
    prompt_tokens   INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens    INTEGER NOT NULL,
    latency_ms      INTEGER,
    status          TEXT NOT NULL,              -- 'success', 'error', 'fallback'
    error_message   TEXT,
    timestamp       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata        JSON                        -- Request params, etc.
);

CREATE TABLE git_activity (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id),
    repo_path       TEXT NOT NULL,
    commit_hash     TEXT,
    branch          TEXT,
    files_changed   INTEGER,
    lines_added     INTEGER,
    lines_removed   INTEGER,
    pushed_to       TEXT,                       -- 'dev', 'test', 'prod', NULL
    timestamp       TIMESTAMP NOT NULL
);

CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(id),
    title           TEXT NOT NULL,
    status          TEXT NOT NULL,              -- 'pending', 'in_progress', 'completed', 'blocked'
    category        TEXT,                       -- 'feature', 'bug', 'refactor', 'docs', 'test'
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    metadata        JSON
);

CREATE TABLE daily_aggregates (
    date            DATE PRIMARY KEY,
    agent           TEXT NOT NULL,
    project         TEXT,
    total_requests  INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    total_sessions  INTEGER DEFAULT 0,
    unique_models   INTEGER DEFAULT 0,
    git_commits     INTEGER DEFAULT 0,
    files_touched   INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    tasks_pending   INTEGER DEFAULT 0,
    UNIQUE(date, agent, project)
);

-- Indexes for dashboard queries
CREATE INDEX idx_requests_session ON requests(session_id);
CREATE INDEX idx_requests_timestamp ON requests(timestamp);
CREATE INDEX idx_requests_model ON requests(model);
CREATE INDEX idx_sessions_agent_project ON sessions(agent, project);
CREATE INDEX idx_git_session ON git_activity(session_id);
```

### Writer Interface (All Agents Use This)
```python
# aegis/lib/work_tracker/client.py
class WorkTrackerClient:
    def __init__(self, db_path: str = "~/.work-tracker/analytics.db"):
        self.db = connect(db_path)
        self._init_schema()
    
    def start_session(self, agent: str, profile: str, project: str, goal: str) -> str:
        # Returns session_id
    
    def log_request(self, session_id: str, model: str, tier: int, 
                    prompt_tokens: int, completion_tokens: int, 
                    latency_ms: int, status: str, error: str = None):
        # Called by ModelRouter after EVERY request
    
    def log_git_activity(self, session_id: str, repo_path: str, **kwargs):
        # Called by git collector or manually
    
    def log_task(self, session_id: str, title: str, status: str, category: str):
        # Called by CLI or agent
    
    def end_session(self, session_id: str, status: str = "completed"):
        # Finalizes session
```

### How Hermes + Aegis Both Write to It
| Agent | Integration Point |
|-------|-------------------|
| **Hermes** | Profile plugin → `ModelRouter` → `WorkTrackerClient.log_request()` |
| **Aegis** | `OracleAgent` → `ModelRouter` → `WorkTrackerClient.log_request()` |
| **CLI/Dev** | `wt log-request ...`, `wt log-git ...`, `wt log-task ...` |
| **Cron** | Daily aggregate job reads `requests` + `git_activity` → writes `daily_aggregates` |

---

## 4. DASHBOARD — GitHub Pages Compatible?

### GitHub Pages = Static Only
| Feature | GitHub Pages | FastAPI/Streamlit |
|---------|--------------|-------------------|
| Static HTML/JS/CSS | ✅ | ✅ |
| Dynamic queries (date filters, drill-down) | ❌ | ✅ |
| Real-time updates | ❌ | ✅ |
| Authentication | ❌ | ✅ |
| Server-side aggregation | ❌ | ✅ |
| **Interactive widgets** | **Limited (JS only)** | **Full** |

### Recommended: Hybrid Approach
```
work-tracker/
├── dashboard/
│   ├── api/              # FastAPI (renders JSON for charts)
│   │   ├── main.py
│   │   └── routes/
│   ├── static/           # Built by: `npm run build` or `python build_dashboard.py`
│   │   ├── index.html
│   │   ├── app.js        # Chart.js / Plotly.js / Alpine.js
│   │   └── style.css
│   └── templates/        # Jinja2 for server-rendered fallback
├── data/
│   └── analytics.db      # SQLite (can be synced to GitHub via Action)
└── deploy/
    └── github-pages.yml  # GitHub Action: builds static + deploys to gh-pages
```

**Dashboard runs two modes:**
1. **Local/Server**: `python -m dashboard.api` → Full interactive (FastAPI + JS)
2. **GitHub Pages**: Static export → `dashboard/static/` → `gh-pages` branch

**Static export strategy:**
- Pre-aggregate data to JSON (daily, weekly, monthly)
- JS loads JSON, renders charts client-side (Chart.js/Plotly.js)
- Filters work client-side (no server needed)
- **Trade-off**: No real-time, but free hosting on GitHub Pages

---

## 5. COMPREHENSIVE TASK LIST

### PHASE 1: Foundation (Week 1)

#### 1.1 Work Tracker Repo + Database
- [ ] **T1.1** Create `work-tracker` repo with structure
- [ ] **T1.2** Implement `WorkTrackerClient` with SQLite schema + migrations
- [ ] **T1.3** Add `ModelRouter` class with tier chain, circuit breaker, token accounting
- [ ] **T1.4** Wire `ModelRouter` → `WorkTrackerClient` (auto-logs every request)
- [ ] **T1.5** Create CLI: `wt start-session`, `wt log-request`, `wt log-git`, `wt log-task`, `wt end-session`

#### 1.2 Hermes Integration
- [ ] **T1.6** Create Hermes plugin: `hermes_model_router.py` in `~/.hermes/profiles/default/plugins/`
- [ ] **T1.7** Plugin intercepts chat completions → routes through `ModelRouter`
- [ ] **T1.8** Update Hermes profile config to use plugin + track session

#### 1.3 Aegis Integration
- [ ] **T1.9** Add `ModelRouter` import to `aegis/agents/oracle/agent.py`
- [ ] **T1.10** Replace direct OpenRouter calls with `ModelRouter.complete()`
- [ ] **T1.11** Ensure `OracleAgent` passes session context to router

#### 1.4 Git Collector
- [ ] **T1.12** Implement `git_collector.py` → scans repos, extracts commits since last run
- [ ] **T1.13** Associate commits with active session (by time overlap or manual tag)
- [ ] **T1.14** Write to `git_activity` table via `WorkTrackerClient`

### PHASE 2: Daily Automation + Aggregation (Week 1-2)

- [ ] **T2.1** Daily cron job (`00:05 UTC`): `daily_aggregate.py`
  - Reads `requests`, `git_activity`, `tasks` for previous day
  - Computes aggregates → writes `daily_aggregates`
  - Exports JSON for static dashboard: `data/exports/YYYY-MM-DD.json`
- [ ] **T2.2** GitHub Action: runs daily aggregate, commits JSON to `gh-pages` branch
- [ ] **T2.3** Budget alert: if daily requests > 950, notify (email/Telegram/console)
- [ ] **T2.4** Backfill script: `wt backfill --from 2026-08-01 --to 2026-08-19`

### PHASE 3: Dashboard (Week 2)

#### 3.1 API Layer (FastAPI)
- [ ] **T3.1** `GET /api/v1/summary?date=...&agent=...&project=...`
- [ ] **T3.2** `GET /api/v1/timeseries?metric=requests|tokens|latency&granularity=hour|day`
- [ ] **T3.3** `GET /api/v1/models` — breakdown by model/tier
- [ ] **T3.4** `GET /api/v1/sessions` — paginated, filterable
- [ ] **T3.5** `GET /api/v1/git-activity` — commits, files, lines by repo/branch

#### 3.2 Static Export for GitHub Pages
- [ ] **T3.6** `build_dashboard.py` → calls API, writes `dashboard/static/data/*.json`
- [ ] **T3.7** `dashboard/static/index.html` + `app.js` (Chart.js + Alpine.js)
- [ ] **T3.8** Interactive widgets:
  - Date range picker
  - Agent filter (multi-select)
  - Project filter
  - Metric selector (requests/tokens/latency/errors)
  - Model tier breakdown (stacked bar)
  - Git activity heatmap (calendar view)
  - Task funnel (pending → in_progress → completed)

#### 3.3 GitHub Pages Deploy
- [ ] **T3.9** `.github/workflows/deploy-pages.yml`:
  - Trigger: daily cron + push to main
  - Steps: checkout → build_dashboard.py → deploy to `gh-pages`
- [ ] **T3.10** Custom domain (optional): `tracker.yourdomain.com`

### PHASE 4: Polish & Hardening (Week 2-3)

- [ ] **T4.1** Model router: per-tier tokenizer support (tiktoken + transformers)
- [ ] **T4.2** Circuit breaker: Redis-backed for multi-process (Aegis workers)
- [ ] **T4.3** Token normalization: convert all to "GPT-4 equivalent" for budgeting
- [ ] **T4.4** Session auto-detection: Hermes/Aegis start session on first request
- [ ] **T4.5** Data retention policy: raw requests 30 days, aggregates forever
- [ ] **T4.6** Export/Import: `wt export --format parquet|json|csv`
- [ ] **T4.7** Tests: unit + integration for router, tracker, dashboard API
- [ ] **T4.8** Documentation: README, architecture diagram, schema docs

---

## 6. DECISIONS NEEDED FROM YOU

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **DB Location** | `~/.work-tracker/analytics.db` (local) vs shared network path | Local SQLite per machine; sync via GitHub Action |
| **Multi-machine** | Single DB synced via Git? Separate DBs merged in dashboard? | Separate DBs → GitHub Action merges on deploy |
| **Dashboard Hosting** | GitHub Pages (static) + optional VPS for live API | Start with GitHub Pages, add VPS later if needed |
| **Token Budget Enforcement** | Hard stop at 950? Soft warn at 800? | Hard stop at 950, warn at 800 |
| **Session Granularity** | Per Hermes conversation? Per Aegis task? Per coding session? | Per "work session" (you define via `wt start`) |
| **Git Repos Tracked** | Only `aegis_oobe`? All repos under `~/git/`? | Configurable list in `~/.work-tracker/config.yaml` |

---

## 7. FILES TO CREATE/MODIFY

### New Files (Work Tracker Repo)
```
work-tracker/
├── pyproject.toml
├── src/
│   └── work_tracker/
│       ├── __init__.py
│       ├── client.py          # WorkTrackerClient
│       ├── models.py          # SQLAlchemy/Pydantic models
│       ├── schema.sql         # DDL
│       ├── migrations/        # Alembic or simple versioned SQL
│       ├── cli.py             # Typer CLI
│       ├── collectors/
│       │   ├── __init__.py
│       │   ├── git_collector.py
│       │   └── session_collector.py
│       ├── dashboard/
│       │   ├── api/
│       │   │   ├── main.py
│       │   │   └── routes/
│       │   ├── static/
│       │   │   ├── index.html
│       │   │   ├── app.js
│       │   │   └── style.css
│       │   └── build.py       # Static export
│       └── cron/
│           └── daily_aggregate.py
├── .github/workflows/
│   ├── daily-aggregate.yml
│   └── deploy-pages.yml
└── tests/
```

### Modified Files (Aegis)
```
aegis/
├── lib/
│   ├── __init__.py
│   ├── model_router.py        # NEW: Shared router
│   └── work_tracker/
│       └── client.py          # NEW: Thin wrapper or import from work-tracker
├── agents/oracle/
│   ├── agent.py               # MODIFY: Use ModelRouter
│   └── token_manager.py       # MODIFY: Delegate to ModelRouter
```

### New Files (Hermes Profile)
```
~/.hermes/profiles/default/
├── plugins/
│   └── hermes_model_router.py # NEW: Intercepts completions
├── config.yaml                # MODIFY: Enable plugin
└── model_router_config.yaml   # NEW: Tier chain, budget, tracker DB path
```

---

## 8. EXECUTION ORDER (Dependency Graph)

```
T1.1 → T1.2 → T1.3 → T1.4 → T1.5
                    ↓
         ┌──────────┴──────────┐
         ▼                     ▼
      T1.6                   T1.9
      T1.7                   T1.10
      T1.8                   T1.11
         │                     │
         └──────────┬──────────┘
                    ▼
               T1.12 → T1.13 → T1.14
                    ↓
               T2.1 → T2.2 → T2.3 → T2.4
                    ↓
         ┌──────────┴──────────┐
         ▼                     ▼
      T3.1-T3.5              T3.6-T3.8
         │                     │
         └──────────┬──────────┘
                    ▼
               T3.9 → T3.10
                    ↓
               T4.1-T4.8
```

---

## 9. ESTIMATED EFFORT

| Phase | Tasks | Est. Hours |
|-------|-------|------------|
| 1: Foundation | 14 | 12-16 |
| 2: Automation | 4 | 4-6 |
| 3: Dashboard | 10 | 10-14 |
| 4: Polish | 8 | 8-12 |
| **Total** | **36** | **34-48** |

---

## 10. NEXT STEPS

**Please confirm:**
1. **DB approach**: SQLite local + GitHub Action merge OK?
2. **Dashboard**: GitHub Pages static export + optional live API OK?
3. **OpenRouter**: You'll enable all 6 free models in dashboard?
4. **Session model**: Per `wt start-session` manual, or auto-detect?
5. **Repos to track**: Just `aegis_oobe` for now, configurable later?

**Then I'll execute Phase 1 tasks in order.**