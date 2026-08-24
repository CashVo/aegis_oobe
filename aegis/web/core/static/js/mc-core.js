// aegis/web/core/static/js/mc-core.js
// Mission Control Core JavaScript Utilities

(function() {
    'use strict';

    // ============================================
    // Global Mission Control Namespace
    // ============================================
    window.MC = window.MC || {};

    // ============================================
    // Configuration
    // ============================================
    MC.config = {
        apiBase: '/api',
        wsBase: '/ws',
        defaultPageSize: 50,
        maxPageSize: 500,
        pollInterval: 5000,
        chartDefaults: {
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d', 'select2d', 'autoScale2d'],
        },
    };

    // ============================================
    // Utility Functions
    // ============================================
    MC.util = {
        // Format numbers with commas
        formatNumber: function(num, decimals = 0) {
            if (num === null || num === undefined || isNaN(num)) return '—';
            return new Intl.NumberFormat('en-US', {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals,
            }).format(num);
        },

        // Format bytes
        formatBytes: function(bytes, decimals = 1) {
            if (bytes === null || bytes === undefined) return '—';
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
        },

        // Format duration in ms
        formatDuration: function(ms) {
            if (ms === null || ms === undefined) return '—';
            if (ms < 1000) return Math.round(ms) + ' ms';
            if (ms < 60000) return (ms / 1000).toFixed(1) + ' s';
            if (ms < 3600000) return (ms / 60000).toFixed(1) + ' m';
            return (ms / 3600000).toFixed(1) + ' h';
        },

        // Format date/time
        formatDateTime: function(date, options = {}) {
            if (!date) return '—';
            const d = date instanceof Date ? date : new Date(date);
            if (isNaN(d.getTime())) return 'Invalid date';
            return new Intl.DateTimeFormat('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
                ...options,
            }).format(d);
        },

        // Format relative time
        formatRelative: function(date) {
            if (!date) return '—';
            const d = date instanceof Date ? date : new Date(date);
            if (isNaN(d.getTime())) return 'Invalid date';
            const diff = Date.now() - d.getTime();
            const abs = Math.abs(diff);
            const isPast = diff > 0;

            if (abs < 60000) return isPast ? 'just now' : 'in a moment';
            if (abs < 3600000) return isPast ? Math.round(abs / 60000) + 'm ago' : 'in ' + Math.round(abs / 60000) + 'm';
            if (abs < 86400000) return isPast ? Math.round(abs / 3600000) + 'h ago' : 'in ' + Math.round(abs / 3600000) + 'h';
            if (abs < 604800000) return isPast ? Math.round(abs / 86400000) + 'd ago' : 'in ' + Math.round(abs / 86400000) + 'd';
            return this.formatDateTime(d, { hour: undefined, minute: undefined, second: undefined });
        },

        // Debounce function
        debounce: function(fn, delay) {
            let timeoutId;
            return function(...args) {
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => fn.apply(this, args), delay);
            };
        },

        // Throttle function
        throttle: function(fn, limit) {
            let inThrottle;
            return function(...args) {
                if (!inThrottle) {
                    fn.apply(this, args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        },

        // Deep clone
        clone: function(obj) {
            return JSON.parse(JSON.stringify(obj));
        },

        // Get nested property
        get: function(obj, path, defaultValue) {
            return path.split('.').reduce((o, k) => (o || {})[k], obj) ?? defaultValue;
        },

        // Generate unique ID
        uid: function(prefix = '') {
            return prefix + Math.random().toString(36).substr(2, 9);
        },

        // Parse query string
        parseQuery: function(queryString) {
            const params = new URLSearchParams(queryString);
            const result = {};
            for (const [key, value] of params) {
                if (result[key]) {
                    if (!Array.isArray(result[key])) result[key] = [result[key]];
                    result[key].push(value);
                } else {
                    result[key] = value;
                }
            }
            return result;
        },

        // Build query string
        buildQuery: function(params) {
            const searchParams = new URLSearchParams();
            Object.entries(params).forEach(([key, value]) => {
                if (value !== null && value !== undefined && value !== '') {
                    if (Array.isArray(value)) {
                        value.forEach(v => searchParams.append(key, v));
                    } else {
                        searchParams.set(key, value);
                    }
                }
            });
            return searchParams.toString();
        },

        // Copy to clipboard
        copyToClipboard: async function(text) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (e) {
                // Fallback
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                return true;
            }
        },

        // Show toast notification
        toast: function(message, type = 'info', delay = 5000) {
            const id = 'toast-' + this.uid();
            const toastHtml = `
                <div class="toast align-items-center text-bg-${type} border-0" id="${id}" role="alert" aria-live="assertive" aria-atomic="true" data-bs-autohide="true" data-bs-delay="${delay}" style="position: fixed; top: 1rem; right: 1rem; z-index: 1080;">
                    <div class="d-flex">
                        <div class="toast-body">${this.escapeHtml(message)}</div>
                        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', toastHtml);
            const toastEl = document.getElementById(id);
            if (window.bootstrap && bootstrap.Toast) {
                new bootstrap.Toast(toastEl).show();
            }
            toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
        },

        escapeHtml: function(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },

        // Get CSRF token from meta tag
        getCsrfToken: function() {
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? meta.content : null;
        },
    };

    // ============================================
    // HTMX Extensions & Helpers
    // ============================================
    MC.htmx = {
        // Trigger HTMX request programmatically
        trigger: function(element, eventType = 'click') {
            if (typeof htmx !== 'undefined') {
                htmx.trigger(element, eventType);
            } else {
                element.dispatchEvent(new Event(eventType, { bubbles: true }));
            }
        },

        // Find closest HTMX target
        findTarget: function(element, selector) {
            return element.closest(selector) || document.querySelector(selector);
        },

        // Swap content manually
        swap: function(target, html, swapStyle = 'innerHTML') {
            if (typeof htmx !== 'undefined') {
                htmx.swap(target, html, swapStyle);
            } else {
                switch (swapStyle) {
                    case 'innerHTML': target.innerHTML = html; break;
                    case 'outerHTML': target.outerHTML = html; break;
                    case 'beforebegin': target.insertAdjacentHTML('beforebegin', html); break;
                    case 'afterbegin': target.insertAdjacentHTML('afterbegin', html); break;
                    case 'beforeend': target.insertAdjacentHTML('beforeend', html); break;
                    case 'afterend': target.insertAdjacentHTML('afterend', html); break;
                }
            }
        },

        // Add request headers
        addHeaders: function(headers) {
            if (typeof htmx !== 'undefined') {
                htmx.config.defaultHeaders = { ...htmx.config.defaultHeaders, ...headers };
            }
        },

        // Handle HTMX events
        on: function(event, handler) {
            document.body.addEventListener(event, handler);
        },

        off: function(event, handler) {
            document.body.removeEventListener(event, handler);
        },
    };

    // ============================================
    // SSE (Server-Sent Events) Manager
    // ============================================
    MC.sse = {
        connections: new Map(),

        connect: function(url, options = {}) {
            if (this.connections.has(url)) {
                return this.connections.get(url);
            }

            const eventSource = new EventSource(url);
            const handlers = new Map();

            eventSource.onopen = () => {
                this.emit('open', url);
                if (options.onOpen) options.onOpen();
            };

            eventSource.onerror = (err) => {
                this.emit('error', url, err);
                if (options.onError) options.onError(err);
            };

            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.emit('message', url, data);
                    if (options.onMessage) options.onMessage(data);
                } catch (e) {
                    this.emit('message', url, event.data);
                    if (options.onMessage) options.onMessage(event.data);
                }
            };

            // Named event listeners
            if (options.events) {
                Object.entries(options.events).forEach(([eventName, handler]) => {
                    eventSource.addEventListener(eventName, (event) => {
                        try {
                            const data = JSON.parse(event.data);
                            handler(data);
                        } catch (e) {
                            handler(event.data);
                        }
                    });
                });
            }

            const connection = {
                url,
                eventSource,
                handlers,
                close: () => {
                    eventSource.close();
                    this.connections.delete(url);
                    this.emit('close', url);
                },
                on: (event, handler) => {
                    if (!handlers.has(event)) handlers.set(event, []);
                    handlers.get(event).push(handler);
                },
                off: (event, handler) => {
                    if (handlers.has(event)) {
                        const idx = handlers.get(event).indexOf(handler);
                        if (idx > -1) handlers.get(event).splice(idx, 1);
                    }
                },
            };

            this.connections.set(url, connection);
            return connection;
        },

        disconnect: function(url) {
            const conn = this.connections.get(url);
            if (conn) {
                conn.close();
            }
        },

        disconnectAll: function() {
            this.connections.forEach(conn => conn.close());
            this.connections.clear();
        },

        emit: function(event, ...args) {
            this.connections.forEach(conn => {
                if (conn.handlers.has(event)) {
                    conn.handlers.get(event).forEach(handler => handler(...args));
                }
            });
        },

        get: function(url) {
            return this.connections.get(url);
        },
    };

    // ============================================
    // Chart Manager (Plotly.js)
    // ============================================
    MC.charts = {
        instances: new Map(),

        // Render a chart in a container
        render: function(containerId, figureJson, config = {}) {
            const container = document.getElementById(containerId);
            if (!container) {
                console.warn('Chart container not found:', containerId);
                return null;
            }

            const plotDiv = container.querySelector('.chart-plot') || container;
            const loadingDiv = container.querySelector('.chart-loading');

            const finalConfig = { ...MC.config.chartDefaults, ...config };

            try {
                const figure = typeof figureJson === 'string' ? JSON.parse(figureJson) : figureJson;

                // Apply theme
                const themedFigure = this.applyTheme(figure);

                // Hide loading
                if (loadingDiv) loadingDiv.style.display = 'none';

                // Render with Plotly
                if (window.Plotly) {
                    return window.Plotly.newPlot(plotDiv, themedFigure.data, themedFigure.layout, finalConfig)
                        .then(gd => {
                            this.instances.set(containerId, gd);
                            this.attachClickHandler(containerId, gd);
                            return gd;
                        })
                        .catch(err => {
                            console.error('Chart render error:', err);
                            if (loadingDiv) {
                                loadingDiv.innerHTML = '<div class="text-danger p-3">Failed to render chart</div>';
                                loadingDiv.style.display = 'flex';
                            }
                        });
                } else {
                    // Wait for Plotly to load
                    window.addEventListener('plotly:ready', () => this.render(containerId, figureJson, config), { once: true });
                }
            } catch (e) {
                console.error('Chart parse error:', e);
            }
        },

        applyTheme: function(figure) {
            const isDark = document.documentElement.classList.contains('dark') ||
                          window.matchMedia('(prefers-color-scheme: dark)').matches;

            const fig = MC.util.clone(figure);
            fig.layout = fig.layout || {};

            if (isDark) {
                fig.layout.template = 'plotly_dark';
                fig.layout.plot_bgcolor = 'rgba(0,0,0,0)';
                fig.layout.paper_bgcolor = 'rgba(0,0,0,0)';
                fig.layout.font = fig.layout.font || {};
                fig.layout.font.color = '#e0e0e0';
            } else {
                fig.layout.plot_bgcolor = 'rgba(0,0,0,0)';
                fig.layout.paper_bgcolor = 'rgba(0,0,0,0)';
                fig.layout.font = fig.layout.font || {};
                fig.layout.font.color = '#212529';
            }

            return fig;
        },

        attachClickHandler: function(containerId, gd) {
            gd.on('plotly_click', (data) => {
                const point = data.points[0];
                if (point && point.customdata) {
                    window.dispatchEvent(new CustomEvent('chart:click', {
                        detail: { chartId: containerId, point }
                    }));
                }
            });
        },

        // Update chart data
        update: function(containerId, update) {
            const gd = this.instances.get(containerId);
            if (gd && window.Plotly) {
                return window.Plotly.update(gd, update.data, update.layout, update.config);
            }
        },

        // Relayout chart (for theme changes)
        relayout: function(containerId, layout) {
            const gd = this.instances.get(containerId);
            if (gd && window.Plotly) {
                return window.Plotly.relayout(gd, layout);
            }
        },

        // Resize chart
        resize: function(containerId) {
            const gd = this.instances.get(containerId);
            if (gd && window.Plotly) {
                window.Plotly.Plots.resize(gd);
            }
        },

        // Destroy chart
        destroy: function(containerId) {
            const gd = this.instances.get(containerId);
            if (gd && window.Plotly) {
                window.Plotly.purge(gd);
                this.instances.delete(containerId);
            }
        },

        // Resize all charts
        resizeAll: function() {
            this.instances.forEach((gd, id) => this.resize(id));
        },

        // Re-theme all charts
        rethemeAll: function() {
            this.instances.forEach((gd, id) => {
                // Re-render with current data to apply theme
                this.render(id, { data: gd.data, layout: gd.layout });
            });
        },
    };

    // ============================================
    // Table Enhancement
    // ============================================
    MC.tables = {
        init: function(tableSelector) {
            const tables = document.querySelectorAll(tableSelector);
            tables.forEach(table => this.enhance(table));
        },

        enhance: function(table) {
            if (table.dataset.mcEnhanced) return;
            table.dataset.mcEnhanced = 'true';

            // Add sort handlers
            const sortableHeaders = table.querySelectorAll('th.sortable');
            sortableHeaders.forEach(th => {
                th.style.cursor = 'pointer';
                th.addEventListener('click', (e) => {
                    if (e.target.closest('button, a, input, select')) return;
                    const sortKey = th.dataset.sort;
                    const currentSort = new URLSearchParams(window.location.search).get('sort');
                    const currentDir = new URLSearchParams(window.location.search).get('sort_dir') || 'asc';
                    const newDir = currentSort === sortKey && currentDir === 'asc' ? 'desc' : 'asc';

                    const url = new URL(window.location.href);
                    url.searchParams.set('sort', sortKey);
                    url.searchParams.set('sort_dir', newDir);
                    url.searchParams.set('page', '1');

                    if (typeof htmx !== 'undefined') {
                        htmx.ajax('GET', url.toString(), { target: '#table-container', swap: 'innerHTML' });
                    } else {
                        window.location.href = url.toString();
                    }
                });
            });

            // Row click handling
            const clickableRows = table.querySelectorAll('tr.clickable-row');
            clickableRows.forEach(row => {
                row.addEventListener('click', (e) => {
                    if (e.target.closest('button, a, .action-menu, .action-item, input, select')) return;
                    const url = row.getAttribute('hx-get');
                    if (url) {
                        MC.htmx.trigger(row, 'click');
                    }
                });
            });
        },
    };

    // ============================================
    // Modal Manager
    // ============================================
    MC.modals = {
        open: function(modalId, contentUrl, options = {}) {
            const modalEl = document.getElementById(modalId);
            if (!modalEl) return;

            const body = modalEl.querySelector('.modal-body');
            if (body && contentUrl) {
                // Show loading
                body.innerHTML = '<div class="d-flex align-items-center justify-content-center p-5"><div class="spinner spinner-md"></div></div>';

                // Load content via HTMX
                if (typeof htmx !== 'undefined') {
                    htmx.ajax('GET', contentUrl, {
                        target: body,
                        swap: 'innerHTML',
                        headers: options.headers,
                    });
                } else {
                    fetch(contentUrl, { headers: options.headers })
                        .then(r => r.text())
                        .then(html => { body.innerHTML = html; });
                }
            }

            if (window.bootstrap && bootstrap.Modal) {
                const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.show();
            }
        },

        close: function(modalId) {
            const modalEl = document.getElementById(modalId);
            if (modalEl && window.bootstrap && bootstrap.Modal) {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
            }
        },
    };

    // ============================================
    // Theme Management
    // ============================================
    MC.theme = {
        init: function() {
            // Check for saved theme or system preference
            const saved = localStorage.getItem('mc-theme');
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

            if (saved) {
                this.set(saved);
            } else if (prefersDark) {
                this.set('dark');
            }

            // Listen for system changes
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (!localStorage.getItem('mc-theme')) {
                    this.set(e.matches ? 'dark' : 'light');
                }
            });
        },

        get: function() {
            return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
        },

        set: function(theme) {
            if (theme === 'dark') {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
            localStorage.setItem('mc-theme', theme);

            // Re-theme charts
            MC.charts.rethemeAll();

            // Dispatch event
            window.dispatchEvent(new CustomEvent('theme:change', { detail: { theme } }));
        },

        toggle: function() {
            this.set(this.get() === 'dark' ? 'light' : 'dark');
        },
    };

    // ============================================
    // Keyboard Shortcuts
    // ============================================
    MC.shortcuts = {
        bindings: new Map(),

        register: function(key, handler, options = {}) {
            const normalized = key.toLowerCase();
            this.bindings.set(normalized, { handler, options });
        },

        unregister: function(key) {
            this.bindings.delete(key.toLowerCase());
        },

        handle: function(e) {
            // Don't trigger in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
                return;
            }

            const key = [
                e.ctrlKey ? 'ctrl' : '',
                e.metaKey ? 'meta' : '',
                e.altKey ? 'alt' : '',
                e.shiftKey ? 'shift' : '',
                e.key.toLowerCase()
            ].filter(Boolean).join('+');

            const binding = this.bindings.get(key);
            if (binding) {
                if (!binding.options.allowInInput || !(e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
                    e.preventDefault();
                    binding.handler(e);
                }
            }
        },

        init: function() {
            document.addEventListener('keydown', (e) => this.handle(e));

            // Default shortcuts
            this.register('/', () => {
                const search = document.querySelector('[data-search-input]');
                if (search) search.focus();
            }, { description: 'Focus search' });

            this.register('escape', () => {
                // Close any open modal
                document.querySelectorAll('.modal.show').forEach(m => MC.modals.close(m.id));
            }, { description: 'Close modal' });
        },
    };

    // ============================================
    // Auto-initialization
    // ============================================
    document.addEventListener('DOMContentLoaded', () => {
        MC.theme.init();
        MC.shortcuts.init();
        MC.tables.init('.data-table');

        // Signal Plotly ready
        if (window.Plotly) {
            window.dispatchEvent(new CustomEvent('plotly:ready'));
        }
    });

    // Handle HTMX content swap for new elements
    document.body.addEventListener('htmx:afterSwap', (e) => {
        MC.tables.init(e.detail.target.querySelectorAll('.data-table'));
        e.detail.target.querySelectorAll('[data-chart-id]').forEach(el => {
            const chartId = el.dataset.chartId;
            const figureJson = el.dataset.chartData;
            const config = JSON.parse(el.dataset.chartConfig || '{}');
            MC.charts.render(chartId, figureJson, config);
        });
    });

    // Cleanup SSE on page unload
    window.addEventListener('beforeunload', () => {
        MC.sse.disconnectAll();
    });

})();

// Export for modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.MC;
}