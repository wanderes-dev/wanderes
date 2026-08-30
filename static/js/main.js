(function () {
    const navToggle = document.getElementById("nav-toggle");
    const siteNav = document.getElementById("site-nav");

    if (navToggle && siteNav) {
        navToggle.addEventListener("click", function () {
            const isOpen = siteNav.classList.toggle("is-open");
            navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
        });
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
