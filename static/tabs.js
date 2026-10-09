// Segmented tabs on the company page. The URL hash keeps the open tab on reload.
// While a research run is going, its status is polled and the page reloads when it ends.

(function () {
  const tabs = [...document.querySelectorAll(".segmented [role=tab]")];
  const panels = [...document.querySelectorAll(".tab-panel")];
  if (!tabs.length) return;

  function open(name, focus) {
    if (!panels.some((p) => p.dataset.panel === name)) name = "overview";
    tabs.forEach((t) => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    panels.forEach((p) => { p.hidden = p.dataset.panel !== name; });
    history.replaceState(null, "", name === "overview" ? location.pathname : "#" + name);
  }

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => open(t.dataset.tab));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      open(next.dataset.tab, true);
    });
  });

  open(location.hash.slice(1) || "overview");

  const card = document.querySelector(".research-card");
  if (card && (card.dataset.state === "running" || card.dataset.state === "queued")) {
    const steps = card.querySelector("[data-steps]");
    const last = card.querySelector("[data-last]");
    const poll = async () => {
      try {
        const res = await fetch(`/company/${encodeURIComponent(card.dataset.ticker)}/research/status`);
        const st = await res.json();
        if (steps) steps.textContent = st.steps || 0;
        if (last) last.textContent = st.last_step || "";
        if (st.state === "done" || st.state === "error") {
          location.hash = "research";
          location.reload();
          return;
        }
      } catch (e) {}
      setTimeout(poll, 5000);
    };
    setTimeout(poll, 3000);
  }
})();
