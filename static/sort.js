// click a column header to sort its table by that column, click again to flip the order.
// shift-click adds the column as the next level: rows that tie on the first one are
// ordered by the second, and so on. numbers start high-to-low, text starts A-to-Z (a header
// can override with data-first). rows without data stay at the bottom.
// the order survives reloads, per table id. other scripts read and set it through table.sorter.

(function () {
  document.querySelectorAll("table.sortable").forEach((table) => {
    const allHeads = [...table.querySelectorAll("thead th")];
    const heads = allHeads.filter((th) => th.dataset.sort);
    const body = table.tBodies[0];
    const key = "sort:" + (table.id || "table");
    [...body.rows].forEach((row, i) => { row.dataset.order = i; });

    // [[column index, "ascending" | "descending"], ...], first level first
    let levels = heads.filter((th) => th.getAttribute("aria-sort") !== "none")
      .map((th) => [allHeads.indexOf(th), th.getAttribute("aria-sort")]);

    function value(row, col, kind) {
      if (row.hasAttribute("data-empty")) return null;
      const cell = row.cells[col];
      const raw = cell ? cell.dataset.value : undefined;
      if (raw === undefined || raw === "" || raw === "None" || raw === "nan") return null;
      if (kind === "text") return raw.toLowerCase();
      const n = parseFloat(raw);
      return Number.isNaN(n) ? null : n;
    }

    function firstDir(th) {
      return th.dataset.first || (th.dataset.sort === "text" ? "ascending" : "descending");
    }

    function flip(dir) {
      return dir === "ascending" ? "descending" : "ascending";
    }

    function compare(a, b) {
      for (const [col, dir] of levels) {
        const kind = allHeads[col].dataset.sort;
        const x = value(a, col, kind);
        const y = value(b, col, kind);
        if (x === null && y === null) continue;
        if (x === null) return 1;
        if (y === null) return -1;
        const d = kind === "text" ? x.localeCompare(y) : x - y;
        if (d !== 0) return dir === "ascending" ? d : -d;
      }
      return a.dataset.order - b.dataset.order;
    }

    function render(remember) {
      heads.forEach((th) => {
        th.setAttribute("aria-sort", "none");
        const button = th.querySelector(".sort-btn");
        if (button) delete button.dataset.level;
      });
      levels.forEach(([col, dir], i) => {
        const th = allHeads[col];
        th.setAttribute("aria-sort", dir);
        const button = th.querySelector(".sort-btn");
        if (button && levels.length > 1) button.dataset.level = i + 1;
      });
      [...body.rows].sort(compare).forEach((row) => body.appendChild(row));
      if (remember) {
        try { sessionStorage.setItem(key, JSON.stringify(levels)); } catch (e) {}
      }
      table.dispatchEvent(new CustomEvent("sorted"));
    }

    heads.forEach((th) => {
      const button = th.querySelector(".sort-btn");
      if (!button) return;
      const col = allHeads.indexOf(th);
      button.addEventListener("click", (e) => {
        const at = levels.findIndex(([c]) => c === col);
        if (e.shiftKey) {
          if (at === -1) levels.push([col, firstDir(th)]);
          else levels[at][1] = flip(levels[at][1]);
        } else if (levels.length === 1 && at === 0) {
          levels[0][1] = flip(levels[0][1]);
        } else {
          levels = [[col, firstDir(th)]];
        }
        render(true);
      });
    });

    table.sorter = {
      levels: () => levels.map((level) => level.slice()),
      firstDir: (col) => firstDir(allHeads[col]),
      set(next) {
        levels = next.filter(([col]) => allHeads[col] && allHeads[col].dataset.sort);
        render(true);
      },
    };

    try {
      let saved = JSON.parse(sessionStorage.getItem(key) || "null");
      if (saved && !Array.isArray(saved) && saved.col !== undefined) saved = [[saved.col, saved.dir]];
      if (Array.isArray(saved)) {
        const valid = saved.filter(([col]) => allHeads[col] && allHeads[col].dataset.sort);
        if (valid.length) { levels = valid; render(false); }
      }
    } catch (e) {}
  });
})();
