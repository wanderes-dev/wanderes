(function () {
    const navToggle = document.getElementById("nav-toggle");
    const siteNav = document.getElementById("site-nav");

    // Looked up fresh on every call, rather than captured once at the top
    // alongside navToggle/siteNav - the backdrop element is a plain,
    // static part of the page (not conditionally rendered), so this is
    // purely defensive, but avoids depending on this closure's reference
    // staying valid for the whole page lifetime.
    function getSiteNavBackdrop() {
        return document.getElementById("site-nav-backdrop");
    }

    function closeSiteNav() {
        siteNav.classList.remove("is-open");
        const backdrop = getSiteNavBackdrop();
        if (backdrop) {
            backdrop.classList.remove("is-open");
        }
        navToggle.setAttribute("aria-expanded", "false");
    }

    if (navToggle && siteNav) {
        navToggle.addEventListener("click", function () {
            const isOpen = siteNav.classList.toggle("is-open");
            const backdrop = getSiteNavBackdrop();
            if (backdrop) {
                backdrop.classList.toggle("is-open", isOpen);
            }
            navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });
        const backdrop = getSiteNavBackdrop();
        if (backdrop) {
            backdrop.addEventListener("click", closeSiteNav);
        }
    }

    document.querySelectorAll(".message").forEach(function (message) {
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "message-close";
        closeButton.setAttribute("aria-label", "Dismiss");
        closeButton.textContent = "×";
        closeButton.addEventListener("click", function () {
            message.remove();
        });
        message.appendChild(closeButton);
    });
})();
