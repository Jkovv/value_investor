// small line charts drawn as inline SVG. each <figure class="chart"> carries
// its data in data-series: [{name, points: [[label, value|null], ...], muted?}].

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const tooltip = document.querySelector(".tooltip");

  const formats = {
    pct: (v) => (v * 100).toFixed(Math.abs(v) < 0.1 ? 1 : 0) + "%",
    pct0: (v) => Math.round(v * 100) + "%",
    num: (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)),
    compact: (v) => {
      const a = Math.abs(v);
      for (const [size, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
        if (a >= size) return (v / size).toFixed(1) + suffix;
      }
      return v.toFixed(0);
    },
  };

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceTicks(lo, hi, count) {
    if (lo === hi) { lo -= Math.abs(lo) * 0.1 || 1; hi += Math.abs(hi) * 0.1 || 1; }
    const raw = (hi - lo) / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const start = Math.floor(lo / step) * step;
    const ticks = [];
    for (let t = start; t <= hi + step * 0.5; t += step) ticks.push(+t.toFixed(10));
    return ticks;
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function draw(fig) {
    fig.querySelectorAll(".legend, svg").forEach((node) => node.remove());
    const series = JSON.parse(fig.dataset.series);
    const fmt = formats[fig.dataset.format] || formats.num;
    const labels = series[0].points.map((p) => p[0]);
    const values = series.flatMap((s) => s.points.map((p) => p[1])).filter((v) => v !== null);
    if (!values.length) return;

    const wide = fig.classList.contains("wide");
    const W = wide ? 1000 : 360, H = wide ? 300 : 170;
    const pad = { top: 10, right: 52, bottom: 24, left: 44 };
    const ticks = niceTicks(Math.min(...values), Math.max(...values), wide ? 5 : 3);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const x = (i) => pad.left + (labels.length === 1 ? 0 : (i / (labels.length - 1)) * (W - pad.left - pad.right));
    const y = (v) => pad.top + (1 - (v - y0) / (y1 - y0 || 1)) * (H - pad.top - pad.bottom);

    const colors = series.map((s) => (s.muted ? cssVar("--series-muted") : cssVar("--series-1")));

    if (series.length > 1) {
      const legend = document.createElement("div");
      legend.className = "legend";
      series.forEach((s, i) => {
        const item = document.createElement("span");
        const key = document.createElement("b");
        key.style.background = colors[i];
        item.appendChild(key);
        item.appendChild(document.createTextNode(s.name));
        legend.appendChild(item);
      });
      fig.appendChild(legend);
    }

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
    const grid = el("g", { class: "grid" }, svg);
    ticks.forEach((t) => {
      el("line", { x1: pad.left, x2: W - pad.right, y1: y(t), y2: y(t) }, grid);
      const label = el("text", { x: pad.left - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg);
      label.textContent = fmt(t);
    });
    el("line", { class: "baseline", x1: pad.left, x2: W - pad.right, y1: H - pad.bottom, y2: H - pad.bottom }, svg);

    const every = Math.max(1, Math.ceil(labels.length / (wide ? 9 : 5)));
    labels.forEach((lab, i) => {
      if (i % every !== 0 && i !== labels.length - 1) return;
      if (i !== labels.length - 1 && labels.length - 1 - i < every * 0.6) return;
      const t = el("text", { x: x(i), y: H - 6, "text-anchor": "middle", class: "tick" }, svg);
      t.textContent = String(lab).slice(0, +(fig.dataset.labelChars || 4));
    });

    series.forEach((s, si) => {
      let d = "", pen = false;
      s.points.forEach((p, i) => {
        if (p[1] === null) { pen = false; return; }
        d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(p[1]).toFixed(1);
        pen = true;
      });
      el("path", { d, class: "line", stroke: colors[si] }, svg);
      const last = [...s.points.keys()].reverse().find((i) => s.points[i][1] !== null);
      if (last === undefined) return;
      el("circle", { cx: x(last), cy: y(s.points[last][1]), r: 4, fill: colors[si], class: "dot" }, svg);
      if (!s.muted) {
        const end = el("text", { x: x(last) + 8, y: y(s.points[last][1]) + 4, class: "end-label" }, svg);
        end.textContent = fmt(s.points[last][1]);
      }
    });

    const cross = el("line", { class: "crosshair", y1: pad.top, y2: H - pad.bottom, visibility: "hidden" }, svg);
    const marks = series.map((s, si) => el("circle", { r: 4, fill: colors[si], class: "dot", visibility: "hidden" }, svg));
    fig.appendChild(svg);

    let current = labels.length - 1;

    function show(i, clientX, clientY) {
      current = i;
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      tooltip.replaceChildren();
      const head = document.createElement("div");
      head.className = "tt-x";
      head.textContent = labels[i];
      tooltip.appendChild(head);
      series.forEach((s, si) => {
        const v = s.points[i][1];
        marks[si].setAttribute("visibility", v === null ? "hidden" : "visible");
        if (v !== null) { marks[si].setAttribute("cx", x(i)); marks[si].setAttribute("cy", y(v)); }
        const row = document.createElement("div");
        row.className = "tt-row";
        const key = document.createElement("b");
        key.style.background = colors[si];
        const strong = document.createElement("strong");
        strong.textContent = v === null ? "-" : fmt(v);
        const name = document.createElement("span");
        name.textContent = s.name;
        row.append(key, strong, name);
        tooltip.appendChild(row);
      });
      tooltip.hidden = false;
      const box = tooltip.getBoundingClientRect();
      let left = clientX + 14, top = clientY - box.height - 10;
      if (left + box.width > window.innerWidth - 8) left = clientX - box.width - 14;
      if (top < 8) top = clientY + 14;
      tooltip.style.left = left + "px";
      tooltip.style.top = top + "px";
    }

    function hide() {
      cross.setAttribute("visibility", "hidden");
      marks.forEach((m) => m.setAttribute("visibility", "hidden"));
      tooltip.hidden = true;
    }

    function indexAt(clientX) {
      const r = svg.getBoundingClientRect();
      const px = ((clientX - r.left) / r.width) * W;
      const t = (px - pad.left) / (W - pad.left - pad.right);
      return Math.max(0, Math.min(labels.length - 1, Math.round(t * (labels.length - 1))));
    }

    svg.addEventListener("pointermove", (e) => show(indexAt(e.clientX), e.clientX, e.clientY));
    svg.addEventListener("pointerleave", hide);

    fig._chart = {
      hide,
      step(delta) {
        const next = Math.max(0, Math.min(labels.length - 1, current + delta));
        const r = svg.getBoundingClientRect();
        show(next, r.left + (x(next) / W) * r.width, r.top + r.height / 3);
      },
    };
  }

  const figures = document.querySelectorAll("figure.chart[data-series]");
  figures.forEach((fig) => {
    draw(fig);
    fig.addEventListener("blur", () => fig._chart && fig._chart.hide());
    fig.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      if (fig._chart) fig._chart.step(e.key === "ArrowRight" ? 1 : -1);
    });
  });

  document.addEventListener("themechange", () => {
    tooltip.hidden = true;
    figures.forEach(draw);
  });
})();
