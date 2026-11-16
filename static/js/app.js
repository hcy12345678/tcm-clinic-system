(function () {
    'use strict';

    var body = document.body;
    var sidebarToggle = document.getElementById('sidebar-toggle');
    var sidebarOverlay = document.getElementById('sidebar-overlay');
    var mobileQuery = window.matchMedia('(max-width: 991.98px)');

    function updateSidebarButton() {
        if (!sidebarToggle) return;
        var expanded = mobileQuery.matches ? body.classList.contains('sidebar-mobile-open') : !body.classList.contains('sidebar-collapsed');
        sidebarToggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    function closeMobileSidebar() {
        body.classList.remove('sidebar-mobile-open');
        updateSidebarButton();
    }

    if (sidebarToggle) {
        updateSidebarButton();
        sidebarToggle.addEventListener('click', function () {
            if (mobileQuery.matches) {
                body.classList.toggle('sidebar-mobile-open');
            } else {
                body.classList.toggle('sidebar-collapsed');
            }
            updateSidebarButton();
        });
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeMobileSidebar);
    }

    document.querySelectorAll('.sidebar .nav-link').forEach(function (link) {
        link.addEventListener('click', function () {
            if (mobileQuery.matches) closeMobileSidebar();
        });
    });

    function handleViewportChange() {
        body.classList.remove('sidebar-mobile-open');
        updateSidebarButton();
    }

    if (typeof mobileQuery.addEventListener === 'function') {
        mobileQuery.addEventListener('change', handleViewportChange);
    } else if (typeof mobileQuery.addListener === 'function') {
        mobileQuery.addListener(handleViewportChange);
    }

    document.addEventListener('click', function (event) {
        var backButton = event.target.closest('[data-action="back"]');
        if (backButton) {
            event.preventDefault();
            if (window.history.length > 1) {
                window.history.back();
            } else if (backButton.dataset.fallback) {
                window.location.href = backButton.dataset.fallback;
            }
            return;
        }

        var printButton = event.target.closest('[data-action="print"]');
        if (printButton) {
            event.preventDefault();
            window.print();
            return;
        }

        var confirmButton = event.target.closest('[data-confirm]');
        if (confirmButton && !window.confirm(confirmButton.dataset.confirm)) {
            event.preventDefault();
        }
    });
})();
