// sun in light mode, moon in dark mode. until clicked, it follows the system.

(function () {
  const root = document.documentElement;
  const button = document.querySelector(".theme-toggle");
  const system = window.matchMedia("(prefers-color-scheme: dark)");

  function effective() {
    return root.dataset.theme || (system.matches ? "dark" : "light");
  }

  function sync() {
    if (!button) return;
    const mode = effective();
    button.dataset.mode = mode;
    button.setAttribute("aria-label", mode === "dark" ? "Switch to light theme" : "Switch to dark theme");
  }

  if (button) {
    button.addEventListener("click", () => {
      const next = effective() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) {}
      sync();
      document.dispatchEvent(new Event("themechange"));
    });
  }

  system.addEventListener("change", () => {
    if (root.dataset.theme) return;
    sync();
    document.dispatchEvent(new Event("themechange"));
  });

  sync();
})();
