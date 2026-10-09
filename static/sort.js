// Click a column header to sort its table, click again to flip the order.
// Numbers start high-to-low, text starts A-to-Z. Rows without data stay at the bottom.
// The choice survives reloads (clicking a market reloads the page), per table id.

(function () {
  document.querySelectorAll("table.sortable").forEach((table) => {
    const heads = [...table.querySelectorAll("thead th[data-sort]")];
    const allHeads = [...table.querySelectorAll("thead th")];
    const body = table.tBodies[0];
    const key = "sort:" + (table.id || "table");

    function cellValue(row, col, kind) {
      if (row.hasAttribute("data-empty")) return null;
      const cell = row.cells[col];
      const raw = cell ? cell.dataset.value : undefined;
      if (raw === undefined || raw === "" || raw === "None") return null;
      if (kind === "text") return raw.toLowerCase();
      const n = parseFloat(raw);
      return Number.isNaN(n) ? null : n;
    }

    function apply(th, dir, remember) {
      const col = allHeads.indexOf(th);
      const kind = th.dataset.sort;
      const sign = dir === "ascending" ? 1 : -1;
      heads.forEach((h) => h.setAttribute("aria-sort", "none"));
      th.setAttribute("aria-sort", dir);
      const rows = [...body.rows];
      rows.sort((a, b) => {
        const x = cellValue(a, col, kind);
        const y = cellValue(b, col, kind);
        if (x === null && y === null) return 0;
        if (x === null) return 1;
        if (y === null) return -1;
        if (kind === "text") return x.localeCompare(y) * sign;
        return (x - y) * sign;
      });
      rows.forEach((r) => body.appendChild(r));
      if (remember) {
        try { sessionStorage.setItem(key, JSON.stringify({ col, dir })); } catch (e) {}
      }
    }

    heads.forEach((th) => {
      const button = th.querySelector(".sort-btn");
      if (!button) return;
      button.addEventListener("click", () => {
        const current = th.getAttribute("aria-sort");
        const first = th.dataset.sort === "text" ? "ascending" : "descending";
        const dir = current === "none" ? first : current === "descending" ? "ascending" : "descending";
        apply(th, dir, true);
      });
    });

    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || "null");
      const th = saved && allHeads[saved.col];
      if (th && th.dataset.sort) apply(th, saved.dir, false);
    } catch (e) {}
  });
})();
