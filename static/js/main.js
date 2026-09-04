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

    // Language suggestion banner (2026-09-04, automatic language
    // detection). Starts [hidden] server-side (templates/base.html) so
    // there's never a flash of it before this runs - only revealed here,
    // and only once, if it wasn't already dismissed this browser session.
    // "Not now" is deliberately session-scoped (sessionStorage, not
    // localStorage) per the original request ("avoid repeatedly showing
    // the same suggestion during the same session") - it's expected and
    // fine to ask again in a later session if the browser/active-language
    // mismatch still holds then.
    const languageSuggestion = document.getElementById("language-suggestion");
    if (languageSuggestion) {
        const suggestedCode = languageSuggestion.dataset.languageCode;
        const dismissKey = "wanderes-language-suggestion-dismissed-" + suggestedCode;

        let alreadyDismissed = false;
        try {
            alreadyDismissed = window.sessionStorage.getItem(dismissKey) === "1";
        } catch (e) {
            // sessionStorage can throw (private browsing, embedded contexts,
            // storage disabled) - fail open (show the suggestion) rather
            // than crash the rest of the page's JS.
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
                    // Same as above - dismissal for this page view still
                    // works even if it can't be remembered for next time.
                }
            });
        }

        const switchButton = languageSuggestion.querySelector(".language-suggestion-switch");
        const switcherForm = document.getElementById("lang-switcher-form");
        const switcherSelect = document.getElementById("lang-switcher-select");
        if (switchButton && switcherForm && switcherSelect) {
            switchButton.addEventListener("click", function () {
                // Reuses the real header language-switcher form (same
                // endpoint, same CSRF token, same cookie/account
                // persistence - core.views.set_language) instead of
                // building a second one - applying and persisting the
                // choice is then identical to using the switcher directly,
                // with nothing duplicated here.
                switcherSelect.value = suggestedCode;
                switcherForm.submit();
            });
        }
    }
})();
