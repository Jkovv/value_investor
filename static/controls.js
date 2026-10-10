// the sort and filter rows above a sortable table. sort: one column, then another for the
// rows that tie, and so on (the same order the headers show). filter: keep only the rows that
// meet every condition, like price at least 100 and discount at least 20%.
// both survive reloads, so they stay put while the market or history switches change.

(function () {
  const panel = document.querySelector("[data-controls]");
  if (!panel) return;
  const table = document.getElementById(panel.dataset.controls);
  if (!table || !table.sorter) return;

  const heads = [...table.querySelectorAll("thead th")];
  const columns = heads
    .map((th, i) => ({
      i,
      kind: th.dataset.sort,
      name: th.dataset.name || (th.querySelector(".sort-btn") || th).textContent.trim(),
      pct: th.dataset.unit === "pct",
      key: th.dataset.key,
    }))
    .filter((c) => c.kind);
  const numeric = columns.filter((c) => c.kind === "num");
  const byIndex = Object.fromEntries(columns.map((c) => [c.i, c]));
  const marketCol = heads.findIndex((th) => th.dataset.key === "market");

  const levelsBox = panel.querySelector("[data-sort-levels]");
  const filtersBox = panel.querySelector("[data-filters]");
  const addLevel = panel.querySelector("[data-add-level]");
  const addFilter = panel.querySelector("[data-add-filter]");
  const clear = panel.querySelector("[data-clear]");
  const noMatch = document.querySelector("[data-no-match]");
  const filterKey = "filters:" + table.id;

  // [{col, op: "min" | "max", value: "text as typed"}]
  let filters = [];
  try {
    const saved = JSON.parse(sessionStorage.getItem(filterKey) || "[]");
    if (Array.isArray(saved)) filters = saved.filter((f) => byIndex[f.col] && byIndex[f.col].kind === "num");
  } catch (e) {}

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    });
    (children || []).forEach((child) => node.appendChild(child));
    return node;
  }

  function select(options, current, label) {
    const node = el("select", { class: "select", "aria-label": label });
    options.forEach(([value, text]) => {
      const option = el("option", { value: String(value), text });
      if (String(value) === String(current)) option.selected = true;
      node.appendChild(option);
    });
    return node;
  }

  function removeButton(label) {
    const button = el("button", { type: "button", class: "remove", "aria-label": label });
    button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
    return button;
  }

  function directions(col) {
    return byIndex[col].kind === "text"
      ? [["ascending", "A to Z"], ["descending", "Z to A"]]
      : [["descending", "High to low"], ["ascending", "Low to high"]];
  }

  // sort rows

  function renderLevels() {
    const levels = table.sorter.levels();
    levelsBox.replaceChildren();
    levels.forEach(([col, dir], n) => {
      const item = el("span", { class: "control-item" });
      if (n > 0) item.appendChild(el("span", { class: "then", text: "then" }));
      const which = select(columns.map((c) => [c.i, c.name]), col, "Sort by");
      const order = select(directions(col), dir, "Order");
      which.addEventListener("change", () => {
        const next = table.sorter.levels();
        const picked = Number(which.value);
        next[n] = [picked, table.sorter.firstDir(picked)];
        table.sorter.set(next.filter(([c], k) => k === n || c !== picked));
      });
      order.addEventListener("change", () => {
        const next = table.sorter.levels();
        next[n][1] = order.value;
        table.sorter.set(next);
      });
      item.append(which, order);
      if (levels.length > 1) {
        const remove = removeButton("Remove this sort");
        remove.addEventListener("click", () => table.sorter.set(table.sorter.levels().filter((_, k) => k !== n)));
        item.appendChild(remove);
      }
      levelsBox.appendChild(item);
    });
    const used = new Set(levels.map(([c]) => c));
    addLevel.hidden = columns.every((c) => used.has(c.i));
  }

  addLevel.addEventListener("click", () => {
    const levels = table.sorter.levels();
    const used = new Set(levels.map(([c]) => c));
    const next = columns.find((c) => !used.has(c.i) && c.kind === "num") || columns.find((c) => !used.has(c.i));
    if (next) table.sorter.set(levels.concat([[next.i, table.sorter.firstDir(next.i)]]));
  });

  table.addEventListener("sorted", renderLevels);

  // filter rows

  function threshold(f) {
    const n = parseFloat(String(f.value).replace(",", "."));
    if (Number.isNaN(n)) return null;
    return byIndex[f.col].pct ? n / 100 : n;
  }

  function passes(row) {
    return filters.every((f) => {
      const limit = threshold(f);
      if (limit === null) return true;
      const raw = row.cells[f.col] ? row.cells[f.col].dataset.value : undefined;
      const v = parseFloat(raw);
      if (Number.isNaN(v)) return false;
      return f.op === "max" ? v <= limit : v >= limit;
    });
  }

  function applyFilters() {
    let shown = 0;
    const markets = new Set();
    [...table.tBodies[0].rows].forEach((row) => {
      const ok = passes(row);
      row.hidden = !ok;
      if (!ok) return;
      shown += 1;
      if (marketCol >= 0 && row.cells[marketCol]) markets.add(row.cells[marketCol].dataset.value);
    });
    document.querySelectorAll("[data-count]").forEach((node) => {
      node.textContent = shown + " " + (shown === 1 ? "company" : "companies") + (node.dataset.count || "");
    });
    document.querySelectorAll("[data-markets]").forEach((node) => {
      node.textContent = marketCol >= 0 ? markets.size : node.textContent;
    });
    if (noMatch) noMatch.hidden = shown > 0;
    clear.hidden = filters.length === 0;
    try { sessionStorage.setItem(filterKey, JSON.stringify(filters)); } catch (e) {}
  }

  function renderFilters() {
    filtersBox.replaceChildren();
    filters.forEach((f, n) => {
      const item = el("span", { class: "control-item" });
      if (n > 0) item.appendChild(el("span", { class: "then", text: "and" }));
      const which = select(numeric.map((c) => [c.i, c.name]), f.col, "Column");
      const op = select([["min", "at least"], ["max", "at most"]], f.op, "Condition");
      const input = el("input", { class: "input", type: "text", inputmode: "decimal", "aria-label": "Value",
                                  placeholder: "value", value: f.value });
      const box = el("span", { class: "value-box" }, [input]);
      if (byIndex[f.col].pct) {
        box.classList.add("pct");
        box.appendChild(el("span", { class: "unit", text: "%" }));
      }
      which.addEventListener("change", () => { f.col = Number(which.value); f.value = ""; renderFilters(); applyFilters(); });
      op.addEventListener("change", () => { f.op = op.value; applyFilters(); });
      input.addEventListener("input", () => { f.value = input.value; applyFilters(); });
      const remove = removeButton("Remove this filter");
      remove.addEventListener("click", () => { filters.splice(n, 1); renderFilters(); applyFilters(); });
      item.append(which, op, box, remove);
      filtersBox.appendChild(item);
    });
  }

  addFilter.addEventListener("click", () => {
    const used = new Set(filters.map((f) => f.col));
    const next = numeric.find((c) => !used.has(c.i)) || numeric[0];
    filters.push({ col: next.i, op: "min", value: "" });
    renderFilters();
    applyFilters();
    const inputs = filtersBox.querySelectorAll("input");
    if (inputs.length) inputs[inputs.length - 1].focus();
  });

  clear.addEventListener("click", () => {
    filters = [];
    renderFilters();
    applyFilters();
  });

  renderLevels();
  renderFilters();
  applyFilters();
})();
