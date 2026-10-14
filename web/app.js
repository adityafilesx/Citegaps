/* CiteGap UI. All page-derived strings are untrusted: the DOM is built with textContent only (no innerHTML). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SEV = { critical: 0, high: 1, medium: 2, low: 3 };
  const STAGES = [
    ["target", "Fetch the live page and its raw HTML"],
    ["search", "Search: rank, indexation, title and snippet"],
    ["competitors", "Fetch the top competitors"],
    ["answerability", "Find passages that answer the query"],
    ["analyze", "Analyze and link causes to symptoms"],
    ["score", "Score and build the report"],
  ];

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return el;
  }
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage may be blocked */ } },
  };

  /* ---------- form + live run ---------- */
  $("form").addEventListener("submit", (e) => {
    e.preventDefault();
    startAudit("/audit", { url: $("url").value.trim(), query: $("query").value.trim() || null });
  });

  async function startAudit(endpoint, body) {
    $("form-error").hidden = true;
    $("go").disabled = true;
    try {
      const r = await fetch(endpoint, { method: "POST", headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      if (r.status === 429) throw new Error("Too many audits from this address. Wait a minute and try again.");
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "The audit could not start.");
      watch(data.id);
    } catch (err) {
      $("form-error").textContent = err.message;
      $("form-error").hidden = false;
      $("go").disabled = false;
    }
  }

  function watch(id) {
    $("report").hidden = true;
    $("run").hidden = false;
    $("calls").replaceChildren();
    $("call-count").textContent = "";
    const list = $("stages");
    list.replaceChildren(...STAGES.map(([k, label]) => h("li", { "data-stage": k }, h("span", { class: "dot" }), label)));
    const rows = new Map();
    const es = new EventSource(`/audit/${id}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      const idx = STAGES.findIndex((s) => s[0] === ev.stage);
      if (idx >= 0) [...list.children].forEach((li, i) => { li.className = i < idx ? "done" : i === idx ? "active" : ""; });
      const c = ev.tinyfish_call;
      if (c) {
        let row = rows.get(c.id);
        if (!row) {
          row = { li: h("li"), st: h("span"), name: h("span") };
          row.li.append(h("span", { class: "badge " + c.endpoint, text: c.endpoint }), row.name, row.st);
          $("calls").append(row.li);
          rows.set(c.id, row);
        }
        row.name.textContent = c.summary + (c.ttl === 0 ? "  ttl:0" : "");
        row.st.textContent = c.status === "pending" ? "running…" : `${c.status} · ${c.latency_ms} ms`;
        row.st.className = c.status === "pending" ? "st-pending" : c.status === "ok" ? "st-ok" : "st-bad";
        $("call-count").textContent = `(${rows.size})`;
      }
      if (ev.stage === "report") { es.close(); history.pushState({}, "", "/r/" + id); loadReport(id); }
      if (ev.stage === "error") { es.close(); fail(ev.message); }
    };
    es.onerror = () => { es.close(); };
  }
  function fail(msg) {
    $("go").disabled = false;
    $("form-error").textContent = msg;
    $("form-error").hidden = false;
    $("run").hidden = true;
  }

  /* ---------- report ---------- */
  async function loadReport(id) {
    const r = await fetch(`/audit/${id}`);
    if (!r.ok) { fail("Report not found."); return; }
    const rep = await r.json();
    $("go").disabled = false;
    $("run").hidden = true;
    renderReport(rep);
  }

  function dial(score, cls) {
    const R = 44, C = 2 * Math.PI * R, frac = Math.max(0, Math.min(100, score)) / 100;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 110 110"); svg.setAttribute("width", "112"); svg.setAttribute("class", "dial");
    svg.setAttribute("role", "img"); svg.setAttribute("aria-label", `${Math.round(score)} out of 100`);
    const mk = (tag, attrs) => { const e = document.createElementNS(ns, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
    const color = cls === "ai" ? "var(--ai)" : "var(--search)";
    svg.append(mk("circle", { cx: 55, cy: 55, r: R, fill: "none", stroke: "var(--line)", "stroke-width": 10 }),
      mk("circle", { cx: 55, cy: 55, r: R, fill: "none", stroke: color, "stroke-width": 10, "stroke-dasharray": `${C * frac} ${C}`, transform: "rotate(-90 55 55)", "stroke-linecap": "butt" }));
    const t = mk("text", { x: 55, y: 64, "text-anchor": "middle", "font-size": 30, fill: "var(--ink)" });
    t.textContent = Math.round(score);
    svg.append(t);
    return svg;
  }

  function scoreCard(title, sc, cls, extra) {
    const bars = sc.components.filter((c) => c.max_points > 0 || c.note).map((c) => h("div", { class: "bar" },
      h("span", { text: c.name.replace(/_/g, " ") }),
      h("span", { class: "track" }, h("span", { class: "fill", style: `width:${c.max_points ? (100 * c.points / c.max_points) : 0}%` })),
      h("span", { class: "mono", text: c.max_points ? `${Math.round(c.points)}/${c.max_points}` : "n/a" }),
      c.note ? h("small", { text: c.note }) : null));
    return h("div", { class: "score " + cls },
      dial(sc.total, cls),
      h("div", {}, h("h3", { text: title }), h("div", { class: "bars" }, bars)),
      sc.note ? h("p", { class: "note", text: sc.note }) : null, extra);
  }

  function verdict(r) {
    const pos = r.serp_card && r.serp_card.position;
    const rank = pos ? `ranks #${pos} for “${r.query}”` : (r.serp.some((p) => p.kind === "target_query" && !p.error) ? `is not in the top results for “${r.query}”` : "has no search data");
    if (r.could_not_read) return `AI tools could not read this page, and it ${rank}.`;
    return `AI can read ${Math.round(r.ars.total)}% of what it should, and the page ${rank}.`;
  }

  function renderReport(r) {
    window.__rep = r; // kept for wire redraws on resize
    const root = $("report");
    root.hidden = false;
    const head = h("div", {},
      h("p", { class: "verdict", text: verdict(r) }),
      h("p", { class: "meta" }, h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", text: r.url }),
        ` · query “${r.query}”${r.query_derived ? " (derived)" : ""} · answerability via ${r.answerability_method} · ${r.duration_s}s · ${r.endpoints_used.fetch || 0} Fetch + ${r.endpoints_used.search || 0} Search calls`),
      h("div", { class: "actions" },
        h("a", { class: "btn primary", href: `/audit/${r.id}/fixpack.zip`, text: "Download fix pack" }),
        h("button", { class: "btn", type: "button", onclick: () => startAudit(`/audit/${r.id}/reaudit`, null), text: "Re-audit" }),
        h("button", { class: "btn", type: "button", onclick: (e) => copy(location.origin + "/r/" + r.id, e.target, "Copy link"), text: "Copy link" }),
        h("a", { class: "btn", href: `/audit/${r.id}/report.md`, text: "Markdown" })),
      r.previous ? deltaBox(r.previous) : null);
    root.replaceChildren(head,
      h("div", { class: "scores" }, scoreCard("AI readability", r.ars, "ai"), scoreCard("Search visibility", r.svs, "search")),
      bridgeSection(r), aiSees(r), serpSection(r), deltaTable(r), fixSection(r), callLog(r), notesBlock(r));
    requestAnimationFrame(() => drawWires(r));
    window.scrollTo({ top: 0 });
  }

  function deltaBox(p) {
    const f = (n) => h("b", { class: n >= 0 ? "up" : "down", text: (n >= 0 ? "+" : "") + n });
    return h("div", { class: "delta" }, "Since the last audit of this page: AI readability ", f(p.ars_delta), ", search visibility ", f(p.svs_delta),
      p.rank_prev !== p.rank_now ? `, rank ${p.rank_prev || "none"} → ${p.rank_now || "none"}` : "",
      `. Fixed: ${p.fixed.length ? p.fixed.join(", ") : "none"}. New: ${p.new.length ? p.new.join(", ") : "none"}.`);
  }

  /* ---------- Gap Bridge (hero) ---------- */
  function bridgeSection(r) {
    const byId = Object.fromEntries(r.findings.map((f) => [f.id, f]));
    const causes = [...new Set(r.bridges.map((b) => b.cause_id))];
    const symptoms = [...new Set(r.bridges.map((b) => b.symptom_id))];
    const lonelyC = r.findings.filter((f) => f.category !== "serp" && !causes.includes(f.id) && (f.severity === "critical" || f.severity === "high"));
    const lonelyS = r.findings.filter((f) => f.category === "serp" && !symptoms.includes(f.id));
    const label = (id) => (byId[id] ? byId[id].title : id === "AI_ANSWER_VISIBILITY" ? "AI answer visibility (not Google rank)" : id);
    const node = (id, linked, side) => h("button", { type: "button", class: "node " + (linked ? "linked" : "lone"), "data-node": id, "data-side": side, onclick: () => hot(id) },
      label(id), byId[id] ? h("small", { text: `${byId[id].category} · ${byId[id].severity}` }) : null);
    const section = h("section", { id: "bridge-sec" },
      h("div", { class: "section-h" }, h("h2", { text: "Gap Bridge" }),
        h("p", { text: "Readability problems on the left, visibility symptoms on the right. A line exists only when both were observed in this audit. Dashed lines are inferred, solid are directly demonstrated." })));
    if (!r.bridges.length) {
      section.append(h("p", { class: "empty", text: "No evidence-backed link in this audit. A link needs both the cause and the symptom to be present." }));
    }
    const colsL = h("div", { class: "col-l" }, h("h3", { text: "What AI struggles with" }), h("div", { class: "nodes" }, causes.map((c) => node(c, true, "l")), lonelyC.map((f) => node(f.id, false, "l"))));
    const colsR = h("div", { class: "col-r" }, h("h3", { text: "What shows up in search and AI answers" }), h("div", { class: "nodes" }, symptoms.map((s) => node(s, true, "r")), lonelyS.map((f) => node(f.id, false, "r"))));
    const wrap = h("div", { class: "bridge", id: "bridge" }, h("div", { class: "bridge-cols" }, colsL, h("div", { class: "gap" }), colsR));
    const detail = h("div", { class: "bridge-detail" }, r.bridges.map((b) => h("div", { class: "link-card", "data-bridge": b.id },
      h("p", {}, h("strong", { text: label(b.cause_id) }), " → ", h("strong", { text: label(b.symptom_id) }), h("span", { class: "conf " + b.confidence, text: b.confidence })),
      h("p", { text: b.statement }), b.evidence.slice(0, 3).map((e) => h("p", { class: "ev", text: `${e.kind}: ${e.value}` })))));
    wrap.append(detail);
    section.append(wrap);
    return section;
  }
  function hot(id) {
    document.querySelectorAll(".node,.wire,.link-card").forEach((n) => n.classList.remove("hot"));
    document.querySelectorAll(`[data-node="${CSS.escape(id)}"]`).forEach((n) => n.classList.add("hot"));
    document.querySelectorAll(".wire").forEach((w) => { if (w.dataset.c === id || w.dataset.s === id) w.classList.add("hot"); });
    document.querySelectorAll(".link-card").forEach((c) => { const [a, b] = c.dataset.bridge.split("->"); if (a === id || b === id) c.classList.add("hot"); });
  }
  function drawWires(r) {
    const box = $("bridge");
    if (!box) return;
    box.querySelector(".wires")?.remove();
    if (window.matchMedia("(max-width:760px)").matches || !r.bridges.length) return;
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "wires");
    const bb = box.getBoundingClientRect();
    for (const b of r.bridges) {
      const a = box.querySelector(`[data-node="${CSS.escape(b.cause_id)}"][data-side="l"]`);
      const z = box.querySelector(`[data-node="${CSS.escape(b.symptom_id)}"][data-side="r"]`);
      if (!a || !z) continue;
      const ra = a.getBoundingClientRect(), rz = z.getBoundingClientRect();
      const x1 = ra.right - bb.left, y1 = ra.top + ra.height / 2 - bb.top, x2 = rz.left - bb.left, y2 = rz.top + rz.height / 2 - bb.top, mx = (x1 + x2) / 2;
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
      p.setAttribute("class", "wire " + b.confidence);
      p.dataset.c = b.cause_id; p.dataset.s = b.symptom_id;
      svg.append(p);
    }
    box.prepend(svg);
  }
  let resizeT;
  window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(() => window.__rep && drawWires(window.__rep), 150); });

  /* ---------- what AI sees ---------- */
  function aiSees(r) {
    const w = r.what_ai_sees;
    const sec = h("section", {}, h("div", { class: "section-h" }, h("h2", { text: "What AI sees" }),
      h("p", { text: `Left: the live page. Right: the text TinyFish Fetch extracted. Struck-through lines are boilerplate outside the main content (${w ? w.extraction_method : "n/a"}).` })));
    const lost = w && w.lost.length ? h("div", {}, h("h3", { text: "Lost or missing" }), h("ul", { class: "lostlist" }, w.lost.map((e) => h("li", {}, h("span", { class: "mono", text: e.kind + ": " }), e.value)))) : h("p", { class: "legend", text: "Nothing observed as lost." });
    const left = h("div", { class: "pane" }, h("h3", { text: "Original page" }), h("p", {}, h("a", { href: r.final_url || r.url, target: "_blank", rel: "noopener noreferrer", text: r.final_url || r.url })),
      h("p", { class: "legend", text: w ? `${w.rendered_chars.toLocaleString()} characters extracted; raw HTML (no JavaScript) holds ${w.raw_chars.toLocaleString()}.` : "" }), lost);
    const lines = w && w.lines.length ? w.lines.slice(0, 400).map((l) => h("div", { class: l.boilerplate ? "bp" : "", text: l.text })) : [h("div", { class: "empty", text: r.could_not_read ? "Fetch could not read this page." : "Empty extraction." })];
    sec.append(h("div", { class: "split" }, left, h("div", { class: "pane" }, h("h3", { text: "Extracted markdown" }), h("div", { class: "extract", tabindex: "0" }, lines))));
    return sec;
  }

  /* ---------- SERP ---------- */
  function serpSection(r) {
    const c = r.serp_card || {};
    const sec = h("section", {}, h("div", { class: "section-h" }, h("h2", { text: "How you appear in search" }),
      h("p", { text: `Real results from TinyFish Search. Indexation probe: ${c.indexation || "unknown"}; ${c.pages_checked || 0} results page(s) checked.` })));
    const you = h("div", { class: "serp-card you" }, h("div", { class: "lbl", text: c.position ? `You · position ${c.position}` : "You · not shown in results" }),
      h("div", { class: "u", text: c.serp_url || r.url }), h("div", { class: "t", text: c.serp_title || "(no result entry for this page)" }), h("p", { class: "s", text: c.serp_snippet || "" }),
      h("div", { class: "mismatch" }, h("div", {}, h("b", { text: "Your <title>: " }), c.page_title || "(none)"), h("div", {}, h("b", { text: "Your meta description: " }), c.meta_description || "(none)")));
    const grid = h("div", { class: "serp-grid" }, you, (c.competitors || []).map((x) => h("div", { class: "serp-card" }, h("div", { class: "lbl", text: `Competitor · position ${x.position}` }),
      h("div", { class: "u", text: x.url }), h("div", { class: "t", text: x.title }), h("p", { class: "s", text: x.snippet }))));
    sec.append(grid);
    return sec;
  }

  function deltaTable(r) {
    if (!r.delta_table.length) return h("span");
    const head = h("tr", {}, h("th", { text: "Feature" }), h("th", { text: "This page" }), r.competitors.map((c) => h("th", { text: `#${c.serp_position || "?"}` })), h("th", { text: "Status" }));
    const fmt = (v) => (v === true ? "yes" : v === false ? "no" : v == null ? "-" : String(v));
    const rows = r.delta_table.map((x) => h("tr", {}, h("td", { text: x.feature }), h("td", { class: x.status === "worse" ? "worse" : "", text: fmt(x.target) }), x.competitors.map((v) => h("td", { text: fmt(v) })), h("td", { class: x.status === "worse" ? "worse" : "", text: x.status })));
    return h("section", {}, h("div", { class: "section-h" }, h("h2", { text: "Competitor delta" }), h("p", { text: "The pages outranking you, fetched live and measured the same way." })),
      h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, rows))));
  }

  /* ---------- fixes ---------- */
  function fixSection(r) {
    const fs = [...r.findings].sort((a, b) => SEV[a.severity] - SEV[b.severity] || b.bridge_to.length - a.bridge_to.length || a.fix.effort_minutes - b.fix.effort_minutes);
    const key = "done:" + r.id;
    const done = new Set(store.get(key) || []);
    const sec = h("section", {}, h("div", { class: "section-h" }, h("h2", { text: `Fix list (${fs.length})` }), h("p", { text: "Highest impact first, quickest first within the same impact. Every item shows the evidence it rests on." })));
    if (!fs.length) sec.append(h("p", { class: "empty", text: "No findings survived the evidence lint." }));
    for (const f of fs) {
      const art = h("article", { class: `fix ${f.severity}${done.has(f.id) ? " done" : ""}` });
      const cb = h("input", { type: "checkbox", "aria-label": `Mark done: ${f.title}`, checked: done.has(f.id), onchange: () => { cb.checked ? done.add(f.id) : done.delete(f.id); art.classList.toggle("done", cb.checked); store.set(key, [...done]); } });
      art.append(h("header", {}, cb, h("div", {}, h("h3", { text: f.title }),
        h("div", { class: "chips" }, h("span", { class: "chip sev", text: f.severity }), h("span", { class: "chip", text: f.category }), h("span", { class: "chip", text: f.confidence }), h("span", { class: "chip", text: `~${f.fix.effort_minutes} min` }), f.bridge_to.length ? h("span", { class: "chip", text: "linked in Gap Bridge" }) : null))));
      art.append(h("div", {}, f.evidence.map((e) => h("p", { class: "ev", text: `${e.kind}: ${e.value}` }))));
      art.append(h("details", {}, h("summary", { text: "Impact and fix" }), h("p", {}, h("b", { text: "AI tools: " }), f.ai_impact), h("p", {}, h("b", { text: "Search: " }), f.search_impact),
        h("ol", {}, f.fix.steps.map((s) => h("li", { text: s }))), f.fix.where_to_paste ? h("p", { class: "legend", text: "Paste into: " + f.fix.where_to_paste }) : null,
        f.fix.snippet ? h("div", {}, h("div", { class: "snip-head" }, h("span", { text: f.fix.snippet_lang || "snippet" }), h("button", { class: "btn small", type: "button", onclick: (e) => copy(f.fix.snippet, e.target, "Copy"), text: "Copy" })), h("pre", { class: "snippet", text: f.fix.snippet })) : null));
      sec.append(art);
    }
    return sec;
  }

  function callLog(r) {
    const rows = r.calls.map((c, i) => h("tr", {}, h("td", { text: i + 1 }), h("td", { text: c.endpoint }), h("td", { text: c.summary }), h("td", { text: c.ttl == null ? "-" : c.ttl }), h("td", { text: `${c.latency_ms} ms` }), h("td", { text: c.status })));
    return h("section", {}, h("div", { class: "section-h" }, h("h2", { text: "TinyFish call log" }), h("p", { text: "Every Fetch ran with ttl 0, so nothing was served from cache." })),
      h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["#", "Endpoint", "Call", "ttl", "Latency", "Status"].map((t) => h("th", { text: t })))), h("tbody", {}, rows))));
  }
  function notesBlock(r) {
    if (!r.notes.length && !r.lint_dropped.length) return h("span");
    return h("section", {}, h("h2", { text: "Notes" }), h("ul", { class: "lostlist" }, r.notes.map((n) => h("li", { text: n })), r.lint_dropped.map((d) => h("li", { text: `Dropped by evidence lint: ${d.id} (${d.reason})` }))));
  }

  async function copy(text, btn, label) {
    try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; } catch (e) { btn.textContent = "Copy failed"; }
    setTimeout(() => { btn.textContent = label; }, 1500);
  }

  const m = location.pathname.match(/^\/r\/([A-Za-z0-9]+)/);
  if (m) loadReport(m[1]);
})();
