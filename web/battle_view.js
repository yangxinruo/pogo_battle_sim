"use strict";
// 一场对战的显示（4g 起"打一场"页和九宫格页共用；在 common.js 之后、各页自己的脚本之前加载）：
// 卡片和表格的小工具、战斗过程图（SVG）、对位分段表、逐回合时间线。
//
// 只负责画：图和表的数据（招式带、逐回合的 HP 和能量、对位分段、时间线）都由服务器算好
// （pogo_sim/battle_summary.py、web_api 的 chart_payload、timeline_payload、segments_payload）。
// r 是服务器回的一场的结果：3v3 是 web_api.battle_payload，九宫格里的一场是 web_api.matchup_battle（每方一只）。
// 这里用到的是 r.teams（每方的 name、names、members）、r.chart、r.timeline，分段表另外用 r.segments。

const SIDES = [0, 1];

const battleView = {
  showDecisions: true, // 时间线里显示决定和原因
  chart: null, // 最近画的过程图 {r, opts, holder}：窗口宽度变了时按新的宽度重画
};

// ---- 卡片和表格 ----

function card(title, ...content) {
  return el("div", {class: "card"}, el("h2", {}, title), ...content);
}

/** 表格。rows 的每一行是格子的数组，或者 {attrs, cells}（给这一行加 id、事件等）。 */
function table(header, rows, attrs = {}) {
  const cell = (c) => (c instanceof Node && c.tagName === "TD" ? c : el("td", {}, c));
  const row = (r) => (Array.isArray(r) ? el("tr", {}, r.map(cell)) : el("tr", r.attrs, r.cells.map(cell)));
  return el("div", {class: "table-wrap"}, el("table", attrs,
    el("thead", {}, el("tr", {}, header.map((h) => (h instanceof Node ? h : el("th", {}, h))))),
    el("tbody", {}, rows.map(row))));
}

function hpBar(hp, max) {
  const fraction = max > 0 ? hp / max : 0;
  const level = fraction > 0.5 ? "high" : fraction > 0.25 ? "mid" : "low";
  return el("span", {class: "hp"},
    el("span", {class: "bar"}, el("span", {class: `fill ${level}`, style: `width: ${Math.round(fraction * 100)}%; display: block;`})),
    `${hp} / ${max}`);
}

function nameOf(result, side, slot) {
  return el("span", {class: `name side-${side}`}, result.teams[side].names[slot]);
}

// ---- 时间线 ----

/** 时间线（带"显示决定和原因"的开关）。opts.highlight：要标出来的回合（Set），例如搜索应对改了决定的回合。 */
function timelineView(r, opts = {}) {
  const holder = el("div", {id: "timeline-table"});
  const controls = el("div", {class: "timeline-controls"},
    el("label", {}, el("input", {
      type: "checkbox",
      checked: battleView.showDecisions,
      onchange: (e) => {
        battleView.showDecisions = e.target.checked;
        holder.replaceChildren(timelineTable(r, opts));
      },
    }), " 显示决定和原因"),
    el("span", {class: "muted"}, "　每回合一行（没有事件的回合不列）；最后一列是回合结束时双方在场那只的 HP、能量和全队剩下的盾。"),
  );
  holder.replaceChildren(timelineTable(r, opts));
  return [controls, holder];
}

function eventClass(event) {
  if (event.type === "move") return event.data.is_charged ? "ev charged" : "ev fast";
  return `ev ${event.type}`;
}

function sideState(r, side, snapshot) {
  const team = r.teams[side];
  const active = snapshot.active;
  return el("div", {class: "state-line"},
    nameOf(r, side, active), " ",
    hpBar(snapshot.hp, team.members[active].hp),
    ` · 能量 ${snapshot.energy} · 盾 ${snapshot.shields}`);
}

function timelineTable(r, opts = {}) {
  const highlight = opts.highlight ?? new Set();
  const rows = [];
  for (const entry of r.timeline) {
    const events = entry.events.filter((e) => battleView.showDecisions || e.type !== "decision");
    if (events.length === 0) continue;
    const cells = SIDES.map((side) => el("td", {class: `events-${side}`},
      events.filter((e) => e.side === side).map((e) => el("div", {class: eventClass(e)},
        el("span", {class: "who"}, r.teams[side].names[e.slot]), " ", e.text))));
    rows.push({attrs: {id: `turn-${entry.turn}`, class: highlight.has(entry.turn) ? "turn-marked" : undefined}, cells: [
      el("td", {class: "turn"}, `T${entry.turn}`),
      ...cells,
      entry.sides ? el("td", {}, SIDES.map((side) => sideState(r, side, entry.sides[side]))) : el("td", {}, ""),
    ]});
  }
  return table(["回合", r.teams[0].name, r.teams[1].name, "回合结束时"], rows, {class: "timeline"});
}

/** 跳到时间线里这一回合的那一行；没有那一行（没有事件）就跳到前面最近的一行。 */
function jumpToTurn(turn) {
  for (let t = turn; t >= 1; t -= 1) {
    const row = document.getElementById(`turn-${t}`);
    if (!row) continue;
    row.scrollIntoView({behavior: "smooth", block: "center"});
    row.classList.add("flash");
    setTimeout(() => row.classList.remove("flash"), 1500);
    return;
  }
}

// ---- 战斗过程图（4b） ----
//
// 上面两条是双方的招式带，下面两条是双方的 HP，共用一根横轴（回合）。

const SVG_NS = "http://www.w3.org/2000/svg";
const MEMBER_COLORS = [["#2563eb", "#0891b2", "#7c3aed"], ["#ea580c", "#ca8a04", "#db2777"]];
// 招式带从上到下：两行文字标签（大招、换人），快招小块，倒下标记
const CHART = {left: 110, right: 16, top: 8, laneHeight: 58, hpHeight: 92, gap: 10, minTurnWidth: 5};

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function memberColor(side, slot) {
  return MEMBER_COLORS[side][slot % MEMBER_COLORS[side].length];
}

/** 对战时间（毫秒）写成"分:秒"，例如 1:05.5。 */
function clock(ms) {
  const seconds = ms / 1000;
  const rest = seconds % 60;
  const text = Number.isInteger(rest) ? String(rest).padStart(2, "0") : rest.toFixed(1).padStart(4, "0");
  return `${Math.floor(seconds / 60)}:${text}`;
}

function chartLayout(turns, width) {
  const {left, right, top, laneHeight, hpHeight, gap, minTurnWidth} = CHART;
  const plotWidth = Math.max(width - left - right, turns * minTurnWidth);
  const laneY = [top, top + laneHeight + gap];
  const hpY = [laneY[1] + laneHeight + gap * 2, laneY[1] + laneHeight + gap * 3 + hpHeight];
  const axisY = hpY[1] + hpHeight + 4;
  return {
    turns, plotWidth, laneY, hpY, axisY,
    width: left + plotWidth + right,
    height: axisY + 34,
    // 第 t 回合占横轴上 [x(t - 1), x(t)] 这一格
    x: (t) => left + (t / turns) * plotWidth,
  };
}

/** 过程图（图例、说明、图）。opts.marks：图上另外标的回合 [{turn, label}]，画成绿色虚线；
 *  opts.note：说明后面加的一句（解释这些标记）；opts.sideLabels：图左边每方的名字（默认是队名，
 *  九宫格里的一场队名是宝可梦的名字，太长，改用"测试对象""对手"）。 */
function chartView(r, opts = {}) {
  const legend = el("div", {class: "chart-legend"},
    SIDES.map((side) => el("span", {class: "legend-team"},
      el("span", {class: `name side-${side}`}, r.teams[side].name), "：",
      r.teams[side].names.map((name, slot) => el("span", {class: "legend-item"},
        el("span", {class: "swatch", style: `background: ${memberColor(side, slot)}`}), name)))),
  );
  const help = el("p", {class: "muted"},
    "招式带：小块是快招（宽度是招式的回合数），竖条是大招（空心是被开盾挡下，旁边写伤害），紫线是换人，✕ 是倒下。" +
    "HP：粗线是在场那只，细的淡线是后备，虚线是在场那只的能量（0–100）。鼠标移上去看这一回合的详情，点一下跳到下面时间线的那一行。" +
    (opts.note ?? ""));
  const holder = el("div", {class: "chart-holder", id: "chart-holder"});
  // 先放进页面再画：要知道可用的宽度
  requestAnimationFrame(() => drawChart(r, holder, opts));
  return [legend, help, holder];
}

function drawChart(r, holder, opts = {}) {
  battleView.chart = {r, opts, holder};
  const chart = r.chart;
  const layout = chartLayout(chart.turns, holder.clientWidth || 1000);
  const {x, laneY, hpY, axisY} = layout;
  const {laneHeight, hpHeight, left} = CHART;
  const parts = [];

  // 背景和左边的标签
  for (const side of SIDES) {
    const team = opts.sideLabels?.[side] ?? r.teams[side].name;
    parts.push(
      svg("rect", {x: left, y: laneY[side], width: layout.plotWidth, height: laneHeight, class: `lane-bg lane-${side}`}),
      svg("text", {x: left - 8, y: laneY[side] + laneHeight / 2 + 4, class: `axis-label side-${side}`, "text-anchor": "end"}, `${team} 招式`),
      svg("rect", {x: left, y: hpY[side], width: layout.plotWidth, height: hpHeight, class: "hp-bg"}),
      svg("text", {x: left - 8, y: hpY[side] + hpHeight / 2 + 4, class: `axis-label side-${side}`, "text-anchor": "end"}, `${team} HP`),
      svg("text", {x: left - 8, y: hpY[side] + 10, class: "axis-small", "text-anchor": "end"}, "100%"),
      svg("text", {x: left - 8, y: hpY[side] + hpHeight, class: "axis-small", "text-anchor": "end"}, "0"),
    );
  }

  // 横轴：每 10 回合（长的对战每 20 回合）一条线，下面写回合数和对战时间
  const step = chart.turns > 200 ? 20 : 10;
  for (let t = 0; t <= chart.turns; t += step) {
    parts.push(
      svg("line", {x1: x(t), x2: x(t), y1: laneY[0], y2: axisY, class: "grid"}),
      svg("text", {x: x(t), y: axisY + 12, class: "axis-small", "text-anchor": "middle"}, `T${t}`),
      svg("text", {x: x(t), y: axisY + 25, class: "axis-small", "text-anchor": "middle"}, clock(chart.elapsed_ms[t])),
    );
  }

  // 对位分段的高亮（鼠标移到分段表的某一行时显示）
  const band = svg("rect", {id: "segment-band", class: "segment-band", y: laneY[0], height: axisY - laneY[0], visibility: "hidden"});
  parts.push(band);

  for (const side of SIDES) {
    parts.push(...laneShapes(r, side, layout), ...hpShapes(r, side, layout));
  }

  // 另外标的回合（打一场页：搜索应对改了的决定）：绿色虚线，上面写标签
  for (const mark of opts.marks ?? []) {
    const xm = (x(mark.turn - 1) + x(mark.turn)) / 2;
    parts.push(
      svg("line", {x1: xm, x2: xm, y1: laneY[0], y2: axisY, class: "chart-mark"}),
      svg("text", {x: xm + 2, y: axisY - 3, class: "chart-mark-label"}, mark.label),
    );
  }

  // 鼠标所在的那一回合
  const column = svg("rect", {class: "hover-column", y: laneY[0], height: axisY - laneY[0], visibility: "hidden"});
  parts.push(column);
  const node = svg("svg", {width: layout.width, height: layout.height, class: "chart"}, parts);
  const tooltip = el("div", {class: "chart-tooltip", hidden: true});
  const overlay = svg("rect", {x: left, y: 0, width: layout.plotWidth, height: axisY, fill: "transparent", class: "chart-overlay"});
  const turnAt = (event) => {
    const box = node.getBoundingClientRect();
    const t = Math.ceil(((event.clientX - box.left - left) / layout.plotWidth) * chart.turns);
    return Math.min(chart.turns, Math.max(1, t));
  };
  overlay.addEventListener("mousemove", (event) => {
    const t = turnAt(event);
    column.setAttribute("x", x(t - 1));
    column.setAttribute("width", Math.max(2, x(t) - x(t - 1)));
    column.setAttribute("visibility", "visible");
    tooltip.replaceChildren(...turnDetails(r, t));
    tooltip.hidden = false;
    const flip = event.clientX > window.innerWidth - 460;
    tooltip.style.left = `${flip ? event.clientX - 452 : event.clientX + 16}px`;
    tooltip.style.top = `${Math.min(event.clientY + 16, window.innerHeight - tooltip.offsetHeight - 8)}px`;
  });
  overlay.addEventListener("mouseleave", () => {
    column.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  });
  overlay.addEventListener("click", (event) => jumpToTurn(turnAt(event)));
  node.append(overlay);
  holder.replaceChildren(node, tooltip);
}

/** 一方的招式带：快招小块、大招竖条、换人线、倒下标记。 */
function laneShapes(r, side, layout) {
  const {x, laneY, hpY} = layout;
  const y = laneY[side];
  const {laneHeight, hpHeight} = CHART;
  const names = r.chart.move_names;
  const shapes = [];
  // 文字标签放两行：这一行的上一个标签还没结束，就放到另一行（按时间顺序画，所以只要记每行写到哪里）
  const rowEnds = [-Infinity, -Infinity];
  const textWidth = (text) => [...text].reduce((width, ch) => width + (ch.charCodeAt(0) > 255 ? 10 : 6), 0);
  const label = (x0, text, attrs) => {
    x0 = Math.min(x0, layout.width - 2 - textWidth(text));  // 靠右边的标签往左挪，不被切掉
    let row = rowEnds.findIndex((end) => x0 >= end + 4);
    if (row < 0) row = rowEnds[0] <= rowEnds[1] ? 0 : 1;
    rowEnds[row] = x0 + textWidth(text);
    return svg("text", {x: x0, y: y + 12 + row * 12, ...attrs}, text);
  };
  for (const item of r.chart.sides[side].lane) {
    const color = memberColor(side, item.slot);
    const x0 = x(item.start_turn - 1);
    const x1 = x(item.end_turn);
    const middle = (x(item.start_turn - 1) + x(item.start_turn)) / 2;
    switch (item.kind) {
      case "fast":
        shapes.push(svg("rect", {x: x0 + 0.5, y: y + 32, width: Math.max(1, x1 - x0 - 1), height: 12, fill: color, rx: 1}));
        break;
      case "cancelled":
        shapes.push(svg("rect", {x: x0 + 0.5, y: y + 32, width: Math.max(1, x1 - x0 - 1), height: 12, class: "cancelled", stroke: color}));
        break;
      case "charged":
        shapes.push(
          svg("rect", {x: middle - 3, y: y + 3, width: 6, height: laneHeight - 6, rx: 1,
            fill: item.shielded ? "#fff" : color, stroke: color, "stroke-width": 2}),
          label(middle + 5, `${names[item.move_id] ?? item.move_id} ${item.shielded ? "挡下" : item.damage}`,
            {class: "charged-label", fill: color}),
        );
        break;
      case "switch":
        shapes.push(
          svg("line", {x1: x0, x2: x0, y1: y, y2: y + laneHeight, class: "switch-line"}),
          svg("line", {x1: x0, x2: x0, y1: hpY[side], y2: hpY[side] + hpHeight, class: "switch-line"}),
          label(x0 + 3, `→ ${r.teams[side].names[item.slot]}`, {class: "switch-label"}),
        );
        break;
      case "faint":
        shapes.push(
          svg("text", {x: middle, y: y + 56, class: "faint-mark", "text-anchor": "middle"}, "✕"),
          svg("text", {x: middle, y: hpY[side] + hpHeight - 2, class: "faint-mark", "text-anchor": "middle"}, "✕"),
        );
        break;
    }
  }
  return shapes;
}

/** 一方每只的 HP（在场时粗线、后备时细淡线）和在场时的能量（虚线），画成阶梯：第 t 回合末的值从 x(t) 起生效。 */
function hpShapes(r, side, layout) {
  const {x, hpY, turns} = layout;
  const {hpHeight} = CHART;
  const data = r.chart.sides[side];
  const shapes = [];
  const yOf = (fraction) => hpY[side] + hpHeight - 2 - fraction * (hpHeight - 6);
  data.hp.forEach((series, slot) => {
    const max = data.max_hp[slot];
    let active = "";
    let bench = "";
    let energy = "";
    for (let t = 1; t <= turns; t += 1) {
      const piece = `M${x(t - 1)},${yOf(series[t - 1] / max)}H${x(t)}V${yOf(series[t] / max)}`;
      if (data.active[t] === slot) {
        active += piece;
        const e = data.energy[slot];
        energy += `M${x(t - 1)},${yOf(e[t - 1] / 100)}H${x(t)}V${yOf(e[t] / 100)}`;
      } else {
        bench += piece;
      }
    }
    const color = memberColor(side, slot);
    if (bench) shapes.push(svg("path", {d: bench, stroke: color, class: "hp-bench"}));
    if (energy) shapes.push(svg("path", {d: energy, stroke: color, class: "energy-line"}));
    if (active) shapes.push(svg("path", {d: active, stroke: color, class: "hp-active"}));
  });
  return shapes;
}

/** 鼠标所在那一回合的详情：对战时间、这一回合的事件（含决定和原因）、回合结束时双方的状态。 */
function turnDetails(r, turn) {
  const entry = r.timeline.find((e) => e.turn === turn);
  const lines = [el("div", {class: "tip-title"}, `T${turn} · 对战时间 ${clock(r.chart.elapsed_ms[turn])}`)];
  if (entry) {
    for (const event of entry.events) {
      lines.push(el("div", {class: eventClass(event)},
        el("span", {class: `who name side-${event.side}`}, r.teams[event.side].names[event.slot]), " ", event.text));
    }
    if (entry.sides) lines.push(el("div", {class: "tip-state"}, SIDES.map((side) => sideState(r, side, entry.sides[side]))));
  }
  if (!entry || entry.events.length === 0) lines.splice(1, 0, el("div", {class: "muted"}, "这一回合没有结算的事件（快招还在进行）"));
  return lines;
}

// 窗口宽度变了：按新的宽度重画最近画的过程图（还在页面上的话）
let chartResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(chartResizeTimer);
  chartResizeTimer = setTimeout(() => {
    const last = battleView.chart;
    if (last && last.holder.isConnected) drawChart(last.r, last.holder, last.opts);
  }, 200);
});

// ---- 对位分段（4b，只有 3v3 用） ----

function segmentsView(r) {
  const help = el("p", {class: "muted"},
    "在场的两只不变的一段时间算一段，任一方换人就开始新的一段。HP 和能量是这一段开始之前 → 最后一回合结束时；" +
    "大招后面是伤害，“挡下”是被对方开盾挡下；开盾是挡下对方大招的次数。鼠标移到一行上，图上会标出这一段。");
  const rows = r.segments.map((segment) => ({
    attrs: {
      class: "segment-row",
      onmouseenter: () => showSegmentBand(r, segment),
      onmouseleave: () => document.getElementById("segment-band")?.setAttribute("visibility", "hidden"),
    },
    cells: [
      el("td", {class: "num"}, segment.start_turn === segment.end_turn ? `${segment.start_turn}` : `${segment.start_turn}–${segment.end_turn}`),
      ...SIDES.map((side) => el("td", {class: "text"}, segmentSideCell(r, segment, side))),
      el("td", {class: "text"}, segment.end_text),
    ],
  }));
  return [help, table(["回合", r.teams[0].name, r.teams[1].name, "怎么结束"], rows)];
}

function segmentSideCell(r, segment, side) {
  const s = segment.sides[side];
  const max = r.chart.sides[side].max_hp[s.slot];
  const details = [`快招 ${s.fast_moves} 次`];
  if (s.charged.length) details.push(`大招 ${segment.charged_text[side]}`);
  if (s.shields_used) details.push(`开盾 ${s.shields_used} 次`);
  return [
    el("div", {},
      el("span", {class: "who", style: `color: ${memberColor(side, s.slot)}`}, r.teams[side].names[s.slot]),
      ` HP ${s.hp_start} → ${s.hp_end}（最大 ${max}）· 能量 ${s.energy_start} → ${s.energy_end}`),
    el("div", {class: "muted"}, details.join(" · ")),
  ];
}

function showSegmentBand(r, segment) {
  const band = document.getElementById("segment-band");
  if (!band) return;
  const holder = document.getElementById("chart-holder");
  const layout = chartLayout(r.chart.turns, holder.clientWidth || 1000);
  band.setAttribute("x", layout.x(segment.start_turn - 1));
  band.setAttribute("width", Math.max(2, layout.x(segment.end_turn) - layout.x(segment.start_turn - 1)));
  band.setAttribute("visibility", "visible");
}
