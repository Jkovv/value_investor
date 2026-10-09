// Auto -> Light -> Dark. "Auto" follows the operating system.

(function () {
  const root = document.documentElement;
  const button = document.querySelector(".theme-toggle");
  const order = ["auto", "light", "dark"];
  const names = { auto: "Auto", light: "Light", dark: "Dark" };

  function current() {
    return root.dataset.theme || "auto";
  }

  function apply(theme) {
    if (theme === "auto") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === "auto") localStorage.removeItem("theme");
      else localStorage.setItem("theme", theme);
    } catch (e) {}
    label();
    document.dispatchEvent(new Event("themechange"));
  }

  function label() {
    if (!button) return;
    button.replaceChildren(document.createTextNode("Theme: "));
    const b = document.createElement("b");
    b.textContent = names[current()];
    button.appendChild(b);
  }

  if (button) {
    button.addEventListener("click", () => {
      const next = order[(order.indexOf(current()) + 1) % order.length];
      apply(next);
    });
  }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (current() === "auto") document.dispatchEvent(new Event("themechange"));
  });
  label();
})();
