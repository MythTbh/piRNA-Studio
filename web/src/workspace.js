import referenceCatalog from "./reference_catalog.json";
import { api } from "./api";
import {
  mountHeader,
  mountOverview,
  releaseOverview,
} from "./components/mount";
const $ = (s) => document.querySelector(s),
  E = (v) =>
    String(v ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    ),
  num = (v) =>
    v == null
      ? "Not available"
      : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }),
  pct = (v) => (v == null ? "Not available" : num(100 * v) + "%"),
  sum = (a) => a.reduce((t, v) => t + Number(v || 0), 0);
let maxUploadBytes = 4 * 1024 * 1024 * 1024;
const icon = () => "";
const tabs = [
  "Overview",
  "Sample QC",
  "Clusters",
  "Differential expression",
  "Validation",
  "Provenance",
  "Export",
];
const slugs = [
  "overview",
  "qc",
  "clusters",
  "de",
  "validation",
  "provenance",
  "export",
];
const chip = (s) => `<span class="chip ${E(s)}">${E(s)}</span>`;
const panel = (title, content) =>
  `<section class="panel"><h2>${title}</h2>${content}</section>`;
const empty = (msg) => `<p class="empty">${E(msg)}</p>`;
function download(name, data, type = "text/plain") {
  const url = URL.createObjectURL(
    data instanceof Blob ? data : new Blob([data], { type }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
const storeGet = (k) => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};
document.documentElement.dataset.theme = "light";
let data = null,
  run = "",
  token = 0,
  live = false,
  latestRun = "",
  tim = null,
  resultsCache = {},
  tableHandlers = new Map(),
  uid = 0;
const navigate = (s) => {
  if (location.hash === "#" + s) route();
  else location.hash = s;
};
const routeParts = () => location.hash.slice(1).split("/");
function home() {
  return `<div class="wrap"><section class="intro"><div class="eyebrow">Small RNA analysis</div><h1>Identify piRNA clusters.<br>Compare biological replicates.</h1><p>Inspect read quality, genomic coverage, cluster calls, and expression differences from single-end or paired-end FASTQ libraries.</p><p class="caption">${live ? "Analysis server connected." : "Public analysis hosting is not connected. Explore the completed datasets below; new analyses currently require the local app."}</p><div class="actions"><a class="btn primary" href="#results/fly/overview">Explore public sequencing data</a><a class="btn" href="#new">${live ? "Start analysis" : "Configure a local analysis"}</a></div></section><div class="sectionHead"><h2>Inspect the evidence</h2></div><section class="dataset"><h3>Drosophila Ago3-IP</h3><p>Interactive results from 20,000 reads in public library SRR1568761, mapped to chromosome 2R. Inspect the cluster calls, read accounting, and agreement with published annotations.</p><div class="actions"><a href="#results/fly/clusters">Browse genomic clusters</a><a href="benchmark.html">Read benchmark limitations</a></div></section><div class="sectionHead"><h2>Analysis steps</h2><a href="#methods">Methods</a></div><div class="pipeline">${[["Prepare reads","Validate libraries, trim adapters or assemble mates, and filter reads."],["Map and inspect","Align retained reads and review quality for each sample."],["Call clusters","Identify genomic intervals supported by biological replicates."],["Compare conditions","Count reads within consensus intervals and examine expression differences."]].map(([title,description],i)=>`<div class="pipe"><span>${String(i+1).padStart(2,"0")}</span><strong>${title}</strong><p>${description}</p></div>`).join("")}</div><div id="recent"></div></div>`;
}
function title(k, h, p = "", action = "") {
  return `<div class="titleRow"><div><div class="eyebrow">${E(k)}</div><h1>${E(h)}</h1>${p ? `<div class="muted">${E(p)}</div>` : ""}</div>${action}</div>`;
}
function cell(value) {
  if (typeof value !== "number") return E(value ?? "Not available");
  if (value !== 0 && Math.abs(value) < 0.001) return value.toExponential(2);
  return Number.isInteger(value)
    ? num(value)
    : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
const tsv = (cols, rows) =>
  [cols, ...rows]
    .map((r) =>
      r.map((v) => String(v ?? "").replace(/[\t\r\n]/g, " ")).join("\t"),
    )
    .join("\n");
function table(name, cols, rows, click = null) {
  const id = "tbl" + ++uid;
  tableHandlers.set(id, { name, cols, rows, click, q: "", idx: -1, dir: 1 });
  return `<div id="${id}"><div class="tablebar"><input type="search" aria-label="Filter ${E(name)}" placeholder="Filter table…"><button data-export>Export TSV</button></div><div class="scroll"><table><thead><tr>${cols.map((c, i) => `<th><button data-col="${i}">${E(c)} ↕</button></th>`).join("")}</tr></thead><tbody></tbody></table></div><p class="caption" data-n></p></div>`;
}
function bindTables() {
  for (const [id, v] of tableHandlers) {
    const el = document.getElementById(id);
    if (!el || el.dataset.bound) continue;
    el.dataset.bound = "1";
    let shown;
    function draw() {
      shown = v.rows.filter((r) =>
        r.some((x) =>
          String(x ?? "")
            .toLowerCase()
            .includes(v.q),
        ),
      );
      if (v.idx >= 0)
        shown.sort(
          (a, b) =>
            v.dir *
            (typeof a[v.idx] === "number" && typeof b[v.idx] === "number"
              ? a[v.idx] - b[v.idx]
              : String(a[v.idx] ?? "").localeCompare(
                  String(b[v.idx] ?? ""),
                  undefined,
                  { numeric: true },
                )),
        );
      el.querySelector("tbody").innerHTML = shown
        .slice(0, v.limit || 150)
        .map(
          (r, i) =>
            "<tr>" +
            r
              .map(
                (x, j) =>
                  `<td>${v.click && j === 0 ? `<button class="link" data-i="${i}">${E(x)}</button>` : cell(x)}</td>`,
              )
              .join("") +
            "</tr>",
        )
        .join("");
      let n = shown.length,
        limit = v.limit || 150;
      el.querySelector("[data-n]").innerHTML =
        (n
          ? `${num(Math.min(limit, n))} of ${num(n)} rows`
          : "No matching rows") +
        (n > limit ? " <button data-more>Show more</button>" : "");
      el.querySelector("[data-more]")?.addEventListener("click", () => {
        v.limit = limit + 150;
        draw();
      });
    }
    el.querySelector("input").oninput = (e) => {
      v.q = e.target.value.toLowerCase().trim();
      draw();
    };
    el.querySelectorAll("[data-col]").forEach(
      (b) =>
        (b.onclick = () => {
          let i = +b.dataset.col;
          v.dir = v.idx === i ? -v.dir : 1;
          v.idx = i;
          el.querySelectorAll("th").forEach((th) =>
            th.removeAttribute("aria-sort"),
          );
          b.parentNode.setAttribute(
            "aria-sort",
            v.dir === 1 ? "ascending" : "descending",
          );
          draw();
        }),
    );
    el.querySelector("[data-export]").onclick = () =>
      download(v.name + ".tsv", tsv(v.cols, shown));
    el.querySelector("tbody").onclick = (e) => {
      const b = e.target.closest("button[data-i]");
      if (b) v.click(shown[+b.dataset.i][0]);
    };
    draw();
  }
}
function bars(entries, caption) {
  if (!entries.length) return empty("No values available.");
  let max = Math.max(1, ...entries.map((x) => x[1]));
  return (
    entries
      .map(
        ([k, v]) =>
          `<div class="barline"><span>${E(k)}</span><i><b style="width:${Math.max(0, (100 * v) / max)}%"></b></i><span class="mono">${num(v)}</span></div>`,
      )
      .join("") + `<p class="caption">${E(caption)}</p>`
  );
}
function accounting(d) {
  let agg = new Map();
  for (const r of d.accounting || [])
    agg.set(r.stage, (agg.get(r.stage) || 0) + r.reads);
  return bars(
    [...agg],
    "Reads by processing stage. Shorter bars indicate fewer retained reads.",
  );
}
function overview() {
  return '<div id="overview"></div>';
}
function lengthHistogram(sample, params = data?.provenance?.parameters || {}) {
  const points = Object.entries(sample.length_histogram || {})
    .map(([nt, count]) => [Number(nt), count])
    .sort((a, b) => a[0] - b[0]);
  if (!points.length) return empty("No length profile available.");
  const min = points[0][0],
    max = points[points.length - 1][0],
    peak = Math.max(1, ...points.map((p) => p[1]));
  const step = 360 / (max - min + 1),
    x = (n) => 46 + (n - min) * step;
  const from = params.min_length ?? 24,
    to = params.max_length ?? 32;
  const columns = points
    .map(
      ([n, v]) =>
        `<rect x="${x(n)}" y="${134 - (108 * v) / peak}" width="${Math.max(0.5, step * 0.8)}" height="${(108 * v) / peak}" fill="var(--${n >= from && n <= to ? "accent" : "neutral"})"><title>${n} nt · ${num(v)} reads</title></rect>`,
    )
    .join("");
  return `<svg class="chart" viewBox="0 0 430 175" role="img" aria-label="Read length distribution for ${E(sample.sample_id)}"><line x1="46" x2="406" y1="134" y2="134"/>${columns}<text x="44" y="25" text-anchor="end">${num(peak)}</text><text x="14" y="90" transform="rotate(-90 14 90)">Reads</text><text x="46" y="150">${min}</text><text x="406" y="150" text-anchor="end">${max}</text><text x="228" y="169" text-anchor="middle">Insert length (nt)</text></svg><p class="caption">The configured window spans ${from}–${to} nt. The most frequent length is ${E(sample.peak_length ?? "Not available")} nt.</p>`;
}
function qc() {
  let q = data.qc || [];
  return (
    panel(
      "Sample quality checks",
      table(
        "sample-qc",
        [
          "Sample",
          "Input reads",
          "piRNA-sized %",
          "Unique %",
          "1U %",
          "10A %",
          "Ping-pong z",
          "Gate",
        ],
        q.map((x) => [
          x.sample_id,
          x.total_reads,
          x.piRNA_range_pct,
          x.unique_pct,
          x.u1_pct,
          x.a10_pct,
          x.pingpong_z,
          x.status,
        ]),
      ),
    ) +
    `<div class="sectionHead"><h2>Read length profiles</h2></div><div class="grid">${q.map((x) => panel(E(x.sample_id), lengthHistogram(x))).join("")}</div><div class="sectionHead"><h2>Nucleotide bias & ping-pong</h2></div><div class="grid">${panel(
      "Nucleotide bias (%)",
      bars(
        q.flatMap((x) => [
          [x.sample_id + " 1U", x.u1_pct],
          [x.sample_id + " 10A", x.a10_pct],
        ]),
        "Fractions of reads carrying U at position 1 or A at position 10, in percent.",
      ),
    )}${panel(
      "Ping-pong z-score",
      table(
        "ping-pong",
        ["Sample", "10 nt overlap z-score", "Gate"],
        q.map((x) => [
          x.sample_id,
          x.pingpong_z,
          x.pingpong_z == null
            ? "Unavailable"
            : x.pingpong_z > 1.65
              ? "Pass"
              : "Warn",
        ]),
      ) +
        '<p class="caption">Scores above 1.65 pass the 10 nt overlap gate. Somatic samples can have a weak signature.</p>',
    )}</div>`
  );
}
const options = (values) =>
  values.map((v) => `<option value="${E(v)}">${E(v)}</option>`).join("");
const clusterFields = [
  "cluster_id",
  "chr",
  "start",
  "end",
  "length",
  "strand_mode",
  "total_reads",
  "support_n",
];
let view = { chr: "", start: 0, end: 0 };
function trackSvg(chr, start, end, tracks, clusters) {
  if (end <= start) return empty("Select a genomic interval.");
  const w = 680,
    left = 50,
    right = 655,
    bins = 90,
    plus = Array(bins).fill(0),
    minus = Array(bins).fill(0),
    ix = (v) => Math.floor(((v - start) * bins) / (end - start));
  for (const r of tracks) {
    if (r.chr !== chr || r.start >= end || r.end <= start) continue;
    const ys = r.strand === "-" ? minus : plus;
    for (
      let i = Math.max(0, ix(r.start));
      i <= Math.min(bins - 1, ix(r.end - 1));
      i++
    )
      ys[i] += r.count;
  }
  const max = Math.max(...plus, ...minus, 1),
    dx = (right - left) / bins,
    X = (v) =>
      left +
      (right - left) * Math.min(1, Math.max(0, (v - start) / (end - start)));
  return `<svg class="chart" viewBox="0 0 ${w} 180" role="img" aria-label="Read coverage on both strands of ${E(chr)}, from ${start} to ${end}"><line x1="50" x2="655" y1="87" y2="87"/><text x="2" y="53">Sense +</text><text x="1" y="117">Anti −</text>${plus.map((v, i) => `<rect x="${left + i * dx}" y="${84 - (v / max) * 52}" width="${dx - 0.3}" height="${(v / max) * 52}" fill="var(--sense)"/><rect x="${left + i * dx}" y="89" width="${dx - 0.3}" height="${(minus[i] / max) * 35}" fill="var(--anti)"/>`).join("")}${clusters
    .filter((c) => c.chr === chr && c.end > start && c.start < end)
    .map(
      (c) =>
        `<rect x="${X(c.start)}" y="135" width="${Math.max(1, X(c.end) - X(c.start))}" height="9" fill="var(--p)" fill-opacity=".2" stroke="var(--p)"><title>${E(c.cluster_id)}</title></rect>`,
    )
    .join(
      "",
    )}<text x="50" y="165">${num(start)}</text><text x="350" text-anchor="middle" y="165">${E(chr)} · genomic position (bp)</text><text x="655" text-anchor="end" y="165">${num(end)}</text></svg><p class="caption">Bar height shows summed alignment weights per bin. Outlined intervals show consensus clusters.</p>`;
}
function clusterDetail(id) {
  const c = data.clusters.find((x) => x.cluster_id === id);
  if (!c) return;
  const dlg = $("#detail");
  dlg.innerHTML = `<div class="between"><div><span class="eyebrow">Cluster details</span><h2>${E(id)}</h2></div><button id="closeDlg">Close</button></div><p class="mono">${E(c.chr)} · ${num(c.start)}–${num(c.end)} bp</p>${trackSvg(c.chr, c.start, c.end, data.tracks || [], [c])}<div class="kpis">${[
    ["1U", c.u1_pct],
    ["10A", c.a10_pct],
    ["Repeat content", c.repeat_pct],
  ]
    .map(
      ([k, v]) =>
        `<div class="kpi"><small>${k}</small><strong>${v == null ? "Not available" : num(v) + "%"}</strong></div>`,
    )
    .join(
      "",
    )}</div><h3>Reads per sample</h3>${bars(Object.entries(c.counts || {}), "Weighted reads assigned to this cluster in each sample.")}`;
  $("#closeDlg").onclick = () => dlg.close();
  dlg.showModal();
}
function clusters() {
  const cs = data.clusters || [],
    chrom = [...new Set([...cs, ...(data.tracks || [])].map((c) => c.chr))];
  if (!cs.length && !chrom.length)
    return panel(
      "Clusters",
      empty("No alignments or consensus intervals were found."),
    );
  if (!chrom.includes(view.chr) || view.end <= view.start) {
    view.chr = chrom[0];
    view.start = 0;
    view.end =
      data.provenance?.chromosome_lengths?.[view.chr] ||
      [...cs, ...(data.tracks || [])].reduce(
        (m, r) => (r.chr === view.chr ? Math.max(m, r.end) : m),
        1,
      );
  }
  return (
    panel(
      "Genome track",
      `<div class="formrow"><label class="field">Chromosome<select id="trackChr">${options(chrom)}</select></label><label class="field">Start (bp)<input id="trackStart" type="number" min="0" value="${view.start}"></label><label class="field">End (bp)<input id="trackEnd" type="number" min="1" value="${view.end}"></label></div><div class="row"><button id="trackApply">View region</button><button id="zoom">Zoom in</button><button id="zoomOut">Zoom out</button><button id="panL" aria-label="Pan left">←</button><button id="panR" aria-label="Pan right">→</button></div><div id="trackPlot"></div>`,
    ) +
    panel(
      "Consensus clusters",
      `<div class="formrow"><label class="field">Chromosome<select id="fChr"><option value="">All</option>${options(chrom)}</select></label><label class="field">Strand mode<select id="fStr"><option value="">All</option>${options([...new Set(cs.map((c) => c.strand_mode))])}</select></label>${[
        ["Length (bp)", "fLen"],
        ["Reads", "fReads"],
        ["Replicates", "fRep"],
      ]
        .map(
          ([k, id]) =>
            `<label class="field">Minimum ${k.toLowerCase()}<input type="number" min="0" value="0" id="${id}"></label>`,
        )
        .join("")}</div><div id="ctable"></div>`,
    )
  );
}
function bindClusters() {
  if (!$("#trackChr")) return;
  const cs = data.clusters || [],
    tr = data.tracks || [];
  const extent = () =>
    data.provenance?.chromosome_lengths?.[view.chr] ||
    [...cs, ...tr].reduce(
      (m, r) => (r.chr === view.chr ? Math.max(m, r.end) : m),
      1,
    );
  function update() {
    view.end = Math.max(view.start + 1, Math.min(extent(), view.end));
    $("#trackStart").value = view.start;
    $("#trackEnd").value = view.end;
    $("#trackPlot").innerHTML = trackSvg(
      view.chr,
      view.start,
      view.end,
      tr,
      cs,
    );
  }
  $("#trackChr").value = view.chr;
  $("#trackChr").onchange = (e) => {
    view.chr = e.target.value;
    view.start = 0;
    view.end = extent();
    update();
  };
  $("#trackApply").onclick = () => {
    let s = Number($("#trackStart").value),
      e = Number($("#trackEnd").value);
    if (!(s >= 0 && e > s && s < extent())) {
      $("#trackPlot").innerHTML = empty(
        "Enter a start within the chromosome and an end larger than the start.",
      );
      return;
    }
    view.start = Math.floor(s);
    view.end = Math.ceil(e);
    update();
  };
  for (const [id, scale, pan] of [
    ["zoom", 0.5, 0],
    ["zoomOut", 2, 0],
    ["panL", 1, -0.5],
    ["panR", 1, 0.5],
  ])
    $("#" + id).onclick = () => {
      let w = view.end - view.start,
        n = Math.min(extent(), Math.max(1, Math.round(w * scale)));
      view.start = Math.max(
        0,
        Math.min(extent() - n, Math.round(view.start + (w - n) / 2 + w * pan)),
      );
      view.end = view.start + n;
      update();
    };
  update();
  function filter() {
    const subset = cs.filter(
      (c) =>
        (!$("#fChr").value || c.chr === $("#fChr").value) &&
        (!$("#fStr").value || c.strand_mode === $("#fStr").value) &&
        c.length >= +$("#fLen").value &&
        c.total_reads >= +$("#fReads").value &&
        c.support_n >= +$("#fRep").value,
    );
    $("#ctable").innerHTML = table(
      "clusters",
      [
        "Cluster",
        "Chromosome",
        "Start (bp)",
        "End (bp)",
        "Length (bp)",
        "Strand",
        "Reads",
        "Support",
      ],
      subset.map((c) => clusterFields.map((k) => c[k])),
      clusterDetail,
    );
    bindTables();
  }
  ["fChr", "fStr", "fLen", "fReads", "fRep"].forEach(
    (k) => ($("#" + k).oninput = filter),
  );
  filter();
}
function scatter(rows, mode, p, fc) {
  const pts = rows
    .filter((r) => r.padj != null && Number.isFinite(+r.log2fc))
    .map((r) => ({
      x: mode === "MA" ? Math.log10(1 + r.base_mean) : +r.log2fc,
      y: mode === "MA" ? +r.log2fc : -Math.log10(Math.max(1e-300, r.padj)),
      r,
    }));
  if (!pts.length) return empty("No tested clusters in this contrast.");
  let xs = pts.map((q) => q.x),
    ys = pts.map((q) => q.y),
    a = Math.min(0, ...xs, mode === "MA" ? 0 : -fc),
    b = Math.max(1, ...xs, mode === "MA" ? 0 : fc),
    c = Math.min(0, ...ys, mode === "MA" ? -fc : 0),
    d = Math.max(1, ...ys, mode === "MA" ? fc : -Math.log10(p));
  const X = (x) => 48 + ((x - a) / (b - a)) * 364,
    Y = (y) => 183 - ((y - c) / (d - c)) * 156;
  const line = (x1, y1, x2, y2) =>
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" style="stroke:var(--muted)" stroke-dasharray="3 3"/>`;
  return `<svg viewBox="0 0 430 225" class="chart" role="img" aria-label="${mode} plot"><line x1="48" x2="412" y1="183" y2="183"/><line x1="48" x2="48" y1="27" y2="183"/>${mode === "MA" ? [-fc, fc].map((t) => line(48, Y(t), 412, Y(t))).join("") : [-fc, fc].map((t) => line(X(t), 27, X(t), 183)).join("") + line(48, Y(-Math.log10(p)), 412, Y(-Math.log10(p)))}${pts
    .map(({ x, y, r }) => {
      let sig = r.padj <= p && Math.abs(r.log2fc) >= fc;
      let tip = `<title>${E(r.cluster_id)} · log2FC ${num(r.log2fc)} · adjusted p ${E(r.padj)}</title>`;
      return sig
        ? `<path d="M${X(x)} ${Y(y) - 4}l4 7h-8z" transform="rotate(${r.log2fc < 0 ? 180 : 0} ${X(x)} ${Y(y)})" fill="var(--${r.log2fc >= 0 ? "up" : "down"})">${tip}</path>`
        : `<circle cx="${X(x)}" cy="${Y(y)}" r="3" fill="var(--neutral)">${tip}</circle>`;
    })
    .join(
      "",
    )}<text x="220" y="220" text-anchor="middle">${mode === "MA" ? "log10(1 + base mean)" : "log2 fold change"}</text><text x="14" y="106" text-anchor="middle" transform="rotate(-90 14 106)">${mode === "MA" ? "log2 fold change" : "−log10(adjusted p)"}</text><text x="48" y="201">${num(a)}</text><text x="412" text-anchor="end" y="201">${num(b)}</text><text x="45" y="25" text-anchor="end">${num(d)}</text></svg><p class="caption">Triangles indicate significant increases (▲) and decreases (▼) at the selected thresholds.</p>`;
}
function differential() {
  let rows = data.de || [],
    contrasts = [...new Set(rows.map((r) => r.contrast))];
  return (
    panel(
      "Contrast and thresholds",
      `<div class="formrow"><label class="field">Contrast<select id="contrast">${options(contrasts)}</select></label><label class="field">Maximum adjusted p<input id="padj" type="number" min="0.000001" max="1" step=".01" value=".05"></label><label class="field">Minimum |log2 fold change|<input id="lfc" type="number" min="0" step=".1" value="1"></label><label class="field">Heatmap clusters<input id="heatN" type="number" min="1" max="100" value="15"></label></div>`,
    ) + '<div id="deout"></div>'
  );
}
function bindDE() {
  const samples = data.samples || [],
    groups = {};
  samples.forEach((s) => {
    groups[s.condition] = (groups[s.condition] || 0) + 1;
  });
  function draw() {
    const p = +$("#padj").value,
      fc = +$("#lfc").value,
      n = +$("#heatN").value;
    if (!(p > 0 && p <= 1 && fc >= 0 && n > 0 && n <= 100)) {
      $("#deout").innerHTML = empty(
        "Choose a positive adjusted p ≤ 1, nonnegative fold-change threshold, and 1–100 heatmap rows.",
      );
      return;
    }
    let rows = (data.de || []).filter(
      (r) => r.contrast === $("#contrast").value,
    );
    const tested = rows.filter((r) => r.padj != null),
      sig = tested
        .filter((r) => r.padj <= p && Math.abs(r.log2fc) >= fc)
        .sort((a, b) => a.padj - b.padj)
        .slice(0, n);
    let cmap = new Map((data.clusters || []).map((c) => [c.cluster_id, c]));
    $("#deout").innerHTML =
      (Object.values(groups).some((v) => v < 3)
        ? '<div class="notice warning">Fewer than three samples in at least one condition. Interpret fold changes and significance cautiously.</div>'
        : "") +
      (!tested.length
        ? '<div class="notice">Adjusted p-values are unavailable for this contrast. Review the engine method and replicate counts in Provenance.</div>'
        : "") +
      `<div class="grid">${panel("Volcano plot", scatter(rows, "Volcano", p, fc))}${panel("MA plot", scatter(rows, "MA", p, fc))}</div>` +
      panel(
        "Top differential clusters",
        sig.length
          ? `<div class="scroll"><table><thead><tr><th>Cluster</th>${samples.map((s) => `<th style="border-top:4px solid var(--condition-${Object.keys(groups).indexOf(s.condition) % 5})">${E(s.sample_id)}<br><small>${E(s.condition)}</small></th>`).join("")}</tr></thead><tbody>${sig
              .map((r) => {
                let vals = samples.map(
                    (s) => cmap.get(r.cluster_id)?.counts?.[s.sample_id] || 0,
                  ),
                  max = Math.max(1, ...vals);
                return `<tr><td>${E(r.cluster_id)}</td>${vals.map((v) => `<td><span class="heat" style="background:color-mix(in srgb,var(--accent) ${10 + (40 * v) / max}%,var(--surface))">${num(v)}</span></td>`).join("")}</tr>`;
              })
              .join(
                "",
              )}</tbody></table></div><p class="caption">Counts by sample, shaded relative to the maximum in each cluster.</p>`
          : empty("No clusters meet the selected thresholds."),
      ) +
      panel(
        "Differential expression results",
        table(
          "de-results",
          [
            "Cluster",
            "Contrast",
            "Base mean",
            "log2 fold change",
            "P-value",
            "Adjusted p",
            "Flag",
          ],
          rows.map((r) => [
            r.cluster_id,
            r.contrast,
            r.base_mean,
            r.log2fc,
            r.pvalue,
            r.padj,
            r.flag,
          ]),
          clusterDetail,
        ),
      );
    bindTables();
  }
  ["contrast", "padj", "lfc", "heatN"].forEach(
    (k) => ($("#" + k).oninput = draw),
  );
  draw();
}
function validation() {
  const v = data.validation || {};
  return (
    panel(
      "Reference overlap",
      `<p class="muted">A cluster matches when the overlap spans at least half of each interval on the same chromosome.</p><div class="kpis">${[
        ["Precision", v.precision],
        ["Recall", v.recall],
        ["Base-pair Jaccard", v.jaccard],
      ]
        .map(
          ([k, x]) =>
            `<div class="kpi"><small>${k}</small><strong>${pct(x)}</strong></div>`,
        )
        .join("")}</div>`,
    ) +
    (v.precision == null && v.recall == null
      ? '<div class="notice">Reference metrics are unavailable for this run.</div>'
      : "") +
    panel(
      "Cluster matches",
      table(
        "validation",
        ["Status", "Cluster", "Reference"],
        [
          ...(v.matched || []).map((x) => ["Matched", x.cluster_id, x.ref_id]),
          ...(v.missed || []).map((x) => [
            "Missed",
            "Not available",
            typeof x === "object" ? x.ref_id : x,
          ]),
          ...(v.extra || []).map((x) => [
            "Extra",
            typeof x === "object" ? x.cluster_id : x,
            "Not available",
          ]),
        ],
      ),
    )
  );
}
function provenance() {
  const p = data.provenance || {};
  return (
    (p.reference_assembly ? panel("Reference genome", `<p><strong>${E(p.reference_assembly.species)} · ${E(p.reference_assembly.assembly)}</strong></p><p>${E(p.reference_assembly.accession)} · downloaded from NCBI RefSeq</p><p>SHA-256: <code>${E(p.reference_assembly.sha256)}</code></p>`) : "") +
    panel(
      "Methods",
      `<p>${E(p.methods || "See the run manifest for tools and parameters.")}</p>`,
    ) +
    panel(
      "Run manifest",
      `<p class="caption">Input checksums, configuration, software versions, and timestamps recorded by the engine.</p><pre class="code">${E(JSON.stringify(p, null, 2))}</pre><div class="actions"><button id="manifest">Download manifest</button><button id="reproProv">Reproduce this run</button></div>`,
    )
  );
}
function exportsView() {
  return panel(
    "Run outputs",
    `<p class="muted">Download a self-contained report, data tables, or the run configuration.</p><div class="actions"><button id="html">HTML report</button><button id="zip">All outputs (.zip)</button><button id="reproduce">Reproduce this run</button></div>`,
  );
}
async function loadBenchmark() {
  if (window.PIRNA_BENCHMARK) return window.PIRNA_BENCHMARK;
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "benchmark-data.js";
    script.onload = resolve;
    script.onerror = () =>
      reject(new Error("The benchmark data could not be loaded."));
    document.head.appendChild(script);
  });
  return window.PIRNA_BENCHMARK;
}
async function results(parts, my) {
  run = parts[1] || latestRun;
  if (!run || run === "demo") {
    $("#main").innerHTML = `<div class="wrap">${title("Results workspace", "No analysis results selected", "Run an analysis or select a completed run from Workspace.")}<p>Synthetic demonstration results are not included.</p><div class="actions"><a class="btn primary" href="#new">New analysis</a><a class="btn" href="#home">Workspace</a></div><p><a href="#results/fly/overview">View the separately labelled public Drosophila benchmark</a></p></div>`;
    return;
  }
  const slug = slugs.includes(parts[2]) ? parts[2] : "overview";
  const d = run === "fly" ? await loadBenchmark() : resultsCache[run] || (await api.results(run));
  if (my !== token) return;
  if (!d)
    throw Error(
      "The selected analysis results could not be loaded.",
    );
  data = d;
  if (run !== "fly") {
    resultsCache[run] = d;
    latestRun = run;
  }
  const pane = [
    overview,
    qc,
    clusters,
    differential,
    validation,
    provenance,
    exportsView,
  ][slugs.indexOf(slug)];
  $("#main").innerHTML =
    `<div class="wrap">${title("Results workspace", run === "fly" ? "Drosophila Ago3-IP" : "Analysis results", run === "fly" ? "SRR1568761 · chromosome 2R · 20,000 public reads" : "Run " + run, '<a class="btn" href="#new">New analysis</a>')}<nav class="tabs" aria-label="Results sections">${tabs.map((v, i) => `<a class="${slugs[i] === slug ? "active" : ""}" href="#results/${encodeURIComponent(run)}/${slugs[i]}">${v}</a>`).join("")}</nav>${pane()}</div>`;
  bindTables();
  if (slug === "overview") mountOverview(d, run);
  if (slug === "clusters") bindClusters();
  if (slug === "de") bindDE();
  if (slug === "provenance")
    $("#manifest").onclick = () =>
      download(
        "provenance.json",
        JSON.stringify(d.provenance, null, 2),
        "application/json",
      );
  if (slug === "provenance")
    $("#reproProv").onclick = () => downloadExport("reproduce");
  if (slug === "export") bindExports();
}
function bindExports() {
  for (const k of ["html", "zip", "reproduce"])
    $("#" + k).onclick = () => downloadExport(k);
}
function downloadExport(k) {
  const a = document.createElement("a");
  a.href =
    run === "fly"
      ? "downloads/" +
        "fly-" +
        { html: "report.html", zip: "outputs.zip", reproduce: "reproduce.zip" }[
          k
        ]
      : api.exportUrl(run, k);
  a.download = "";
  a.click();
}
const blankWizard = () => ({
  step: 0,
  samples: [],
  refs: {},
  referenceId: "",
  referenceState: null,
  referenceBusy: false,
  params: {
    min_length: 24,
    max_length: 32,
    min_cluster_size: 1000,
    support: 2,
    max_gap: 150,
    min_loci: 5,
    min_total_count: 10,
    count_mode: "fractional",
    backend: "protrac",
    protrac_profile: "default",
    de_method: "auto",
  },
  checks: null,
  error: "",
  busy: false,
});
let wiz = blankWizard();
const hostedDemo =
  location.protocol === "https:" &&
  !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const localBundle = hostedDemo
  ? '<p><a class="btn" href="downloads/piRNA-Studio.zip" download>Download local app</a></p>'
  : "";
const setupOffline =
  '<div class="notice">This copy opens precomputed results. To process your files, open <strong>Launch piRNA Studio.command</strong> from the downloaded project on macOS, or run <code>python3 -m server</code> in its project directory. Use the local address printed by the launcher.' +
  localBundle +
  "</div>";
function sampleSummary() {
  const groups = new Map();
  wiz.samples.forEach(s => groups.set(s.condition || "Unassigned", (groups.get(s.condition || "Unassigned") || 0) + 1));
  return [...groups].map(([name,n]) => `${E(name)}: ${n} biological replicate${n === 1 ? "" : "s"}`).join(" · ") || "No samples added yet.";
}
function sampleError() {
  if (!wiz.samples.length) return "Add at least one sample to continue.";
  const ids = new Set(), reps = new Set(), files = new Set();
  for (const s of wiz.samples) {
    if (!/^[A-Za-z0-9_-]+$/.test(s.sample_id) || ids.has(s.sample_id)) return "Give each sample a unique ID using letters, numbers, underscores or hyphens.";
    ids.add(s.sample_id);
    const key = JSON.stringify([s.condition.trim(), Number(s.replicate)]);
    if (!s.condition.trim() || !Number.isInteger(+s.replicate) || +s.replicate < 1 || reps.has(key)) return "Each condition needs distinct positive biological replicate numbers.";
    reps.add(key);
    if (!s.file || (s.layout === "paired" && !s.file2)) return `Select ${s.layout === "paired" ? "both R1 and R2 files" : "a FASTQ file"} for ${s.sample_id}.`;
    for (const f of [s.file, ...(s.layout === "paired" ? [s.file2] : [])]) {
      if (files.has(f.name)) return "Use each FASTQ once and give distinct files unique filenames: " + f.name;
      files.add(f.name);
    }
  }
  return "";
}
function sampleRows() {
  return `<p id="replicateSummary" class="notice">${sampleSummary()}</p>` + wiz.samples.map((s,i) => `<section class="sampleCard"><div class="between"><h3>Sample ${i+1}</h3><button data-remove="${i}">Remove sample</button></div><div class="formrow">${[["sample_id","Sample ID"],["condition","Condition / group"],["replicate","Biological replicate"],["library_kit","Kit or adapter (single-end)"]].map(([k,label]) => `<label class="field">${label}<input data-row="${i}" data-key="${k}" ${k === "replicate" ? 'type="number" min="1" step="1"' : k === "library_kit" ? 'list="kitOptions"' : ""} value="${E(s[k])}"></label>`).join("")}</div><label class="field">Sequencing layout<select data-layout="${i}"><option value="single" ${s.layout !== "paired" ? "selected" : ""}>Single-end · one FASTQ</option><option value="paired" ${s.layout === "paired" ? "selected" : ""}>Paired-end · R1 + R2</option></select></label><div class="formrow">${["file",...(s.layout === "paired" ? ["file2"] : [])].map(k => `<label class="field">${k === "file2" ? "R2 FASTQ" : s.layout === "paired" ? "R1 FASTQ" : "FASTQ file"}<input type="file" data-sample-file="${k}" data-row="${i}" accept=".fastq,.fq,.gz"><small>${s[k] ? E(s[k].name) : "No file selected"}</small></label>`).join("")}</div>${s.layout === "paired" ? '<p class="caption">Overlapping mates are assembled in R1 orientation and counted once. Pairs without a unique overlap of at least 12 nt are discarded; pre-flight reports the merge rate.</p>' : ""}</section>`).join("");
}
function addSample(file = null) {
  const condition = wiz.samples.at(-1)?.condition || "Control";
  const replicate = Math.max(0,...wiz.samples.filter(s => s.condition === condition).map(s => +s.replicate || 0))+1;
  wiz.samples.push({file, file2:null, layout:"single", sample_id:file ? file.name.replace(/\.(fastq|fq)(\.gz)?$/i, "").replace(/[^a-zA-Z0-9_-]/g,"_") : `sample_${wiz.samples.length+1}`, condition,replicate,library_kit:"TruSeq"});
  wiz.checks = null;
}
function referencePicker() {
  const ref = referenceCatalog.find(r => r.id === wiz.referenceId);
  const state = wiz.referenceState;
  return `<label class="field">Reference organism<select id="referenceOrganism" ${wiz.referenceBusy ? "disabled" : ""}><option value="">Choose an organism</option>${referenceCatalog.map(r => `<option value="${r.id}" ${r.id === wiz.referenceId ? "selected" : ""}>${E(r.label)}  /  ${E(r.species)}</option>`).join("")}</select></label>${ref ? `<div class="notice"><strong>${E(ref.assembly)}</strong><p>${E(ref.accession)} · NCBI RefSeq · ${(ref.bytes/1024/1024).toFixed(0)} MiB download</p><a href="${ref.source}" target="_blank" rel="noopener">View NCBI assembly</a><p>Downloaded automatically on Continue, verified against NCBI’s checksum, and cached for future runs. No genome upload needed.</p><p class="caption">Uses NCBI sequence accession names. Optional BED files must match this assembly and its sequence names.</p></div>` : ""}${state ? `<p role="status">${state.status === "ready" ? "Reference verified and ready." : state.status === "failed" ? E(state.error) : state.status === "downloading" ? `Downloading from NCBI: ${(state.downloaded_bytes/1024/1024).toFixed(1)} / ${(state.total_bytes/1024/1024).toFixed(1)} MiB` : state.status === "queued" ? "Reference download queued…" : "Verifying reference integrity…"}</p>` : ""}<p class="caption">Full genomes require the installed proTRAC backend. ${live ? "The first download requires internet access and sufficient disk space." : "Automatic downloads and analysis run in the local app; this public site lets you explore and configure the workflow."}</p>`;
}
async function prepareReference() {
  const id = wiz.referenceId;
  wiz.referenceBusy = true; wiz.error = ""; if (location.hash === "#new") wizard();
  try {
    let state = await api.prepareReference(id);
    while (true) {
      if (wiz.referenceId !== id) return;
      wiz.referenceState = state; if (location.hash === "#new") wizard();
      if (state.status === "failed") throw Error(state.error);
      if (state.status === "ready") break;
      await new Promise(resolve => setTimeout(resolve, 1000));
      state = await api.referenceStatus(id);
    }
    wiz.step = 2;
  } catch (error) { wiz.error = error.message; }
  finally { wiz.referenceBusy = false; if (location.hash === "#new") wizard(); }
}
function fileInput(k, label, accept) {
  return `<label class="field">${label}<input type="file" data-ref="${k}" accept="${accept}"><small>${wiz.refs[k] ? "Selected: " + E(wiz.refs[k].name) : ""}</small></label>`;
}
function selectParam(k, label, opts) {
  return `<label class="field">${label}<select data-param="${k}">${Object.entries(
    opts,
  )
    .map(
      ([v, l]) =>
        `<option value="${v}" ${wiz.params[k] === v ? "selected" : ""}>${E(l)}</option>`,
    )
    .join("")}</select></label>`;
}
function intParam(k, label) {
  return `<label class="field">${label}<input data-param="${k}" type="number" min="1" value="${E(wiz.params[k])}"></label>`;
}
function preflightHistogram(check) {
  if (!check.histogram) return "";
  const bins = Object.entries(check.histogram);
  if (!bins.length) return "";
  const peak = bins.reduce((best, next) =>
    best[1] < next[1] ? next : best,
  )[0];
  const profile = {
    sample_id: check.name,
    length_histogram: check.histogram,
    peak_length: peak,
  };
  return `<details><summary>Sampled length distribution</summary>${lengthHistogram(profile, wiz.params)}<p class="caption">Reads without a full adapter match contribute their sequenced length.</p></details>`;
}
function wizard() {
  const titles = [
    "Samples",
    "Genome & references",
    "Parameters",
    "Pre-flight review",
  ];
  let body = "";
  if (wiz.step === 0)
    body = `<p>Each card represents one biological replicate. For example, Control replicates 1, 2 and 3 are three cards with the same condition. A paired-end R1/R2 pair belongs on one card.</p><p class="caption">Local upload limit: ${num(maxUploadBytes / 1024 ** 3)} GiB total across all files in a submission.</p><div class="actions"><button id="addSample">Add sample / replicate</button></div><label class="field">Bulk add single-end samples<input type="file" id="reads" multiple accept=".fastq,.fq,.gz"><small>One card per file. For paired-end data, add a sample, choose Paired-end, and select R1 and R2.</small></label>${sampleRows()}<datalist id="kitOptions">${options(["TruSeq", "NEBNext", "QIAseq", "Lexogen"])}</datalist><p class="caption">Replicates are processed separately, then grouped by condition for expression analysis. Use independent biological replicates; do not label R1 and R2 as replicates.</p><label class="field">Import sample metadata (optional CSV)<input type="file" id="sheet" accept=".csv"><small>Select files first. Columns: sample_id, condition, replicate, fastq_path, library_kit. Paired-end rows also use layout=paired and fastq_r2_path. Match files by filename.</small></label>`;
  if (wiz.step === 1)
    body =
      referencePicker() +
      fileInput("reference", "Reference clusters (optional BED)", ".bed,.gz") +
      "<details><summary>Additional reference files</summary>" +
      fileInput("repeats", "Repeat regions (BED)", ".bed,.gz") +
      ["rRNA", "tRNA", "snRNA", "miRNA"]
        .map((k) => fileInput(k, k + " filter (FASTA)", ".fa,.fasta,.gz"))
        .join("") +
      "</details>";
  if (wiz.step === 2)
    body = `<div class="formrow">${intParam("min_length", "Minimum insert length (nt)")}${intParam("max_length", "Maximum insert length (nt)")}${intParam("min_cluster_size", "Minimum cluster size (bp)")}</div>${selectParam("backend", "Analysis backend", { protrac: "proTRAC · full reference genomes" })}<details><summary>Advanced parameters</summary><div class="formrow">${intParam("support", "Minimum replicate support")}${intParam("min_loci", "Minimum distinct loci")}${intParam("max_gap", "Maximum locus gap (bp)")}${intParam("min_total_count", "Minimum total DE count")}</div>${selectParam("protrac_profile", "proTRAC thresholds", { default: "Standard proTRAC", clusterdb: "piRNAclusterDB profile" })}${selectParam("count_mode", "Multimapping policy", { fractional: "Fractional (1 / number of hits)", unique: "Unique hits only" })}${selectParam("de_method", "Expression method", { auto: "Auto · PyDESeq2 if installed", pydeseq2: "Require PyDESeq2", descriptive: "Descriptive fold changes" })}</details>`;
  if (wiz.step === 3)
    body = wiz.checks
      ? wiz.checks.checks
          .map(
            (c) =>
              `<div class="check"><div class="between"><strong>${E(c.name)}</strong>${chip(c.severity)}</div><p>${E(c.message)}</p>${c.fix ? `<p class="muted">${E(c.fix)}</p>` : ""}${preflightHistogram(c)}</div>`,
          )
          .join("")
      : empty(
          wiz.busy
            ? "Checking files and configuration…"
            : "Run pre-flight to check the current inputs.",
        );
  $("#main").innerHTML =
    `<div class="wrap">${title("Analysis setup", "New analysis", "Prepare samples, choose a reference, and check your inputs.")}${live ? "" : setupOffline}<div class="wizardnav" aria-label="Setup progress">${titles.map((t, i) => `<span class="${i === wiz.step ? "active" : ""}">${i + 1}. ${t}</span>`).join("")}</div>${panel(titles[wiz.step], body)}${wiz.error ? `<div class="notice error" role="alert">${E(wiz.error)}</div>` : ""}<div class="actions">${wiz.step ? '<button id="back">Back</button>' : ""}${wiz.step < 3 ? `<button id="next" class="primary" ${wiz.referenceBusy ? "disabled" : ""}>${wiz.referenceBusy ? "Preparing reference…" : "Continue"}</button>` : `<button id="check" ${wiz.busy || !live ? "disabled" : ""}>${wiz.busy ? "Working…" : "Check inputs"}</button><button id="start" class="primary" ${!live || !wiz.checks || wiz.checks.blocking || wiz.busy ? "disabled" : ""}>Run analysis</button>`}</div></div>`;
  if ($("#referenceOrganism")) $("#referenceOrganism").onchange = e => {
    wiz.referenceId = e.target.value; wiz.referenceState = null; wiz.checks = null; wiz.error = ""; wizard();
  };
  if ($("#addSample")) $("#addSample").onclick = () => { addSample(); wiz.error=""; wizard(); };
  if ($("#reads")) $("#reads").onchange = e => {
    for (const file of e.target.files) addSample(file);
    wiz.error = sampleError(); wizard();
  };
  document.querySelectorAll("[data-layout]").forEach(el => el.onchange = () => {
    const s = wiz.samples[+el.dataset.layout]; s.layout=el.value;
    if (s.layout === "single") s.file2=null;
    wiz.checks=null; wizard();
  });
  document.querySelectorAll("[data-sample-file]").forEach(el => el.onchange = () => {
    if (el.files[0]) wiz.samples[+el.dataset.row][el.dataset.sampleFile]=el.files[0];
    wiz.checks=null; wizard();
  });
  document.querySelectorAll("[data-key]").forEach(
    (el) =>
      (el.oninput = () => {
        wiz.samples[+el.dataset.row][el.dataset.key] = el.value;
        wiz.checks = null;
        $("#replicateSummary").innerHTML = sampleSummary();
      }),
  );
  document.querySelectorAll("[data-remove]").forEach(
    (b) =>
      (b.onclick = () => {
        wiz.samples.splice(+b.dataset.remove, 1);
        wiz.checks = null;
        wizard();
      }),
  );
  if ($("#sheet"))
    $("#sheet").onchange = async (e) => {
      try {
        const rows = parseCSV(await e.target.files[0].text());
        const head = rows.shift();
        for (const k of [
          "sample_id",
          "condition",
          "replicate",
          "fastq_path",
          "library_kit",
        ])
          if (!head.includes(k))
            throw Error("Missing sample sheet column: " + k);
        const next = rows.map((row) => {
          const rec = Object.fromEntries(head.map((k, i) => [k, row[i]]));
          const name = rec.fastq_path.split(/[\\/]/).pop(),
            s = wiz.samples.find((x) => x.file?.name === name);
          if (!s) throw Error("Select the corresponding FASTQ first: " + name);
          const layout = rec.layout || (rec.fastq_r2_path ? "paired" : "single");
          const name2 = rec.fastq_r2_path?.split(/[\\/]/).pop();
          const file2 = name2 ? wiz.samples.flatMap(x => [x.file,x.file2]).find(f => f?.name === name2) : null;
          if (layout === "paired" && !file2) throw Error("Select R2 first: " + (name2 || "missing fastq_r2_path"));
          return { ...s, sample_id:rec.sample_id, condition:rec.condition, replicate:rec.replicate, library_kit:rec.library_kit, layout, file2 };
        });
        if (new Set(next.map((s) => s.file.name)).size !== next.length)
          throw Error("Each FASTQ must appear once in the sheet.");
        wiz.samples = [
          ...next,
          ...wiz.samples.filter((s) => !next.some((x) => x.file === s.file || x.file2 === s.file)),
        ];
        wiz.checks = null;
        wiz.error = sampleError();
      } catch (err) {
        wiz.error = err.message;
      }
      wizard();
    };
  document.querySelectorAll("[data-ref]").forEach(
    (f) =>
      (f.onchange = () => {
        wiz.refs[f.dataset.ref] = f.files[0];
        f.parentElement.querySelector("small").textContent = f.files[0]
          ? "Selected: " + f.files[0].name
          : "";
        wiz.checks = null;
      }),
  );
  document.querySelectorAll("[data-param]").forEach(
    (f) =>
      (f.oninput = () => {
        wiz.params[f.dataset.param] =
          f.type === "number" ? Number(f.value) : f.value;
        wiz.checks = null;
      }),
  );
  if ($("#back")) $("#back").disabled = wiz.referenceBusy;
  if ($("#back"))
    $("#back").onclick = () => {
      wiz.step--;
      wiz.checks = null;
      wiz.error = "";
      wizard();
    };
  if ($("#next"))
    $("#next").onclick = () => {
      if (wiz.step === 0 && sampleError())
        wiz.error = sampleError();
      else if (wiz.step === 1 && !wiz.referenceId)
        wiz.error = "Choose a reference organism to continue.";
      else if (wiz.step === 1 && live) { prepareReference(); return; }
      else {
        wiz.error = "";
        wiz.step++;
      }
      wizard();
      if (wiz.step === 3 && live) submitWizard(false);
    };
  if ($("#check")) $("#check").onclick = () => submitWizard(false);
  if ($("#start")) $("#start").onclick = () => submitWizard(true);
}
function parseCSV(txt) {
  let rows = [],
    row = [],
    s = "",
    q = false;
  txt = txt.replace(/^\uFEFF/, "");
  for (let i = 0; i < txt.length; i++) {
    let c = txt[i];
    if (c === '"') {
      if (q && txt[i + 1] === '"') {
        s += '"';
        i++;
      } else q = !q;
    } else if (c === "," && !q) {
      row.push(s.trim());
      s = "";
    } else if (c === "\n" && !q) {
      row.push(s.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      s = "";
    } else s += c;
  }
  if (q) throw Error("Unclosed quotation mark in sample sheet");
  row.push(s.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}
function formData() {
  let files = new Map(),
    refs = wiz.refs;
  const add = (f) => {
    if (files.has(f.name) && files.get(f.name) !== f)
      throw Error("Give different files distinct filenames: " + f.name);
    files.set(f.name, f);
    return f.name;
  };
  const cfg = {
    samples: wiz.samples.map(({ file, file2, ...s }) => ({
      ...s,
      fastq_path: add(file),
      ...(s.layout === "paired" ? { fastq_r2_path: add(file2) } : {}),
    })),
    reference_genome: wiz.referenceId,
    params: wiz.params,
    ncrna: {},
  };
  for (const k of ["reference", "repeats"]) if (refs[k]) cfg[k] = add(refs[k]);
  for (const k of ["rRNA", "tRNA", "snRNA", "miRNA"])
    if (refs[k]) cfg.ncrna[k] = add(refs[k]);
  const configJson = JSON.stringify(cfg);
  // Include conservative multipart header overhead, not just the FASTQ sizes.
  const estimatedBytes = sum([...files.values()].map((f) => f.size))
    + new Blob([configJson]).size + (files.size + 1) * 4096;
  if (estimatedBytes > maxUploadBytes)
    throw Error(
      `The local server accepts up to ${num(maxUploadBytes / 1024 ** 3)} GiB total per submission, including all samples and upload metadata. Use the engine CLI for larger inputs.`,
    );
  let form = new FormData();
  form.append("config", configJson);
  files.forEach((f) => form.append("files", f, f.name));
  return form;
}
async function submitWizard(start) {
  const my = token;
  wiz.busy = true;
  wiz.error = "";
  wizard();
  try {
    let res = start
      ? await api.start(formData())
      : await api.preflight(formData());
    if (start) {
      latestRun = res.run_id;
      wiz = blankWizard();
      if (my === token) navigate("monitor/" + res.run_id);
      return;
    }
    wiz.checks = res;
  } catch (err) {
    wiz.error = err.message;
  } finally {
    wiz.busy = false;
    if (my === token && routeParts()[0] === "new") wizard();
  }
}
function workflowStages(status) {
  const stages = [
    ["Preflight", 0],
    ["Mapping and cluster calling", 5],
    ["Consensus and counting", 72],
    ["Differential expression", 82],
    ["Validation and report", 92],
  ];
  return (
    '<ol class="run-stages">' +
    stages
      .map(([name, start], i) => {
        const next = stages[i + 1]?.[1] ?? 100;
        const state =
          status.progress >= next
            ? "completed"
            : status.stage === name
              ? "running"
              : status.progress >= start &&
                  ["failed", "cancelled"].includes(status.status)
                ? "stopped"
                : "pending";
        return `<li><span>${name}</span> ${chip(state)}</li>`;
      })
      .join("") +
    "</ol>"
  );
}
async function monitor(id, my) {
  let r = await api.status(id);
  if (my !== token) return;
  let done = ["completed", "cancelled", "failed"].includes(r.status);
  $("#main").innerHTML =
    `<div class="wrap">${title("Run monitor", "Analysis progress", "Run " + id, chip(r.status))}${panel("Workflow progress", `<p>${E(r.stage)} · ${num(r.progress)}%</p><progress max="100" value="${Number(r.progress) || 0}"></progress>${workflowStages(r)}${r.error ? `<p class="error">${E(r.error)}</p>` : ""}<div class="actions">${r.status === "completed" ? `<a class="btn primary" href="#results/${E(id)}/overview">Open results →</a>` : done ? '<a class="btn" href="#new">New analysis</a>' : '<button id="cancel">Cancel run</button>'}</div>`)}<div class="sectionHead"><h2>Processing details</h2></div><div class="grid">${panel("Read accounting", accounting(r))}${panel("Run log", `<pre class="code">${E((r.logs || []).join("\n") || "Awaiting first stage…")}</pre>`)}</div></div>`;
  if ($("#cancel"))
    $("#cancel").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await api.cancel(id);
        if (my === token) route();
      } catch (err) {
        if (my === token) showError(err);
      }
    };
  if (!done)
    tim = setTimeout(() => {
      if (my === token)
        monitor(id, my).catch((err) => {
          if (my === token) showError(err);
        });
    }, 1100);
}
function methods() {
  const terms = [
    [
      "piRNA",
      "A PIWI-interacting small RNA. Read length and nucleotide biases provide evidence about a library.",
    ],
    [
      "Cluster",
      "A genomic interval with a concentration of mapped small RNA reads.",
    ],
    [
      "Consensus cluster",
      "An interval supported by calls in the required number of replicates within a condition.",
    ],
    [
      "1U and 10A",
      "The fraction of reads with U at the first base or A at the tenth.",
    ],
    [
      "Ping-pong",
      "Enrichment of a 10 nt overlap between opposite-strand 5′ ends, assessed against other overlap lengths.",
    ],
    [
      "Multimapper",
      "A read sequence with multiple genomic alignments. Fractional counting splits its weight across hits.",
    ],
  ];
  return `<div class="wrap">${title("Documentation", "Methods & help", "Interpret each stage and reproduce an analysis.")}<div class="sectionHead"><h2>Analysis methods</h2></div><div class="grid">${panel("Analysis backends", "<p>The portable engine trims exact adapters, maps exact matches on both strands of a small reference, and groups nearby mapped loci into candidate clusters. Use it for demonstrations and small-reference experiments.</p><p>The external backend uses cutadapt, duster, sRNAmapper and proTRAC. Each run records its chosen tools and parameters in Provenance.</p>")}${panel("Sample quality gates", '<ul class="steps"><li>At least 20% of reads in the configured piRNA length range and the largest peak inside it.</li><li>At least 10% distinct reads among piRNA-sized reads.</li><li>At least 35% 1U or 10A.</li><li>10 nt ping-pong overlap z-score above 1.65.</li></ul><p class="caption">Warnings allow analysis to continue. Tissue context can affect the ping-pong signature.</p>')}</div><div class="sectionHead"><h2>Interpretation</h2></div><div class="grid">${panel("Expression and validation", "<p>Counts use the discovered consensus intervals as features. PyDESeq2 fits Wald tests to integer counts from uniquely mapped reads. The cluster table also supports fractional expression counts. Descriptive runs report fold changes with empty p-values. Inspect the recorded count policy before comparing runs.</p><p>Precision and recall use 50% reciprocal overlap. Base-pair Jaccard divides the intersecting genomic bases by the union.</p>")}${panel("Limits of the examples", "<p>The Drosophila benchmark compares calls to published clusters on chromosome 2R. Whole-genome, multi-sample performance requires separate evaluation.</p>")}</div><div class="sectionHead"><h2>Glossary</h2></div>${panel("Terms", terms.map(([k, v]) => `<div class="check"><strong>${k}</strong><p>${v}</p></div>`).join(""))}</div>`;
}
function legal(page) {
  const privacy = page === "privacy";
  const text = privacy ? `<h2>Data entered in the workspace</h2><p>The current public site displays precomputed datasets. Selecting a FASTQ file in the setup form does not upload it to a hosted analysis service. Public analysis hosting is not connected.</p><h2>Local analysis</h2><p>When you use the local app, files are submitted to the analysis server running on your computer. Uploaded files, run records, and outputs are stored in its configured data directory. There is no automatic deletion schedule in the current app.</p><h2>Reference downloads</h2><p>The local app contacts NCBI to retrieve the selected reference assembly. NCBI receives the download request from that computer. Read files are not sent to NCBI by this feature.</p><h2>Hosting and browser storage</h2><p>The public host receives normal web requests, which can include your IP address and browser information. Its logging and retention arrangements must be confirmed before launch. The application has no advertising or analytics integration in its source. Earlier versions saved a display preference under pirna-theme in browser local storage; that preference is no longer used.</p><h2>Contact and deletion requests</h2><p>piRNA Studio is operated by Mithila Jahan Jui. The contact method, hosting arrangements, and process for privacy requests remain to be confirmed. This policy must be completed before public analysis launches.</p>` : `<h2>Scope of the service</h2><p>piRNA Studio is a research software workspace for small RNA analysis. The current public site provides precomputed examples and configuration screens. It does not provide hosted analysis of uploaded sequencing data.</p><h2>Use of data</h2><p>Only process data you are authorized to use. Before submitting data to any future hosted service, check its published data handling terms. Local users control the input files and stored outputs on their own computer.</p><h2>Interpreting results</h2><p>Cluster calls and statistical results depend on library quality, reference assembly, parameters, and replicate design. The public benchmark is limited to its stated read subset and chromosome. This does not establish performance on every dataset.</p><h2>Research use</h2><p>The software has not been validated for clinical diagnosis or treatment decisions. Review methods and provenance and independently validate scientific conclusions.</p><h2>Terms pending completion</h2><p>piRNA Studio is operated by Mithila Jahan Jui. Contact details, applicable jurisdiction, hosting limits, data retention, and any fees must be confirmed before final terms can be issued. This draft does not announce a paid or public computing service.</p>`;
  return `<div class="wrap legal">${title("Service information",privacy ? "Privacy policy" : "Terms and conditions")}<p class="notice">Draft for review. Contact and hosting details are pending. Not approved for launch.</p>${text}<p><a href="#home">Return to workspace</a></p></div>`;
}
function showError(err) {
  $("#main").innerHTML =
    `<div class="wrap">${title("Workspace", "Unable to load this view")}<div class="notice error" role="alert">${E(err.message)}</div><div class="actions"><button id="retry">Try again</button><a class="btn" href="#home">Workspace</a></div></div>`;
  $("#retry").onclick = route;
}
async function recent(my) {
  if (!live) return;
  try {
    const d = await api.list();
    if (my !== token || !d.runs?.length) return;
    $("#recent").innerHTML =
      '<div class="sectionHead"><h2>Recent analyses</h2></div>' +
      panel(
        "Local runs",
        table(
          "local-runs",
          ["Run", "Created", "Status"],
          d.runs.map((r) => [r.run_id, r.created_at, r.status]),
          (id) => navigate("monitor/" + id),
        ),
      );
    bindTables();
  } catch {}
}
async function route() {
  clearTimeout(tim);
  const my = ++token,
    parts = routeParts(),
    page = parts[0] || "home";
  releaseOverview();
  mountHeader(page, latestRun);
  tableHandlers.clear();
  uid = 0;
  $("#detail").close();
  try {
    if (page === "home") {
      $("#main").innerHTML = home();
      recent(my);
    } else if (page === "methods") $("#main").innerHTML = methods();
    else if (page === "privacy" || page === "terms") $("#main").innerHTML = legal(page);
    else if (page === "new") wizard();
    else if (page === "results" || page === "monitor") {
      $("#main").innerHTML =
        '<div class="wrap skeleton" role="status" aria-busy="true"><span>Loading analysis…</span><div aria-hidden="true"><div class="skeleton-line short"></div><div class="skeleton-line"></div><div class="skeleton-block"></div></div></div>';
      if (page === "results") await results(parts, my);
      else await monitor(parts[1], my);
    } else navigate("home");
    if (my === token) {
      document.title =
        (page === "home"
          ? "Workspace"
          : page === "results"
            ? tabs[Math.max(0, slugs.indexOf(parts[2]))]
            : page === "new"
              ? "New analysis"
              : page === "monitor"
                ? "Run monitor"
                : page === "privacy" ? "Privacy policy" : page === "terms" ? "Terms and conditions" : "Methods") + " · piRNA Studio";
      $("#announce").textContent = document.title;
      window.scrollTo(0, 0);
    }
  } catch (err) {
    if (my === token) showError(err);
  }
}
window.addEventListener("hashchange", route);
route();
if (location.protocol !== "file:")
  api
    .health()
    .then((r) => {
      if (r.service === "piRNA Studio") {
        live = true;
        maxUploadBytes = r.max_upload_bytes || 128 * 1024 * 1024;
        const page = routeParts()[0];
        if (page === "new" || page === "home" || !page) route();
      }
    })
    .catch(() => {});
