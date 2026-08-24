# Redis Bus Observability Dashboard - Task List

## Phase 1: Core Infrastructure ✅ COMPLETE
- [x] 1.1 Create directory structure `aegis/web/routes/redis_bus/`
- [x] 1.2 Create `models.py` with Pydantic response models
- [x] 1.3 Create `service.py` with Redis stream inspection logic
- [x] 1.4 Create `router.py` with all API endpoints
- [x] 1.5 Register router in `aegis/web/app.py`
- [x] 1.6 Add Plotly.js via CDN (instead of Chart.js)

## Phase 2: Stream Dashboard UI ✅ COMPLETE
- [x] 2.1 Create base template `redis_bus.html`
- [x] 2.2 Create stream list partial `partials/stream_list.html`
- [x] 2.3 Implement stream cards with stats (length, pending, rate)
- [x] 2.4 Add HTMX polling for real-time updates (10s default)
- [x] 2.5 Add stream detail view with message pagination
- [x] 2.6 Add table view toggle with sorting

## Phase 3: Message Inspection ✅ COMPLETE
- [x] 3.1 Create message list partial with filters
- [x] 3.2 Create message detail modal `partials/message_detail.html`
- [x] 3.3 Implement high-level stats computation per message
- [x] 3.4 Add JSON syntax highlighting for payload (via hljs)
- [x] 3.5 Add token estimation (tiktoken + fallback to chars/4)

## Phase 4: Pipeline Visualization ✅ COMPLETE
- [x] 4.1 Add pipeline state endpoint in service/router
- [x] 4.2 Create pipeline view partial `partials/pipeline_view.html`
- [x] 4.3 Implement stuck/abandoned detection logic
- [x] 4.4 Visual component (funnel chart + stats cards + tables)

## Phase 5: Charts ✅ COMPLETE
- [x] 5.1 Create `charts.py` (integrated into `aegis/web/core/charting.py`) for chart data preparation
- [x] 5.2 Per-message token chart endpoint + component (stacked bar chart)
- [x] 5.3 Cumulative chart endpoint with date range filters (dual-axis area chart)
- [x] 5.4 Date range picker component (presets + custom) `components/date_range_picker.html`
- [x] 5.5 Chart rendering with Plotly.js (interactive, hover cards, clickable drill-down)

## Phase 6: Polish & Integration ✅ COMPLETE
- [x] 6.1 Add navigation link to main dashboard (Redis Bus tab)
- [x] 6.2 Responsive design & mobile support
- [x] 6.3 Error handling & loading states (skeletons, error partials)
- [x] 6.4 Keyboard shortcuts (/, Escape for modals)
- [x] 6.5 Add to Mission Control sidebar navigation (done in base.html)
- [x] 6.6 Dark mode support (via theme toggle)

## Phase 7: Persistence Layer ✅ COMPLETE (Bonus)
- [x] 7.1 Create `storage.py` with SQLite persistence
- [x] 7.2 Implement stream/metric archival
- [x] 7.3 Implement message archival with full query support
- [x] 7.4 Implement pipeline state snapshots
- [x] 7.5 Implement token aggregates persistence
- [x] 7.6 Implement message action audit log
- [x] 7.7 Create background archiver (`ObservabilityArchiver`)
- [x] 7.8 Add History tab with sub-tabs (Messages, Stream Metrics, Pipeline, Tokens, Actions)
- [x] 7.9 Add archiver control (start/stop/status) and maintenance (cleanup)

## Phase 8: Mission Control Core Infrastructure ✅ COMPLETE (Shared)
- [x] 8.1 Create `aegis/web/core/` shared module
- [x] 8.2 Base router with common error handling
- [x] 8.3 Dependencies (bus, config, redis client)
- [x] 8.4 Pagination & filter utilities
- [x] 8.5 Charting utilities (Plotly helpers, themes)
- [x] 8.6 Reusable template partials (loading, error, table, modal, chart_wrapper, stats_card)
- [x] 8.7 Reusable components (date_range_picker, agent_selector, stream_selector)
- [x] 8.8 Shared CSS (`mc-components.css`) with theme support
- [x] 8.9 Core JS (`mc-core.js`) with HTMX, SSE, Charts, Theme, Keyboard shortcuts

## Testing
- [ ] T1 Unit tests for service layer
- [ ] T2 Integration tests for API endpoints
- [ ] T3 E2E test for dashboard flow

---

## File Creation Summary

### Core Module (`aegis/web/core/`)
1. `aegis/web/core/__init__.py`
2. `aegis/web/core/dependencies.py`
3. `aegis/web/core/pagination.py`
4. `aegis/web/core/filters.py`
5. `aegis/web/core/charting.py`
6. `aegis/web/core/base_router.py`
7. `aegis/web/core/static/css/mc-components.css`
8. `aegis/web/core/static/js/mc-core.js`
9. `aegis/web/core/templates/partials/loading.html`
10. `aegis/web/core/templates/partials/error.html`
11. `aegis/web/core/templates/partials/table.html`
12. `aegis/web/core/templates/partials/modal.html`
13. `aegis/web/core/templates/partials/chart_wrapper.html`
14. `aegis/web/core/templates/partials/stats_card.html`
15. `aegis/web/core/templates/components/date_range_picker.html`
16. `aegis/web/core/templates/components/agent_selector.html`
17. `aegis/web/core/templates/components/stream_selector.html`

### Redis Bus Module (`aegis/web/routes/redis_bus/`)
18. `aegis/web/routes/redis_bus/__init__.py`
19. `aegis/web/routes/redis_bus/models.py`
20. `aegis/web/routes/redis_bus/service.py`
21. `aegis/web/routes/redis_bus/storage.py`
22. `aegis/web/routes/redis_bus/router.py`
23. `aegis/web/routes/redis_bus/templates/redis_bus.html`
24. `aegis/web/routes/redis_bus/templates/partials/stream_list.html`
25. `aegis/web/routes/redis_bus/templates/partials/stream_detail.html`
26. `aegis/web/routes/redis_bus/templates/partials/message_detail.html`
27. `aegis/web/routes/redis_bus/templates/partials/pipeline_view.html`
28. `aegis/web/routes/redis_bus/templates/partials/token_chart.html`
29. `aegis/web/routes/redis_bus/templates/partials/cumulative_chart.html`
30. `aegis/web/routes/redis_bus/templates/partials/overview_stats.html`

### Updates
31. `aegis/web/app.py` - Added redis_bus router import and registration
32. `aegis/web/templates/base.html` - Added Redis Bus nav tab, Plotly.js CDN, mc-components.css, mc-core.js, theme toggle

### Documentation
33. `build_chunks/SPEC_REDIS_BUS_OBSERVABILITY.md`
34. `build_chunks/TASKS_REDIS_BUS_OBSERVABILITY.md` (this file)

---

## Next Steps (Future Enhancements)

1. **Unit/Integration Tests** - Add pytest tests for service layer and API endpoints
2. **WebSocket Support** - Upgrade from polling/SSE to WebSocket for true real-time
3. **Alert Rules** - Configurable alerts (pending > threshold, error rate spike, etc.)
4. **Export/Reporting** - CSV/JSON export, scheduled reports
5. **Dead Letter Queue UI** - Separate tab for failed messages with replay
6. **Correlation ID Tracer** - Visual trace view across all streams
7. **Distributed Tracing** - OpenTelemetry integration
8. **Message Schema Validation** - Show schema violations in message detail
9. **Performance Optimization** - Query optimization, caching for large datasets
10. **Multi-tenant Isolation** - Ensure tenant data isolation in queries