// Mission Control core JavaScript
(function() {
    'use strict';

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    const html = document.documentElement;

    function setTheme(theme) {
        html.classList.remove('light', 'dark');
        html.classList.add(theme);
        localStorage.setItem('theme', theme);
        updateThemeIcon(theme);
    }

    function updateThemeIcon(theme) {
        const sunIcon = document.querySelector('.sun-icon');
        const moonIcon = document.querySelector('.moon-icon');
        if (sunIcon && moonIcon) {
            if (theme === 'dark') {
                sunIcon.style.display = 'block';
                moonIcon.style.display = 'none';
            } else {
                sunIcon.style.display = 'none';
                moonIcon.style.display = 'block';
            }
        }
    }

    function getStoredTheme() {
        return localStorage.getItem('theme') ||
               (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }

    if (themeToggle) {
        // Initialize theme
        setTheme(getStoredTheme());

        themeToggle.addEventListener('click', () => {
            const currentTheme = html.classList.contains('dark') ? 'dark' : 'light';
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });
    }

    // HTMX configuration
    document.body.addEventListener('htmx:configRequest', (evt) => {
        // Add CSRF token if needed
    });

    // Auto-refresh handling
    document.addEventListener('htmx:afterSwap', (evt) => {
        // Re-initialize any components after HTMX swap
        const autoRefreshBtn = document.getElementById('auto-refresh-btn');
        if (autoRefreshBtn && autoRefreshBtn.dataset.auto === 'true') {
            // Auto-refresh is handled by HTMX hx-trigger
        }
    });

    // Chart resize handler
    window.addEventListener('resize', () => {
        if (window.Plotly) {
            document.querySelectorAll('.chart-container').forEach(el => {
                if (el._plotly) {
                    Plotly.Plots.resize(el);
                }
            });
        }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl+Shift+L to toggle theme
        if (e.ctrlKey && e.shiftKey && e.key === 'L') {
            e.preventDefault();
            if (themeToggle) themeToggle.click();
        }
    });

    console.log('Mission Control core initialized');
})();

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {};
}