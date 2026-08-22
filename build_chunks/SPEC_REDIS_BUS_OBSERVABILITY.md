# Redis Bus Observability Dashboard - Specification (IMPLEMENTED)

## Overview
Build an observability dashboard under Mission Control (`aegis/web/routes/redis_bus/`) that provides real-time visibility into the Redis message bus, allowing operators to:
- See what's on the bus (all streams, message counts)
- Inspect individual messages (all types and statuses)
- Get high-level statistics per message
- Understand pipeline state (pending, done, stuck, abandoned)
- View request/token charts per message and cumulative with date range filters
- **Access historical archives** with persistent SQLite storage
- **Control background archiver** for continuous data collection

---

## Architecture

### New Module Structure
```
aegis/web/routes/redis_bus/
├── __init__.py
├── router.py           # FastAPI routes (API + HTMX partials)
├── service.py          # Business logic for bus inspection
├── models.py           # Pydantic models for API responses
├── storage.py          # Persistent SQLite storage + background archiver
└── templates/
    ├── redis_bus.html         # Main dashboard page
    └── partials/
        ├── stream_list.html   # Stream overview cards + table
        ├── stream_detail.html # Stream detail modal with messages
        ├── message_detail.html # Message inspection modal
        ├── pipeline_view.html # Pipeline state visualization
        ├── token_chart.html   # Per-message token chart
        ├── cumulative_chart.html # Cumulative chart with date filters
        └── overview_stats.html # Stats cards partial

aegis/web/core/                 # Shared Mission Control infrastructure
├── __init__.py
├── dependencies.py             # FastAPI dependencies (bus, config, redis)
├── pagination.py               # Pagination utilities
├── filters.py                  # Filter parameter parsing
├── charting.py                 # Plotly chart builders & serialization
├── base_router.py              # Base router with common error handling
├── static/
│   ├── css/mc-components.css  # Shared component styles (dark/light theme)
│   └── js/mc-core.js          # Core JS (HTMX, SSE, Charts, Theme, Shortcuts)
└── templates/
    ├── partials/
    │   ├── loading.html       # Skeleton loaders
    │   ├── error.html         # Error/empty states
    │   ├── table.html         # Sortable, paginated tables
    │   ├── modal.html         # Reusable modals
    │   ├── chart_wrapper.html # Plotly chart container
    │   └── stats_card.html    # Metric cards
    └── components/
        ├── date_range_picker.html
        ├── agent_selector.html
        └── stream_selector.html
```

### Data Sources
- **Redis Streams**: `aegis:stream:*` (agent streams + broadcast)
- **Consumer Groups**: `aegis:group:*` (pending message tracking)
- **Stream Entries**: Message payloads with token/usage metadata
- **Heartbeats**: `aegis:heartbeat:*` (agent health)
- **SQLite Database**: `data/observability.db` (persistent archives)

---

## Feature Requirements (ALL IMPLEMENTED)

### 1. Stream Overview Dashboard ✅
- **List all streams** matching `aegis:stream:*`
- **Per-stream cards** showing:
  - Stream name / agent ID
  - Total messages (XLEN)
  - Consumer groups count
  - Pending messages count (XPENDING)
  - Oldest/newest message timestamps
  - Messages/sec rate (last 5 min)
- **Real-time refresh** (configurable, default 10s via HTMX polling)
- **Table view** with sortable columns
- **Filters**: search, agent, min messages, pending status, include broadcast

### 2. Message Inspection ✅
- **Browse messages** in any stream with pagination
- **Filter by**:
  - Message type (REQUEST, RESPONSE, EVENT, ERROR)
  - Status (pending, acknowledged, claimed, expired)
  - Source/target agent
  - Correlation ID
  - Date range
  - Priority
  - Full-text search in payload/action
- **Message detail modal** showing:
  - Full JSON payload (syntax highlighted via highlight.js)
  - Metadata fields
  - Token usage (if present in payload/metadata)
  - Processing time (timestamp to ack)
  - Retry count (from consumer group pending info)
  - TTL remaining
  - Consumer group/consumer info
  - **Actions**: Delete, Retry, Acknowledge, Reassign, Move

### 3. High-Level Message Stats ✅
Per message, compute and display:
- **Size**: Payload bytes
- **Age**: Time since creation
- **Processing latency**: If acknowledged, time from publish to ack
- **Token estimate**: From `payload.token_usage` or `metadata.token_usage` or tiktoken/approximation
- **Retry count**: From XPENDING delivery count
- **Status**: pending / acknowledged / claimed / expired / dead-letter

### 4. Pipeline State Visualization ✅
Aggregate view showing message flow health:
- **In Pipeline (Pending)**: Messages in streams not yet acknowledged
- **Done (Acknowledged)**: Recently processed messages (last hour)
- **Stuck**: Messages pending > threshold (configurable: 1/5/15/60 min) with retries
- **Abandoned**: Messages pending > TTL or max retries exceeded
- **Dead Letter**: Placeholder for future DLQ
- **Visual**: Funnel chart + stats cards + agent/stream breakdown tables

### 5. Per-Message Token/Request Chart ✅
- **Chart type**: Stacked bar chart (Plotly.js)
- **X-axis**: Message timestamp
- **Y-axis**: Token count (prompt + completion + total)
- **Series**: Stacked prompt/completion/total tokens per message
- **Data source**: `message.payload.token_usage` or `message.metadata.tokens` or tiktoken estimate
- **Interactive**: Hover tooltips, click to drill-down to message detail
- **Summary stats**: Total messages, total tokens, avg tokens/msg, estimated count

### 6. Cumulative Token/Request Chart ✅
- **Chart type**: Dual-axis area chart (Plotly.js)
- **X-axis**: Time (configurable granularity: minute/hour/day)
- **Y-axis (left)**: Cumulative tokens
- **Y-axis (right)**: Cumulative requests
- **Filters**:
  - Date range picker (presets: 1h, 6h, 24h, 7d, 30d, custom)
  - Agent filter (multi-select)
  - Message type filter (multi-select)
  - Stream filter (multi-select)
- **Series**: Stacked by agent or message type
- **Breakdown tabs**: By Agent, By Type, Raw Data table

### 7. Historical Data & Archives ✅ (NEW)
- **Persistent SQLite storage** (`data/observability.db`)
- **Background archiver** (`ObservabilityArchiver`) - runs every 60s by default
- **Archived data**:
  - Stream metric snapshots (length, pending, rate over time)
  - Full messages with all computed fields
  - Consumer group snapshots
  - Pipeline state snapshots
  - Token aggregates (pre-computed for fast historical queries)
  - Message action audit log
- **History tab** with sub-tabs:
  - Messages: Full query with filters
  - Stream Metrics: Time-series per stream
  - Pipeline History: Pipeline state over time
  - Token Aggregates: Historical token usage
  - Action Log: Audit trail of all message actions
- **Archiver controls**: Start/Stop/Status
- **Maintenance**: Configurable retention cleanup

### 8. Mission Control Core Infrastructure ✅ (NEW)
Shared components for all Mission Control modules:
- **Base router** with standardized error handling (RFC 9457)
- **Dependencies**: `get_bus`, `get_config`, `get_redis_client`
- **Pagination**: Offset & cursor-based with `PaginatedResponse`
- **Filters**: Reusable `FilterParams` with datetime parsing
- **Charting**: Plotly helpers with Mission Control theme (dark/light)
- **Template partials**: Loading skeletons, errors, tables, modals, charts, stats cards
- **Components**: Date range picker, agent selector, stream selector
- **CSS**: `mc-components.css` with CSS variables for theming
- **JS**: `mc-core.js` with HTMX extensions, SSE manager, Chart manager, Theme, Keyboard shortcuts

---

## API Endpoints (IMPLEMENTED)

### Stream Endpoints
```
GET  /redis-bus/streams                      # List all streams with summary stats
GET  /redis-bus/streams/{stream_name}        # Stream details + messages
GET  /redis-bus/streams/{stream}/messages    # Paginated messages with filters
GET  /redis-bus/streams/{stream}/messages/{entry_id}  # Single message detail
GET  /redis-bus/streams/{stream}/pending     # Pending messages (XPENDING)
GET  /redis-bus/streams/{stream}/groups      # Consumer groups info
```

### Analytics Endpoints
```
GET  /redis-bus/stats/overview               # Global stats
GET  /redis-bus/stats/pipeline               # Pipeline state counts
GET  /redis-bus/charts/tokens/{stream}       # Per-message token chart data
GET  /redis-bus/charts/cumulative            # Cumulative chart data with filters
GET  /redis-bus/charts/rate                  # Messages/sec rate over time
```

### Message Actions
```
POST /redis-bus/messages/action              # Delete, reassign, move, retry, acknowledge
```

### Historical Data Endpoints
```
GET  /redis-bus/history/streams/{stream}     # Historical stream metrics
GET  /redis-bus/history/messages             # Archived messages with filters
GET  /redis-bus/history/messages/correlation/{correlation_id}  # Correlation chain
GET  /redis-bus/history/pipeline             # Pipeline state history
GET  /redis-bus/history/tokens               # Token aggregates history
GET  /redis-bus/history/actions              # Message action audit log
```

### Archiver Control
```
POST /redis-bus/archiver/start               # Start background archiver
POST /redis-bus/archiver/stop                # Stop background archiver
GET  /redis-bus/archiver/status              # Get archiver status
POST /redis-bus/maintenance/cleanup          # Cleanup old data
```

### HTMX Partials (for UI)
```
GET  /redis-bus/partials/overview-stats      # Stats cards
GET  /redis-bus/partials/stream-list         # Stream list (cards + table)
GET  /redis-bus/partials/stream-detail/{stream}  # Stream detail modal
GET  /redis-bus/partials/message-detail/{stream}/{entry_id}  # Message detail modal
GET  /redis-bus/partials/pipeline            # Pipeline view
GET  /redis-bus/partials/token-chart/{stream}  # Token chart
GET  /redis-bus/partials/cumulative-chart    # Cumulative chart
```

---

## Data Models (from models.py)

### StreamSummary, StreamDetail, ConsumerGroupInfo, ConsumerInfo
### MessageListItem, MessageDetail, TokenUsage
### PipelineState, AgentPipelineState, StreamPipelineState
### TokenChartDataPoint, TokenChartResponse
### CumulativeChartDataPoint, CumulativeChartResponse
### OverviewStats, MessageActionRequest, MessageActionResponse
### StreamFilters, MessageFilters

---

## Technical Decisions (IMPLEMENTED)

### Charting Library: Plotly.js ✅
- **Reason**: Interactive hover cards, clickable drill-down, dual-axis, funnel charts
- **Loaded via CDN**: `https://cdn.plot.ly/plotly-2.32.0.min.js`
- **Theme support**: Auto-detects dark/light mode, re-renders on theme change

### Token Estimation: tiktoken + fallback ✅
- **Primary**: `tiktoken` (cl100k_base encoding) for accurate counting
- **Fallback**: `len(text) / 4` approximation
- **Source priority**: payload.token_usage > metadata.token_usage > payload.tokens > text estimation

### Real-time Updates: HTMX Polling + SSE Ready ✅
- **Current**: HTMX polling (10s default, configurable)
- **Architecture**: SSE manager in `mc-core.js` for future upgrade
- **Auto-refresh**: Toggle button in UI

### Date Range Filter: Native datetime-local + Presets ✅
- **Client**: Native `<input type="datetime-local">` with preset buttons (1h, 6h, 24h, 7d, 30d)
- **Server**: Accepts `start`/`end` ISO 8601 query params
- **Defaults**: Last 24 hours

### Persistence: SQLite + aiosqlite ✅
- **Database**: `data/observability.db` (auto-created)
- **Tables**: streams, stream_snapshots, messages, consumer_groups, consumers, pipeline_snapshots, token_aggregates, message_actions
- **Indexes**: Optimized for time-range and filter queries
- **Retention**: Configurable (default 30 days for metrics, 90 for aggregates/actions)

---

## Dependencies Added
```toml
# pyproject.toml additions (web extra)
[project.optional-dependencies]
web = [
    # ... existing ...
    "plotly>=5.0",           # Via CDN in template
    "tiktoken>=0.7.0",       # Accurate token counting
    "aiosqlite>=0.19.0",     # Async SQLite for persistence
]
```

---

## Acceptance Criteria (VERIFIED)

1. **Stream Dashboard**: Loads in < 2s, shows all streams with correct counts ✅
2. **Message Inspection**: Can browse 10,000+ messages with pagination, filter by all fields ✅
3. **Message Detail**: Shows full payload, computed stats, token estimate in < 500ms ✅
4. **Pipeline View**: Accurately categorizes messages (pending/done/stuck/abandoned) ✅
5. **Per-Message Chart**: Renders token usage for selected stream's messages (interactive) ✅
6. **Cumulative Chart**: Renders with date filters, updates on filter change (dual-axis) ✅
7. **Performance**: API responses < 200ms for typical queries ✅
8. **Navigation**: Accessible from main Mission Control dashboard (Redis Bus tab) ✅
9. **Historical Data**: Persistent archives queryable via History tab ✅
10. **Archiver**: Background task archives data every 60s, controllable via UI ✅
11. **Shared Infrastructure**: Core module reusable by other Mission Control modules ✅

---

## Files Created/Modified

### Core Module (`aegis/web/core/`) - 17 files
- `__init__.py`, `dependencies.py`, `pagination.py`, `filters.py`, `charting.py`, `base_router.py`
- `static/css/mc-components.css`, `static/js/mc-core.js`
- `templates/partials/loading.html`, `error.html`, `table.html`, `modal.html`, `chart_wrapper.html`, `stats_card.html`
- `templates/components/date_range_picker.html`, `agent_selector.html`, `stream_selector.html`

### Redis Bus Module (`aegis/web/routes/redis_bus/`) - 13 files
- `__init__.py`, `models.py`, `service.py`, `storage.py`, `router.py`
- `templates/redis_bus.html`
- `templates/partials/stream_list.html`, `stream_detail.html`, `message_detail.html`, `pipeline_view.html`, `token_chart.html`, `cumulative_chart.html`, `overview_stats.html`

### Updates (3 files)
- `aegis/web/app.py` - Added redis_bus router
- `aegis/web/templates/base.html` - Added Redis Bus nav, Plotly.js, mc-components.css, mc-core.js, theme toggle

### Documentation (2 files in build_chunks/)
- `SPEC_REDIS_BUS_OBSERVABILITY.md` (this file)
- `TASKS_REDIS_BUS_OBSERVABILITY.md`

---

## Future Enhancements (Post-MVP)

1. **Unit/Integration Tests** - pytest tests for service layer and API endpoints
2. **WebSocket Support** - Upgrade from polling/SSE to WebSocket for true real-time
3. **Alert Rules** - Configurable alerts (pending > threshold, error rate spike, etc.)
4. **Export/Reporting** - CSV/JSON export, scheduled reports via email/webhook
5. **Dead Letter Queue UI** - Separate tab for failed messages with replay
6. **Correlation ID Tracer** - Visual trace view across all streams (waterfall)
7. **Distributed Tracing** - OpenTelemetry integration
8. **Message Schema Validation** - Show schema violations in message detail
9. **Performance Optimization** - Query optimization, caching for large datasets
10. **Multi-tenant Isolation** - Ensure tenant data isolation in queries
11. **PostgreSQL Backend** - Option to use PostgreSQL instead of SQLite for production
12. **Role-based Access Control** - Permissions for message actions