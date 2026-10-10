// the little "i" next to a label: hover, focus or tap it to read what the label means.

(function () {
  const tooltip = document.querySelector(".tooltip");
  if (!tooltip) return;
  let open = null;

  function show(el) {
    open = el;
    const text = document.createElement("div");
    text.className = "tt-text";
    text.textContent = el.dataset.tip;
    tooltip.replaceChildren(text);
    tooltip.hidden = false;
    const at = el.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    let left = at.left + at.width / 2 - box.width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
    let top = at.bottom + 8;
    if (top + box.height > window.innerHeight - 8) top = at.top - box.height - 8;
    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
  }

  function hide() {
    open = null;
    tooltip.hidden = true;
  }

  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mouseenter", () => show(el));
    el.addEventListener("mouseleave", hide);
    el.addEventListener("focus", () => show(el));
    el.addEventListener("blur", hide);
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      if (open === el) hide(); else show(el);
    });
    el.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  });
  document.addEventListener("click", hide);
  window.addEventListener("scroll", hide, { passive: true });
})();
