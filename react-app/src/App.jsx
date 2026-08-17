import { useState, useEffect, useRef, useCallback } from "react";
import "./style.css";


const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const n2 = (x) => (x == null ? "-" : Number(x).toFixed(2));
const n1 = (x) => (x == null ? "-" : Number(x).toFixed(1));
const REQUIRED_COLS = ["team_name", "event_type", "minute"];

const COL = (teams, t) => (t === teams[0] ? "#3b82f6" : "#ef4444");
const RGBA = (teams, t, a) => (t === teams[0] ? `rgba(59,130,246,${a})` : `rgba(239,68,68,${a})`);

function stat(k, v) {
  const isNumeric = /^-?[\d.,%\s]+$/.test(String(v).trim()) && String(v).trim() !== "";
  return `<div class="stat"><div class="k">${k}</div><div class="v ${isNumeric ? "v-num" : "v-text"}">${v}</div></div>`;
}

function pitchLines() {
  const s = 'stroke="rgba(255,255,255,.45)" stroke-width="0.4" fill="none"';
  return `<rect x="0" y="0" width="120" height="80" ${s}/>
    <line x1="60" y1="0" x2="60" y2="80" ${s}/><circle cx="60" cy="40" r="9" ${s}/>
    <rect x="0" y="18" width="18" height="44" ${s}/><rect x="102" y="18" width="18" height="44" ${s}/>
    <rect x="0" y="30" width="6" height="20" ${s}/><rect x="114" y="30" width="6" height="20" ${s}/>`;
}
const fy = (y) => y; 


function columnsCard(allMatches) {
  const cols = (allMatches && allMatches[0] && allMatches[0].columns) || REQUIRED_COLS;
  const required = cols.filter((c) => REQUIRED_COLS.includes(c));
  const optional = cols.filter((c) => !REQUIRED_COLS.includes(c));
  const chip = (c, req) => `<span class="chip ${req ? "req" : ""}">${esc(c)}</span>`;
  return `<div class="card"><h3>Add your own match</h3>
    <p class="muted">Use the <b>Upload</b> control in the bar above to add StatsBomb-format event data. A single <code>.csv</code> adds one match; a multi-sheet Excel workbook (<code>.xlsx</code>) adds <b>every sheet as its own match</b>, all at once. The new matches then appear in the dropdown like the built-ins. If a file has no <code>xt_added</code> column it is filled with 0, so the timeline and verdict still run.</p>
    <h4>Required &middot; every file needs these three</h4>
    <div class="cols-list">${required.map((c) => chip(c, true)).join("")}</div>
    <h4>Optional &middot; unlock the full analysis (network positions, passes, pressing, xT)</h4>
    <div class="cols-list">${optional.map((c) => chip(c, false)).join("")}</div>
  </div>`;
}

function renderLoad(S) {
  const m = S.info || {};
  return `<div class="card match-hero">
    <div class="eyebrow">${esc(m.competition || "")} &middot; ${esc(m.date_display || S.match)} &middot; ${m.events || "?"} events</div>
    <div class="matchup">
      <div class="side home"><span class="dot" style="background:var(--home)"></span><span class="team-name">${esc(m.home_team || "-")}</span></div>
      <div class="vs">vs</div>
      <div class="side away"><span class="team-name">${esc(m.away_team || "-")}</span><span class="dot" style="background:var(--away)"></span></div>
    </div>
    <div class="statgrid">
      ${stat("Home", esc(m.home_team || "-"))}
      ${stat("Away", esc(m.away_team || "-"))}
      ${stat("Events", m.events || "-")}
      ${stat("Teams", S.teams.length)}
    </div>
    <p class="muted">Move through the six steps above. Every module runs on this match's real event data; steps 2-4 show both teams side by side.</p>
  </div>
  ${columnsCard(S.allMatches)}`;
}

function networkSVG(teams, net, team) {
  const maxW = Math.max(1, ...net.edges.map((e) => e.weight));
  const maxInv = Math.max(1, ...net.players.map((p) => p.total_involvement));
  let g = `<svg class="pitch" viewBox="0 0 120 80"><rect x="0" y="0" width="120" height="80" fill="var(--grass)"/>${pitchLines()}`;
  net.edges.filter((e) => e.weight >= 3).forEach((e) => {
    g += `<line x1="${e.source_x}" y1="${fy(e.source_y)}" x2="${e.target_x}" y2="${fy(e.target_y)}"
      stroke="${RGBA(teams, team, 0.15 + 0.55 * (e.weight / maxW))}" stroke-width="${(0.25 + 1.7 * (e.weight / maxW)).toFixed(2)}"/>`;
  });
  const hub = net.metrics && net.metrics.hub;
  net.players.forEach((p) => {
    const r = 1.6 + 3.2 * (p.total_involvement / maxInv);
    const isHub = !!hub && (p.nickname === hub || p.name === hub);
    if (isHub) {
      g += `<circle cx="${p.avg_x}" cy="${fy(p.avg_y)}" r="${(r + 1.7).toFixed(2)}" fill="none" stroke="var(--accent)" stroke-width="0.6" stroke-dasharray="1.3,1"/>`;
    }
    g += `<circle cx="${p.avg_x}" cy="${fy(p.avg_y)}" r="${r.toFixed(2)}" fill="${COL(teams, team)}" stroke="${isHub ? "var(--accent)" : "#fff"}" stroke-width="${isHub ? "0.9" : "0.4"}"/>
      <text x="${p.avg_x}" y="${fy(p.avg_y) - r - (isHub ? 2.3 : 0.6)}" text-anchor="middle" font-size="${isHub ? "2.7" : "2.4"}" font-weight="${isHub ? "700" : "400"}" fill="${isHub ? "var(--accent)" : "#fff"}" style="paint-order:stroke;stroke:#000;stroke-width:.6">${esc(p.nickname || p.name)}${isHub ? " \u2605" : ""}</text>`;
  });
  return g + "</svg>";
}

async function renderNetwork(S, api) {
  const nets = await Promise.all(S.teams.map((t) => api({ command: "network", match_date: S.match, team: t })));
  const cols = S.teams.map((t, i) => {
    const net = nets[i], m = net.metrics;
    const rows = [...net.players].sort((a, b) => b.total_involvement - a.total_involvement).slice(0, 8).map((p) =>
      `<tr><td>${esc(p.nickname || p.name)}</td><td class="num">${p.passes_made}</td><td class="num">${p.passes_received}</td><td class="num">${n2(p.degree_centrality)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      ${networkSVG(S.teams, net, t)}
      <div class="statgrid">${stat("Density", (m.density * 100).toFixed(0) + "%")}${stat("Hub", esc(m.hub))}${stat("Players", m.num_players)}${stat("Connections", m.num_edges)}</div>
      <h4>Most involved</h4>
      <table><tr><th>Player</th><th class="num">Made</th><th class="num">Recv</th><th class="num">Degree</th></tr>${rows}</table>
    </div>`;
  });
  return `<div class="card"><h3>The passing network</h3><p class="muted">Each dot is a player at their average passing position, sized by involvement; lines are pass combinations (3+), thicker = more used. Density = combinations used / possible; the hub is the most involved player.</p></div>
    <div class="cols">${cols.join("")}</div>`;
}

async function renderCentrality(S, api) {
  const data = await Promise.all(S.teams.map((t) => Promise.all([
    api({ command: "network", match_date: S.match, team: t }),
    api({ command: "tactical", match_date: S.match, team: t }),
  ])));
  const cols = S.teams.map((t, i) => {
    const [net, tac] = data[i];
    const cen = tac.centrality || {};
    const top = (key) => [...net.players].sort((a, b) => (b[key] || 0) - (a[key] || 0))[0];
    const wl = net.weakest_link?.weakest_link || {};
    const cp = cen.centrality_percentage;
    const band = cp == null ? "" : cp < 12 ? "spread evenly" : cp < 18 ? "slight hub" : cp < 25 ? "one/two carry it" : "hub-dependent";
    const rows = [...net.players].sort((a, b) => b.betweenness_centrality - a.betweenness_centrality).slice(0, 8).map((p) =>
      `<tr><td>${esc(p.nickname || p.name)}</td><td class="num">${n2(p.betweenness_centrality)}</td><td class="num">${n2(p.eigenvector_centrality)}</td><td class="num">${n2(p.clustering_coefficient)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      <div class="statgrid">
        ${stat("Grund centralisation", cp == null ? "-" : cp.toFixed(0) + "%")}
        ${stat("Style", esc(cen.style || "-"))}
        ${stat("Top connector", esc((top("betweenness_centrality") || {}).nickname || "-"))}
        ${stat("Core (eigenvector)", esc((top("eigenvector_centrality") || {}).nickname || "-"))}
      </div>
      <p class="muted" style="font-size:12px">${band ? "Centralisation band: <b>" + band + "</b>." : ""}</p>
      <h4>Centrality (top by betweenness)</h4>
      <table><tr><th>Player</th><th class="num">Between</th><th class="num">Eigen</th><th class="num">Cluster</th></tr>${rows}</table>
      <h4>Weakest link (press target)</h4>
      <div class="stat"><div class="k">${esc(wl.nickname || wl.player || "-")} &middot; score ${n2(wl.weakness_score)}</div>
        <div class="v" style="font-size:12px;font-weight:500;color:var(--muted)">${(wl.reasons || []).map(esc).join(" &middot; ")}</div></div>
    </div>`;
  });
  return `<div class="card"><h3>Centrality &amp; roles</h3><p class="muted">Betweenness = the connector; eigenvector = connected to the well-connected; clustering = tight triangles. Grund centralisation shows how much the passing leans on one hub; the weakest link is the man to press.</p></div>
    <div class="cols">${cols.join("")}</div>`;
}

function heatmapSVG(zones) {
  const max = Math.max(1, ...zones.map((z) => z.count));
  let g = `<svg class="pitch" viewBox="0 0 120 80"><rect x="0" y="0" width="120" height="80" fill="var(--grass)"/>`;
  zones.forEach((z) => {
    const x = z.col * 24, y = z.row * 16, inten = z.count / max;
    g += `<rect x="${x}" y="${y}" width="24" height="16" fill="rgba(227,178,60,${(0.08 + 0.82 * inten).toFixed(2)})" stroke="rgba(255,255,255,.2)" stroke-width="0.3"/>
      <text x="${x + 12}" y="${y + 9}" text-anchor="middle" font-size="3" fill="#fff" style="paint-order:stroke;stroke:#000;stroke-width:.5">${z.count || ""}</text>`;
  });
  return g + pitchLines() + "</svg>";
}

function sonarSVG(teams, counts, team) {
  const LABELS = ["forward", "forward_right", "right", "back_right", "back", "back_left", "left", "forward_left"];
  const ANGLES = [270, 315, 0, 45, 90, 135, 180, 225];
  counts = counts || {};
  const max = Math.max(1, ...LABELS.map((l) => counts[l] || 0));
  const cx = 50, cy = 50, R = 30;
  const pts = LABELS.map((l, i) => {
    const a = ANGLES[i] * Math.PI / 180, r = ((counts[l] || 0) / max) * R;
    return `${(cx + Math.cos(a) * r).toFixed(1)},${(cy + Math.sin(a) * r).toFixed(1)}`;
  }).join(" ");
  let g = `<svg viewBox="0 0 100 100" style="width:100%;max-width:260px;display:block;margin:0 auto">`;
  [0.25, 0.5, 0.75, 1].forEach((f) => (g += `<circle cx="${cx}" cy="${cy}" r="${(R * f).toFixed(1)}" fill="none" stroke="var(--line)" stroke-width="0.4"/>`));
  ANGLES.forEach((a) => {
    const rad = a * Math.PI / 180;
    g += `<line x1="${cx}" y1="${cy}" x2="${(cx + Math.cos(rad) * R).toFixed(1)}" y2="${(cy + Math.sin(rad) * R).toFixed(1)}" stroke="var(--line)" stroke-width="0.35"/>`;
  });
  g += `<polygon points="${pts}" fill="${RGBA(teams, team, 0.35)}" stroke="${COL(teams, team)}" stroke-width="1"/>`;
  LABELS.forEach((l, i) => {
    const rad = ANGLES[i] * Math.PI / 180, lr = R + 9;
    g += `<text x="${(cx + Math.cos(rad) * lr).toFixed(1)}" y="${(cy + Math.sin(rad) * lr).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" font-size="3.1" fill="var(--muted)">${l.replace("_", " ")}</text>`;
  });
  return g + `</svg>`;
}

function shape(net) {
  const P = net.players;
  const ys = P.map((p) => p.avg_y), xs = P.map((p) => p.avg_x);
  const width = Math.max(...ys) - Math.min(...ys), depth = Math.max(...xs) - Math.min(...xs);
  let sum = 0, cnt = 0;
  for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
    sum += Math.hypot(P[i].avg_x - P[j].avg_x, P[i].avg_y - P[j].avg_y); cnt++;
  }
  const comp = cnt ? 100 / (sum / cnt) : 0;
  return { width, depth, comp };
}

async function renderTactical(S, api) {
  const cmp = await api({ command: "compare", match_date: S.match });
  const data = await Promise.all(S.teams.map((t) => Promise.all([
    api({ command: "tactical_map", match_date: S.match, team: t }),
    api({ command: "insights", match_date: S.match, team: t }),
    api({ command: "zone_connections", match_date: S.match, team: t }),
    api({ command: "network", match_date: S.match, team: t }),
  ])));
  const cols = S.teams.map((t, i) => {
    const [tm, ins, zc, net] = data[i];
    const c = (cmp.teams || {})[t] || {};
    const ppda = c.ppda?.ppda, tilt = c.field_tilt?.field_tilt;
    const sh = shape(net);
    const tot = zc.progressive_passes + zc.regressive_passes + zc.lateral_passes || 1;
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      <div class="statgrid">
        ${stat("PPDA", ppda == null ? "-" : n1(ppda))}
        ${stat("Field tilt", tilt == null ? "-" : tilt.toFixed(0) + "%")}
        ${stat("Progressive", Math.round(100 * zc.progressive_passes / tot) + "%")}
        ${stat("Shape W/D", sh.width.toFixed(0) + " / " + sh.depth.toFixed(0))}
      </div>
      <h4>25-zone passing map (attacking &rarr;)</h4>${heatmapSVG(tm.zones)}
      <h4>Direction sonar</h4>${sonarSVG(S.teams, ins.pass_directions && ins.pass_directions.counts, t)}
      <h4>Zone flow</h4>
      <div class="statgrid">${stat("Progressive", zc.progressive_passes)}${stat("Lateral", zc.lateral_passes)}${stat("Regressive", zc.regressive_passes)}</div>
    </div>`;
  });
  return `<div class="card"><h3>Tactical geography</h3><p class="muted">Where each team plays and how hard it presses. PPDA: lower = more aggressive. Field tilt: share of all final-third passes. The 25-zone map colours by pass volume; the sonar shows passing direction (forward points up).</p></div>
    <div class="cols">${cols.join("")}</div>`;
}

function verdictCard(v) {
  const js = v.justice_score || 0;
  return `<div class="verdict">
    <div class="score">${esc(v.score || "")} <span class="muted" style="font-size:16px">${esc(v.winner || "")}</span></div>
    <div class="headline">${esc(v.verdict_headline || "")}</div>
    <div style="margin:10px 0"><div class="muted" style="font-size:12px">Justice score ${js}/100</div><div class="bar-h"><span style="width:${js}%"></span></div></div>
    <p>${esc(v.narrative || "")}</p></div>`;
}

function goalPitch(teams, g) {
  let s = `<svg class="pitch" viewBox="0 0 120 80" style="max-height:160px"><rect x="0" y="0" width="120" height="80" fill="var(--grass)"/>${pitchLines()}`;
  (g.buildup_sequence || []).forEach((ev) => {
    if (ev.end_x == null) return;
    const good = (ev.xt_added || 0) >= 0;
    s += `<line x1="${ev.x}" y1="${fy(ev.y)}" x2="${ev.end_x}" y2="${fy(ev.end_y)}" stroke="${good ? "#22c55e" : "#94a3b8"}" stroke-width="0.8" opacity="0.9"/>
      <circle cx="${ev.x}" cy="${fy(ev.y)}" r="0.8" fill="#fff"/>`;
  });
  s += `<circle cx="${g.x}" cy="${fy(g.y)}" r="1.8" fill="var(--accent)" stroke="#000" stroke-width="0.4"/></svg>`;
  return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(teams, g.team)}"></span>${esc(g.scorer)} &middot; ${g.minute}'</div>
    <p class="muted" style="font-size:12px">xG ${n2(g.xg)} &middot; build-up xT ${n2(g.buildup_xt)} over ${g.buildup_events} events</p>${s}</div>`;
}

async function renderStory(S, api) {
  const [tl, goals] = await Promise.all([
    api({ command: "timeline", match_date: S.match }),
    api({ command: "goals", match_date: S.match }),
  ]);
  const shots = await Promise.all(S.teams.map((t) => api({ command: "shots", match_date: S.match, team: t })));
  const strip = (tl.periods || []).map((p) => {
    let lead = S.teams[0], best = -1;
    S.teams.forEach((t) => { const q = p.teams?.[t]?.possession ?? 0; if (q > best) { best = q; lead = t; } });
    return `<div class="seg" title="${p.label}: ${lead} ${best.toFixed(0)}%" style="height:${20 + 0.8 * best}%;background:${COL(S.teams, lead)}"></div>`;
  }).join("");
  const shifts = tl.insights?.momentum_shifts?.length ?? 0;
  const shotTables = S.teams.map((t, i) => {
    const rows = (shots[i].players || []).slice(0, 6).map((p) =>
      `<tr><td>${esc(p.nickname || p.player)}</td><td class="num">${p.shots}</td><td class="num">${p.goals}</td><td class="num">${n2(p.xg)}</td><td class="num" style="color:${p.xg_difference >= 0 ? "var(--good)" : "var(--bad)"}">${p.xg_difference >= 0 ? "+" : ""}${n2(p.xg_difference)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)} shots</div>
      <table><tr><th>Player</th><th class="num">Sh</th><th class="num">G</th><th class="num">xG</th><th class="num">xG diff</th></tr>${rows}</table></div>`;
  }).join("");
  const goalCards = (goals.goals || []).map((g) => goalPitch(S.teams, g)).join("");
  return `<div class="card"><h3>The match story &amp; verdict</h3>${verdictCard(tl.verdict || {})}</div>
    <div class="card"><h4>Timeline (5-minute windows, coloured by who led)</h4>
      <div class="timeline-strip">${strip}</div>
      <p class="muted" style="font-size:12px;margin-top:8px">${shifts} momentum shift${shifts === 1 ? "" : "s"} across the match.</p></div>
    <div class="section-head"><h3>Goals - build-up xT trails</h3><p class="muted">The passing that led to each goal - green legs added positive threat, grey legs didn't.</p></div>
    ${goalCards ? `<div class="cols">${goalCards}</div>` : '<p class="muted">No goals in the data.</p>'}
    <div class="cols">${shotTables}</div>`;
}

async function renderReport(S, api) {
  const [cmp, tl, goals] = await Promise.all([
    api({ command: "compare", match_date: S.match }),
    api({ command: "timeline", match_date: S.match }),
    api({ command: "goals", match_date: S.match }),
  ]);
  const per = await Promise.all(S.teams.map((t) => Promise.all([
    api({ command: "network", match_date: S.match, team: t }),
    api({ command: "tactical", match_date: S.match, team: t }),
    api({ command: "tactical_map", match_date: S.match, team: t }),
    api({ command: "insights", match_date: S.match, team: t }),
    api({ command: "zone_connections", match_date: S.match, team: t }),
    api({ command: "shots", match_date: S.match, team: t }),
  ])));
  const m = S.info || {}, v = tl.verdict || {};

  const netCards = S.teams.map((t, i) => {
    const net = per[i][0], mm = net.metrics;
    const rows = [...net.players].sort((a, b) => b.total_involvement - a.total_involvement).slice(0, 6).map((p) =>
      `<tr><td>${esc(p.nickname || p.name)}</td><td class="num">${p.passes_made}</td><td class="num">${p.passes_received}</td><td class="num">${n2(p.degree_centrality)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      ${networkSVG(S.teams, net, t)}
      <div class="statgrid">${stat("Density", (mm.density * 100).toFixed(0) + "%")}${stat("Hub", esc(mm.hub))}${stat("Players", mm.num_players)}${stat("Links", mm.num_edges)}</div>
      <table><tr><th>Player</th><th class="num">Made</th><th class="num">Recv</th><th class="num">Degree</th></tr>${rows}</table></div>`;
  }).join("");

  const cenCards = S.teams.map((t, i) => {
    const net = per[i][0], cen = (per[i][1].centrality) || {}, wl = net.weakest_link?.weakest_link || {};
    const rows = [...net.players].sort((a, b) => b.betweenness_centrality - a.betweenness_centrality).slice(0, 6).map((p) =>
      `<tr><td>${esc(p.nickname || p.name)}</td><td class="num">${n2(p.betweenness_centrality)}</td><td class="num">${n2(p.eigenvector_centrality)}</td><td class="num">${n2(p.clustering_coefficient)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      <div class="statgrid">${stat("Grund", cen.centrality_percentage == null ? "-" : cen.centrality_percentage.toFixed(0) + "%")}${stat("Style", esc(cen.style || "-"))}${stat("Weakest link", esc(wl.nickname || wl.player || "-"))}</div>
      <table><tr><th>Player</th><th class="num">Between</th><th class="num">Eigen</th><th class="num">Cluster</th></tr>${rows}</table>
      <p class="muted" style="font-size:12px">${(wl.reasons || []).map(esc).join(" &middot; ")}</p></div>`;
  }).join("");

  const tacCards = S.teams.map((t, i) => {
    const net = per[i][0], tm = per[i][2], ins = per[i][3], zc = per[i][4];
    const c = (cmp.teams || {})[t] || {}, sh = shape(net);
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</div>
      <div class="statgrid">${stat("PPDA", c.ppda?.ppda == null ? "-" : n1(c.ppda.ppda))}${stat("Field tilt", c.field_tilt?.field_tilt == null ? "-" : c.field_tilt.field_tilt.toFixed(0) + "%")}${stat("Shape W/D", sh.width.toFixed(0) + "/" + sh.depth.toFixed(0))}${stat("Progressive", zc.progressive_passes)}</div>
      <h4>25-zone map</h4>${heatmapSVG(tm.zones)}<h4>Direction sonar</h4>${sonarSVG(S.teams, ins.pass_directions && ins.pass_directions.counts, t)}</div>`;
  }).join("");

  const strip = (tl.periods || []).map((p) => {
    let lead = S.teams[0], best = -1;
    S.teams.forEach((t) => { const q = p.teams?.[t]?.possession ?? 0; if (q > best) { best = q; lead = t; } });
    return `<div class="seg" title="${p.label}" style="height:${20 + 0.8 * best}%;background:${COL(S.teams, lead)}"></div>`;
  }).join("");
  const shotCards = S.teams.map((t, i) => {
    const rows = (per[i][5].players || []).slice(0, 6).map((p) =>
      `<tr><td>${esc(p.nickname || p.player)}</td><td class="num">${p.shots}</td><td class="num">${p.goals}</td><td class="num">${n2(p.xg)}</td><td class="num" style="color:${p.xg_difference >= 0 ? "var(--good)" : "var(--bad)"}">${p.xg_difference >= 0 ? "+" : ""}${n2(p.xg_difference)}</td></tr>`).join("");
    return `<div class="card"><div class="teamhdr"><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)} shots</div>
      <table><tr><th>Player</th><th class="num">Sh</th><th class="num">G</th><th class="num">xG</th><th class="num">xG diff</th></tr>${rows}</table></div>`;
  }).join("");

  const h2h = S.teams.map((t, i) => {
    const c = (cmp.teams || {})[t] || {}, mm = per[i][0].metrics, wl = per[i][0].weakest_link?.weakest_link || {};
    return `<tr><td><span class="dot" style="background:${COL(S.teams, t)}"></span>${esc(t)}</td><td class="num">${c.passes ?? "-"}</td><td class="num">${(mm.density * 100).toFixed(0)}%</td><td>${esc(mm.hub)}</td><td class="num">${c.ppda?.ppda == null ? "-" : n1(c.ppda.ppda)}</td><td class="num">${c.field_tilt?.field_tilt == null ? "-" : c.field_tilt.field_tilt.toFixed(0) + "%"}</td><td class="num">${n2(c.xt)}</td><td>${esc(wl.nickname || "-")}</td></tr>`;
  }).join("");

  return `<div class="card"><h3 style="display:flex;justify-content:space-between;align-items:center;gap:12px">Full report - the complete analysis
    <button id="printBtn" class="btn">Print / Save as PDF</button></h3>
    <p><b>${esc(m.home_team)} vs ${esc(m.away_team)}</b> - ${esc(m.competition)}, ${esc(m.date_display || S.match)}.</p></div>
    <div class="card"><h4>1. Executive summary</h4>${verdictCard(v)}
      <table style="margin-top:12px"><tr><th>Team</th><th class="num">Passes</th><th class="num">Density</th><th>Hub</th><th class="num">PPDA</th><th class="num">Field tilt</th><th class="num">xT</th><th>Weakest link</th></tr>${h2h}</table></div>
    <div class="card"><h4>2. Passing networks</h4><div class="cols">${netCards}</div></div>
    <div class="card"><h4>3. Centrality &amp; roles</h4><div class="cols">${cenCards}</div></div>
    <div class="card"><h4>4. Tactical geography</h4><div class="cols">${tacCards}</div></div>
    <div class="card"><h4>5. Match story</h4>
      <div class="timeline-strip">${strip}</div>
      <h4>Goals - build-up xT trails</h4><div class="cols">${(goals.goals || []).map((g) => goalPitch(S.teams, g)).join("") || '<p class="muted">No goals in the data.</p>'}</div>
      <div class="cols">${shotCards}</div></div>
    <div class="card"><h4>6. How to read it</h4><p class="muted">The verdict's justice score (25 + 18.75 per metric the winner led, out of xG / xT / possession / passes) says how well the result matched the balance of play. A dominant network (high density, distributed hub) with strong pressing (low PPDA) and territory (high field tilt) that agrees with the scoreline is a deserved win; when they disagree, it is a smash-and-grab.</p></div>`;
}

function svgTrendChart(trend, key, { label = "", suffix = "" } = {}) {
  const vals = trend.map((m) => m[key]).filter((v) => v != null);
  if (!vals.length) return `<p class="muted" style="font-size:12px">Not enough data for ${esc(label)}.</p>`;
  const w = 320, h = 130, padL = 30, padR = 10, padT = 12, padB = 22;
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const stepX = (w - padL - padR) / Math.max(trend.length - 1, 1);
  const pts = trend.map((m, i) => {
    const v = m[key];
    return {
      x: padL + i * stepX,
      y: v == null ? null : padT + (h - padT - padB) * (1 - (v - min) / range),
      v, date: m.match_date, opp: m.opponent,
    };
  });
  const valid = pts.filter((p) => p.y != null);
  const line = valid.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = valid.map((p) =>
    `<circle class="pt" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.6"><title>${esc(p.date)} vs ${esc(p.opp || "-")}: ${n2(p.v)}${suffix}</title></circle>`
  ).join("");
  return `<svg class="trend-chart" viewBox="0 0 ${w} ${h}">
    <line class="axis" x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}"/>
    <line class="axis" x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}"/>
    <text x="2" y="${padT + 4}">${n1(max)}${suffix}</text>
    <text x="2" y="${h - padB}">${n1(min)}${suffix}</text>
    <polyline class="line" points="${line}"/>
    ${dots}
  </svg>`;
}

function renderOpponentProfile(profile) {
  const a = profile.averages || {};
  const rows = (profile.trend || []).map((m) =>
    `<tr><td>${esc(m.match_date)}</td><td>${esc(m.opponent || "-")}</td>
      <td class="num">${m.ppda == null ? "-" : n1(m.ppda)}</td>
      <td class="num">${m.field_tilt == null ? "-" : m.field_tilt + "%"}</td>
      <td class="num">${m.density == null ? "-" : (m.density * 100).toFixed(0) + "%"}</td>
      <td>${esc(m.hub || "-")}</td></tr>`
  ).join("");
  const takeaways = (profile.takeaways || []).map((t) => `<li>${esc(t)}</li>`).join("");
  return `<div class="card match-hero">
      <div class="eyebrow">Opponent scout &middot; ${profile.matches_analyzed} match${profile.matches_analyzed === 1 ? "" : "es"} analyzed</div>
      <div class="matchup"><div class="side home"><span class="team-name">${esc(profile.team)}</span></div></div>
      <div class="statgrid">
        ${stat("Avg PPDA", a.ppda == null ? "-" : a.ppda)}
        ${stat("Avg field tilt", a.field_tilt == null ? "-" : a.field_tilt + "%")}
        ${stat("Avg density", a.density == null ? "-" : (a.density * 100).toFixed(0) + "%")}
        ${stat("Avg centralisation", a.centrality_percentage == null ? "-" : a.centrality_percentage + "%")}
        ${stat("Most common hub", esc(profile.most_common_hub || "-"))}
        ${stat("Most common style", esc(profile.most_common_style || "-"))}
      </div>
    </div>
    <div class="card"><h3>Scouting takeaways</h3><ul class="takeaways">${takeaways || '<li>Not enough data yet.</li>'}</ul></div>
    <div class="cols">
      <div class="card"><h4>PPDA trend &middot; lower = presses higher</h4>${svgTrendChart(profile.trend, "ppda", { label: "PPDA" })}</div>
      <div class="card"><h4>Field tilt trend</h4>${svgTrendChart(profile.trend, "field_tilt", { label: "Field tilt", suffix: "%" })}</div>
    </div>
    <div class="card"><h4>Match-by-match</h4>
      <table><tr><th>Match</th><th>Opponent</th><th class="num">PPDA</th><th class="num">Field tilt</th><th class="num">Density</th><th>Hub</th></tr>${rows}</table>
    </div>`;
}

function renderCompareTeams(a, b) {
  const aa = a.averages || {}, bb = b.averages || {};
  // [label, value_a, value_b, direction] - direction says which side "wins" that metric
  const metricRows = [
    ["Avg PPDA (pressing intensity)", aa.ppda, bb.ppda, "low", ""],
    ["Avg field tilt", aa.field_tilt, bb.field_tilt, "high", "%"],
    ["Avg network density", aa.density != null ? aa.density * 100 : null, bb.density != null ? bb.density * 100 : null, "high", "%"],
    ["Avg centralisation", aa.centrality_percentage, bb.centrality_percentage, "neutral", "%"],
  ];
  const h2hRows = metricRows.map(([label, va, vb, dir, suffix]) => {
    let aStyle = "", bStyle = "";
    if (va != null && vb != null && dir !== "neutral" && va !== vb) {
      const aBetter = dir === "low" ? va < vb : va > vb;
      aStyle = aBetter ? ' style="color:var(--good);font-weight:700"' : "";
      bStyle = !aBetter ? ' style="color:var(--good);font-weight:700"' : "";
    }
    return `<tr><td>${label}</td>
      <td class="num"${aStyle}>${va == null ? "-" : n1(va) + suffix}</td>
      <td class="num"${bStyle}>${vb == null ? "-" : n1(vb) + suffix}</td></tr>`;
  }).join("");

  const teamCard = (p, side) => `<div class="card"><div class="teamhdr"><span class="dot" style="background:var(--${side})"></span>${esc(p.team)}</div>
    <div class="statgrid">
      ${stat("Avg PPDA", p.averages?.ppda ?? "-")}
      ${stat("Avg field tilt", p.averages?.field_tilt != null ? p.averages.field_tilt + "%" : "-")}
      ${stat("Hub", esc(p.most_common_hub || "-"))}
      ${stat("Style", esc(p.most_common_style || "-"))}
    </div>
    <h4>Takeaways</h4>
    <ul class="takeaways">${(p.takeaways || []).map((t) => `<li>${esc(t)}</li>`).join("") || "<li>Not enough data yet.</li>"}</ul>
  </div>`;

  return `<div class="card match-hero">
      <div class="eyebrow">Head-to-head &middot; ${a.matches_analyzed} vs ${b.matches_analyzed} matches analyzed</div>
      <div class="matchup">
        <div class="side home"><span class="dot" style="background:var(--home)"></span><span class="team-name">${esc(a.team)}</span></div>
        <div class="vs">vs</div>
        <div class="side away"><span class="team-name">${esc(b.team)}</span><span class="dot" style="background:var(--away)"></span></div>
      </div>
      <table><tr><th>Metric</th><th class="num">${esc(a.team)}</th><th class="num">${esc(b.team)}</th></tr>${h2hRows}</table>
    </div>
    <div class="cols">${teamCard(a, "home")}${teamCard(b, "away")}</div>`;
}

function renderPlayerProfile(profile) {
  const t = profile.totals || {}, a = profile.averages || {};
  const rows = (profile.trend || []).map((m) =>
    `<tr><td>${esc(m.match_date)}</td><td>${esc(m.opponent || "-")}</td>
      <td class="num">${m.accuracy == null ? "-" : m.accuracy + "%"}</td>
      <td class="num">${m.progressive_passes ?? "-"}</td>
      <td class="num">${m.xt_generated == null ? "-" : n2(m.xt_generated)}</td>
      <td class="num">${m.under_pressure_accuracy == null ? "-" : m.under_pressure_accuracy + "%"}</td></tr>`
  ).join("");
  const takeaways = (profile.takeaways || []).map((tk) => `<li>${esc(tk)}</li>`).join("");
  return `<div class="card match-hero">
      <div class="eyebrow">Player scout &middot; ${esc(profile.team || "-")} &middot; ${profile.matches_analyzed} match${profile.matches_analyzed === 1 ? "" : "es"} analyzed</div>
      <div class="matchup"><div class="side home"><span class="team-name">${esc(profile.nickname || profile.player)}</span></div></div>
      <div class="statgrid">
        ${stat("Overall accuracy", t.accuracy == null ? "-" : t.accuracy + "%")}
        ${stat("Avg accuracy/match", a.accuracy == null ? "-" : a.accuracy + "%")}
        ${stat("Total progressive", t.progressive_passes ?? "-")}
        ${stat("Avg under pressure", a.under_pressure_accuracy == null ? "-" : a.under_pressure_accuracy + "%")}
        ${stat("Total xT generated", t.xt_generated == null ? "-" : n2(t.xt_generated))}
        ${stat("Avg xT/match", a.xt_generated == null ? "-" : n2(a.xt_generated))}
      </div>
    </div>
    <div class="card"><h3>Scouting takeaways</h3><ul class="takeaways">${takeaways || '<li>Not enough data yet.</li>'}</ul></div>
    <div class="cols">
      <div class="card"><h4>Accuracy trend</h4>${svgTrendChart(profile.trend, "accuracy", { label: "Accuracy", suffix: "%" })}</div>
      <div class="card"><h4>xT generated trend</h4>${svgTrendChart(profile.trend, "xt_generated", { label: "xT generated" })}</div>
    </div>
    <div class="card"><h4>Match-by-match</h4>
      <table><tr><th>Match</th><th>Opponent</th><th class="num">Accuracy</th><th class="num">Progressive</th><th class="num">xT</th><th class="num">Under pressure</th></tr>${rows}</table>
    </div>`;
}

const STEP_FN = [null, renderLoad, renderNetwork, renderCentrality, renderTactical, renderStory, renderReport];
const STEPS = [
  { n: 1, label: "1 \u00b7 Load" },
  { n: 2, label: "2 \u00b7 Network" },
  { n: 3, label: "3 \u00b7 Centrality" },
  { n: 4, label: "4 \u00b7 Tactical" },
  { n: 5, label: "5 \u00b7 Match Story" },
  { n: 6, label: "6 \u00b7 Report" },
];

export default function App() {
  const cacheRef = useRef({});
  const [theme, setTheme] = useState(() => {
    try {
      const saved = localStorage.getItem("pns-theme");
      if (saved === "light" || saved === "dark") return saved;
    } catch { /* localStorage unavailable */ }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [allMatches, setAllMatches] = useState([]);
  const [matchDate, setMatchDate] = useState("");
  const [info, setInfo] = useState(null);
  const [teams, setTeams] = useState([]);
  const [step, setStep] = useState(1);
  const [stepsEnabled, setStepsEnabled] = useState(false);
  const [content, setContent] = useState('<div class="empty-state"><svg class="empty-icon" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" fill="var(--grass)" stroke="var(--accent)" stroke-width="1.6"/><line x1="4" y1="32" x2="60" y2="32" stroke="rgba(255,255,255,.4)" stroke-width="1"/><line x1="32" y1="4" x2="32" y2="60" stroke="rgba(255,255,255,.25)" stroke-width="1"/><circle cx="32" cy="32" r="11" fill="none" stroke="rgba(255,255,255,.4)" stroke-width="1"/><circle cx="32" cy="32" r="2" fill="var(--accent)"/></svg><h3>Pick a match to begin</h3><p>Choose a match from the dropdown above, or upload your own StatsBomb-format CSV or Excel file to run the full six-step analysis.</p></div>');
  const [uploadMsg, setUploadMsg] = useState("");
  const [uploadCls, setUploadCls] = useState("");
  const [csvName, setCsvName] = useState("");
  const fileInputRef = useRef(null);
  const contentRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("pns-theme", theme); } catch { /* localStorage unavailable */ }
  }, [theme]);

  // --- Opponent Scout mode: independent of the match-step pipeline above ---
  const [mode, setMode] = useState("match");
  const [allTeams, setAllTeams] = useState([]);
  const [opponentTeam, setOpponentTeam] = useState("");
  const [opponentContent, setOpponentContent] = useState('<p class="muted pad">Pick a team above to scout.</p>');

  const api = useCallback(async (cmd) => {
    const key = JSON.stringify(cmd);
    if (cacheRef.current[key]) return cacheRef.current[key];
    const r = await fetch("/api/predict", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: key,
    });
    const j = await r.json();
    cacheRef.current[key] = j;
    return j;
  }, []);

  useEffect(() => {
    if ((mode === "opponent" || mode === "compare") && allTeams.length === 0) {
      api({ command: "all_teams" }).then((d) => setAllTeams(d.teams || [])).catch(() => {});
    }
  }, [mode, allTeams.length, api]);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!opponentTeam) { setOpponentContent('<p class="muted pad">Pick a team above to scout.</p>'); return; }
      setOpponentContent('<p class="loading">Computing...</p>');
      try {
        const profile = await api({ command: "opponent_profile", team: opponentTeam });
        if (cancelled) return;
        if (profile.error) { setOpponentContent(`<p class="loading">Error: ${esc(profile.error)}</p>`); return; }
        setOpponentContent(renderOpponentProfile(profile));
      } catch (e) {
        if (!cancelled) setOpponentContent(`<p class="loading">Error: ${esc(e.message)}</p>`);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [opponentTeam, api]);

  // --- Compare mode: two opponent profiles fetched side by side ---
  const [compareTeamA, setCompareTeamA] = useState("");
  const [compareTeamB, setCompareTeamB] = useState("");
  const [compareContent, setCompareContent] = useState('<p class="muted pad">Pick two teams above to compare.</p>');

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!compareTeamA || !compareTeamB) { setCompareContent('<p class="muted pad">Pick two teams above to compare.</p>'); return; }
      if (compareTeamA === compareTeamB) { setCompareContent('<p class="loading">Pick two different teams.</p>'); return; }
      setCompareContent('<p class="loading">Computing...</p>');
      try {
        const [a, b] = await Promise.all([
          api({ command: "opponent_profile", team: compareTeamA }),
          api({ command: "opponent_profile", team: compareTeamB }),
        ]);
        if (cancelled) return;
        if (a.error || b.error) { setCompareContent(`<p class="loading">Error: ${esc(a.error || b.error)}</p>`); return; }
        setCompareContent(renderCompareTeams(a, b));
      } catch (e) {
        if (!cancelled) setCompareContent(`<p class="loading">Error: ${esc(e.message)}</p>`);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [compareTeamA, compareTeamB, api]);

  const populateMatches = useCallback(async (selectDate) => {
    delete cacheRef.current[JSON.stringify({ command: "matches" })]; // bust so uploads appear
    const d = await api({ command: "matches" });
    const ms = d.matches || [];
    setAllMatches(ms);
    if (selectDate) setMatchDate(selectDate);
    return ms;
  }, [api]);

  useEffect(() => { populateMatches(); }, [populateMatches]);

  const loadMatch = useCallback(async (date, matchInfo) => {
    setMatchDate(date);
    setInfo(matchInfo || null);
    if (!date) {
      setStepsEnabled(false);
      setTeams([]);
      setContent('<div class="empty-state"><svg class="empty-icon" width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" fill="var(--grass)" stroke="var(--accent)" stroke-width="1.6"/><line x1="4" y1="32" x2="60" y2="32" stroke="rgba(255,255,255,.4)" stroke-width="1"/><line x1="32" y1="4" x2="32" y2="60" stroke="rgba(255,255,255,.25)" stroke-width="1"/><circle cx="32" cy="32" r="11" fill="none" stroke="rgba(255,255,255,.4)" stroke-width="1"/><circle cx="32" cy="32" r="2" fill="var(--accent)"/></svg><h3>Pick a match to begin</h3><p>Choose a match from the dropdown above, or upload your own StatsBomb-format CSV or Excel file to run the full six-step analysis.</p></div>');
      return;
    }
    const t = await api({ command: "teams", match_date: date });
    setTeams(t.teams || []);
    setStepsEnabled(true);
    setStep(1);
  }, [api]);

  const onMatchChange = (e) => {
    const date = e.target.value;
    const m = allMatches.find((mm) => mm.date === date);
    loadMatch(date, m);
  };

  async function doUpload() {
    const f = fileInputRef.current?.files?.[0];
    if (!f) { setUploadMsg("Choose a CSV or Excel file first."); setUploadCls("err"); return; }
    const isXlsx = /\.xlsx?$/i.test(f.name);
    setUploadMsg("Uploading " + f.name + "..."); setUploadCls("");
    try {
      let body;
      if (isXlsx) {
        const buf = new Uint8Array(await f.arrayBuffer());
        let bin = "";
        for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
        body = { xlsx_b64: btoa(bin), filename: f.name };
      } else {
        const name = csvName.trim() || f.name.replace(/\.csv$/i, "");
        body = { match_name: name, csv_text: await f.text() };
      }
      const r = await fetch("/api/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json();
      if (j.error) { setUploadMsg("Upload failed: " + j.error); setUploadCls("err"); return; }
      const added = j.added || [];
      if (!added.length) { setUploadMsg("Nothing added."); setUploadCls("err"); return; }
      const ms = await populateMatches(added[0].match_date);
      setUploadMsg(`Added ${added.length} match${added.length === 1 ? "" : "es"}: ${added.map((a) => a.match_date).join(", ")}. Selected the first below.`);
      setUploadCls("ok");
      loadMatch(added[0].match_date, ms.find((m) => m.date === added[0].match_date));
    } catch (e) {
      setUploadMsg("Upload error: " + e.message); setUploadCls("err");
    }
  }

  // render current step's content whenever step/match/teams change
  useEffect(() => {
    let cancelled = false;
    async function render() {
      if (!matchDate) return;
      setContent('<p class="loading">Computing...</p>');
      const S = { match: matchDate, info, teams, allMatches };
      try {
        const fn = STEP_FN[step];
        const html = step === 1 ? fn(S) : await fn(S, api);
        if (!cancelled) setContent(html);
      } catch (e) {
        if (!cancelled) setContent(`<p class="loading">Error: ${esc(e.message)}</p>`);
      }
    }
    render();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, matchDate, teams]);

  // wire up the print button injected via dangerouslySetInnerHTML on step 6
  useEffect(() => {
    if (step !== 6 || !contentRef.current) return;
    const btn = contentRef.current.querySelector("#printBtn");
    if (btn) btn.onclick = () => window.print();
  }, [step, content]);

  return (
    <div className="shell">
      <header>
        <div className="header-row">
          <div className="brand">
            <svg className="crest" width="38" height="38" viewBox="0 0 38 38">
              <circle cx="19" cy="19" r="17" fill="var(--grass)" stroke="var(--accent)" strokeWidth="1.6" />
              <line x1="19" y1="3" x2="19" y2="35" stroke="rgba(255,255,255,.5)" strokeWidth="1" />
              <circle cx="19" cy="19" r="6" fill="none" stroke="rgba(255,255,255,.5)" strokeWidth="1" />
            </svg>
            <div>
              <h1> Opposition Passing Networks <span>Studio</span></h1>
              <p className="sub">Build and analyse a full passing network from real match data - network, centrality, tactical maps and the match story, end to end.</p>
            </div>
          </div>
          <button
            className="theme-toggle"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="4.5" />
                <line x1="12" y1="1.5" x2="12" y2="4" />
                <line x1="12" y1="20" x2="12" y2="22.5" />
                <line x1="4.2" y1="4.2" x2="5.9" y2="5.9" />
                <line x1="18.1" y1="18.1" x2="19.8" y2="19.8" />
                <line x1="1.5" y1="12" x2="4" y2="12" />
                <line x1="20" y1="12" x2="22.5" y2="12" />
                <line x1="4.2" y1="19.8" x2="5.9" y2="18.1" />
                <line x1="18.1" y1="5.9" x2="19.8" y2="4.2" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.4 14.7A8.5 8.5 0 0 1 9.3 3.6a.75.75 0 0 0-.9-1 10 10 0 1 0 12.9 12.9.75.75 0 0 0-1-.9z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <nav className="mode-tabs">
        <button className={mode === "match" ? "active" : ""} onClick={() => setMode("match")}>Match Analysis</button>
        <button className={mode === "opponent" ? "active" : ""} onClick={() => setMode("opponent")}>Opponent Scout</button>
        <button className={mode === "compare" ? "active" : ""} onClick={() => setMode("compare")}>Compare Teams</button>
      </nav>

      {mode === "match" && (
        <>
          <section className="bar">
            <label>
              Match
              <select value={matchDate} onChange={onMatchChange}>
                <option value="">{allMatches.length ? "Select a match..." : "Loading matches..."}</option>
                {allMatches.map((m) => (
                  <option key={m.date} value={m.date}>
                    {`${m.home_team} vs ${m.away_team} - ${m.competition} (${m.date_display})`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Add your own match(es)
              <span className="upload">
                <input type="file" ref={fileInputRef} accept=".csv,.xlsx" />
                <input type="text" placeholder="name (CSV only)" value={csvName} onChange={(e) => setCsvName(e.target.value)} />
                <button className="btn small" onClick={doUpload}>Upload</button>
              </span>
            </label>
            {teams.length > 0 && (
              <div className="legend">
                {teams.map((tm) => (
                  <span key={tm}>
                    <span className="dot" style={{ background: COL(teams, tm) }}></span>{tm}
                  </span>
                ))}
              </div>
            )}
          </section>
          <div className={"uploadmsg " + uploadCls}>{uploadMsg}</div>

          <nav className="steps">
            {STEPS.map((s) => (
              <button
                key={s.n}
                className={step === s.n ? "active" : ""}
                disabled={!stepsEnabled && s.n !== 1}
                onClick={() => setStep(s.n)}
              >
                {s.label}
              </button>
            ))}
          </nav>

          <main ref={contentRef} dangerouslySetInnerHTML={{ __html: content }} />
        </>
      )}

      {mode === "opponent" && (
        <>
          <section className="bar">
            <label>
              Opponent team
              <select value={opponentTeam} onChange={(e) => setOpponentTeam(e.target.value)}>
                <option value="">{allTeams.length ? "Select a team..." : "Loading teams..."}</option>
                {allTeams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
          </section>

          <main dangerouslySetInnerHTML={{ __html: opponentContent }} />
        </>
      )}

      {mode === "compare" && (
        <>
          <section className="bar">
            <label>
              Team A
              <select value={compareTeamA} onChange={(e) => setCompareTeamA(e.target.value)}>
                <option value="">{allTeams.length ? "Select a team..." : "Loading teams..."}</option>
                {allTeams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label>
              Team B
              <select value={compareTeamB} onChange={(e) => setCompareTeamB(e.target.value)}>
                <option value="">{allTeams.length ? "Select a team..." : "Loading teams..."}</option>
                {allTeams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
          </section>

          <main dangerouslySetInnerHTML={{ __html: compareContent }} />
        </>
      )}

      <footer>Reads real StatsBomb event data with xT pre-computed. All fourteen analysis modules run live in <code>predict_server.py</code>; this page is served by <code>api_server.py</code>.</footer>
    </div>
  );
}