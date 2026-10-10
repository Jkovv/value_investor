// segmented tabs on the company page; the url hash keeps the open tab on reload.
// a running research brief or question is polled, and the page reloads when it ends.

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
      // on a phone the tab strip scrolls sideways; keep the open tab in view without moving the page
      const bar = t.parentElement;
      if (on && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = t.offsetLeft - (bar.clientWidth - t.offsetWidth) / 2;
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

  // links like "all 19 measures" on the overview open another tab
  document.querySelectorAll("[data-open-tab]").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      open(a.dataset.openTab);
      document.querySelector(".segmented").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  function poll(url, onUpdate, isDone) {
    const tick = async () => {
      try {
        const st = await (await fetch(url)).json();
        onUpdate(st);
        if (isDone(st)) {
          location.hash = "research";
          location.reload();
          return;
        }
      } catch (e) {}
      setTimeout(tick, 5000);
    };
    setTimeout(tick, 3000);
  }

  const card = document.querySelector(".research-card");
  if (card && (card.dataset.state === "running" || card.dataset.state === "queued")) {
    const steps = card.querySelector("[data-steps]");
    const last = card.querySelector("[data-last]");
    poll(`/company/${encodeURIComponent(card.dataset.ticker)}/research/status`, (st) => {
      if (steps) steps.textContent = st.steps || 0;
      if (last) last.textContent = st.last_step || "";
    }, (st) => st.state !== "running" && st.state !== "queued");
  }

  const ask = document.querySelector(".ask-card");
  if (ask && ask.dataset.state === "running") {
    const last = ask.querySelector("[data-ask-last]");
    poll(`/company/${encodeURIComponent(ask.dataset.ticker)}/ask/status`, (st) => {
      if (last) last.textContent = st.last_step || "";
    }, (st) => st.state !== "running");
  }
})();
