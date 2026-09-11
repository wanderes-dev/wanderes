(function () {
    const navToggle = document.getElementById("nav-toggle");
    const siteNav = document.getElementById("site-nav");

    // Looked up fresh each call instead of cached with navToggle/siteNav
    // above - the backdrop is a static part of the page, not
    // conditionally rendered, so this is mostly defensive.
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

    // Starts [hidden] server-side (base.html) so there's never a flash of
    // it before this runs - revealed here only if it wasn't already
    // dismissed this browser session. "Not now" uses sessionStorage, not
    // localStorage, on purpose: it's fine to ask again next session if
    // the browser/active-language mismatch still holds.
    const languageSuggestion = document.getElementById("language-suggestion");
    if (languageSuggestion) {
        const suggestedCode = languageSuggestion.dataset.languageCode;
        const dismissKey = "wanderes-language-suggestion-dismissed-" + suggestedCode;

        let alreadyDismissed = false;
        try {
            alreadyDismissed = window.sessionStorage.getItem(dismissKey) === "1";
        } catch (e) {
            // sessionStorage can throw in private browsing or embedded
            // contexts - fail open (show the suggestion) instead of
            // breaking the rest of the page's JS.
        }

        if (!alreadyDismissed) {
            languageSuggestion.hidden = false;
        }

        const dismissButton = languageSuggestion.querySelector(".language-suggestion-dismiss");
        if (dismissButton) {
            dismissButton.addEventListener("click", function () {
                languageSuggestion.hidden = true;
                try {
                    window.sessionStorage.setItem(dismissKey, "1");
                } catch (e) {
                    // Same deal - dismissal still works for this page view
                    // even if it can't be remembered for next time.
                }
            });
        }

        const switchButton = languageSuggestion.querySelector(".language-suggestion-switch");
        const switcherForm = document.getElementById("lang-switcher-form");
        const switcherSelect = document.getElementById("lang-switcher-select");
        if (switchButton && switcherForm && switcherSelect) {
            switchButton.addEventListener("click", function () {
                // Reuses the header's own language-switcher form (same
                // endpoint, CSRF token, cookie/account persistence via
                // core.views.set_language) rather than building a second
                // one - so this behaves exactly like using the switcher
                // directly.
                switcherSelect.value = suggestedCode;
                switcherForm.submit();
            });
        }
    }
})();
