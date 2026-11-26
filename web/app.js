"use strict";
// "打一场 3v3"页（第 4 步，4a 起）：选队伍、打一场 3v3、看结果和逐回合时间线；手动对战、搜索应对、队伍库。
//
// 这里只负责填表和显示，不算任何东西：建配置、检查、对战、统计都在 Python 引擎里，
// 通过 tools/run_web.py 的接口拿结果（每个接口返回什么见 pogo_sim/web_api.py）。
// 页面上的配置和 3v3 配置文件（pogo_sim/team_battle.py 开头）写法一样；浏览器会记住上次填的（localStorage）。
// 和九宫格页共用的部分：一只宝可梦的编辑器在 editor.js，过程图、时间线等一场对战的显示在 battle_view.js。

const STORAGE_KEY = "pogo_sim.team_battle.config.v1";

const state = {
  options: null, // GET /api/options：下拉选项和例子配置
  config: null, // 页面上的配置（normalizeConfig）；发给服务器前用 requestConfig 整理
  result: null, // POST /api/team-battle 的结果（手动对战打完以后是那一场的结果；搜索应对时是正在看的那一场）
  bestResponse: null, // POST /api/best-response 的结果（4e）；打一场、手动对战打完时清掉
  library: null, // GET /api/team-library 的结果（4f）；打开队伍库时重新读
  libraryOpen: null, // 哪一队下面打开了"从队伍库载入"（0 / 1 / null）
  libraryFilter: {sameLeague: true, query: ""},
  manual: null, // 手动对战：{config, side, decisions, data（服务器最近一次的回答）, seenEvents, pending}
};

// ---- 小工具（其余在 common.js） ----

/** 建配置用的设置（editor.js 的 settings）。 */
function buildSettings() {
  return {league: state.config.league, season: state.config.season, custom_files: state.config.custom_files};
}

// ---- 配置 ----

/** 把例子配置或浏览器记住的配置整理成页面用的样子（缺的字段补上默认值）。 */
function normalizeConfig(raw) {
  const options = state.options;
  return {
    league: raw.league ?? 1500,
    season: raw.season ?? options.seasons[0].key,
    custom_files: (raw.custom_files ?? []).filter((name) => options.custom_files.some((f) => f.name === name)),
    team: SIDES.map((side) => normalizeSide(raw.team?.[side] ?? {}, side)),
  };
}

/** 第 side 方的一队（editor.js 的 normalizeTeam）：没写队名时叫 Team A / Team B。 */
function normalizeSide(team, side) {
  const options = state.options;
  return normalizeTeam(team, {
    name: side === 0 ? "Team A" : "Team B",
    size: options.team_size,
    shields: options.max_shields,
    switching: options.switching[0].key,
  });
}

/** 打一场时发给服务器的配置：同 3v3 配置文件。 */
function requestConfig() {
  const config = state.config;
  return {
    league: config.league,
    season: config.season,
    custom_files: config.custom_files,
    team: config.team.map(teamRequest),
  };
}

function save() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.config));
}

function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

/** 队伍对队伍页点了"在打一场页打开"：那一场的两队存在 PAIRING_KEY（common.js）里。问过再换掉现在填的；
 *  不论换不换都删掉这个键（只问一次）。返回要载入的配置，不载入时为 null。 */
function takePairing() {
  let pairing = null;
  try {
    pairing = JSON.parse(localStorage.getItem(PAIRING_KEY));
  } catch {
    // 读不了就当没有
  }
  localStorage.removeItem(PAIRING_KEY);
  if (!pairing?.config) return null;
  const warnings = pairing.warnings?.length ? `\n\n注意：\n- ${pairing.warnings.join("\n- ")}` : "";
  if (!confirm(`载入队伍对队伍页里的一场（${pairing.title}）？现在填的设置和两队会被换掉。${warnings}`)) return null;
  return pairing;
}

/** 配置改了：记住，并标出下面的结果是改之前的。 */
function configChanged() {
  save();
  const note = document.getElementById("stale-note");
  if (note) note.hidden = false;
}

// ---- 设置 ----

function renderSettings() {
  const {options, config} = state;
  document.getElementById("league").replaceWith(select(
    options.leagues.map((l) => [l.cp, `${l.name}（${l.cp === 10000 ? "不限 CP" : `CP ${l.cp}`}）`]),
    config.league,
    async (value) => {
      config.league = Number(value);
      configChanged();
      await reloadCatalog(); // 推荐配招和排名跟联盟走
      renderTeams();
      rebuildMembers();
    },
    {id: "league"},
  ));
  document.getElementById("season").replaceWith(select(
    options.seasons.map((s) => [s.key, s.name]),
    config.season,
    (value) => {
      config.season = value;
      configChanged();
      rebuildMembers();
    },
    {id: "season"},
  ));

  const files = options.custom_files.map((file) => el("label", {},
    el("input", {
      type: "checkbox",
      checked: config.custom_files.includes(file.name),
      onchange: async (e) => {
        config.custom_files = options.custom_files
          .map((f) => f.name)
          .filter((name) => (name === file.name ? e.target.checked : config.custom_files.includes(name)));
        configChanged();
        await reloadCatalog();
        renderTeams();
        rebuildMembers();
      },
    }),
    ` 覆盖文件 ${file.name}`,
    file.description ? el("span", {class: "muted"}, `：${file.description}`) : null,
  ));
  document.getElementById("custom-files").replaceChildren(...files);
}

async function reloadCatalog() {
  await loadCatalog(state.config.league, state.config.custom_files);
}

// ---- 两队 ----

function renderTeams() {
  renderSideSelects();
  document.getElementById("teams").replaceChildren(...SIDES.map(renderTeam));
}

function renderTeam(side) {
  return teamEditor(state.config.team[side], {
    prefix: side,
    class: `side-${side}`,
    maxShields: state.options.max_shields,
    switching: state.options.switching,
    settings: buildSettings,
    onChange: configChanged,
    onNameChange: renderSideSelects,
    nameTitle: "队名（两队不能同名）",
    tools: el("span", {class: "library-buttons"},
      el("button", {onclick: () => saveLibraryTeam(side), title: "存进仓库的 teams/（一队一个文件，文件名按队名）"}, "存进队伍库"),
      el("button", {onclick: () => toggleLibrary(side)}, state.libraryOpen === side ? "收起队伍库" : "从队伍库载入"),
    ),
    panel: state.libraryOpen === side ? el("div", {class: "library", id: `library-${side}`}, libraryContent(side)) : null,
  });
}

// ---- 打一场 ----

async function runBattle() {
  const button = document.getElementById("run");
  button.disabled = true;
  showError("");
  setStatus("正在打……");
  try {
    state.result = await api("/api/team-battle", requestConfig());
    state.bestResponse = null;
    renderResult();
    setStatus(`打完了：${state.result.result.turns} 回合`);
    document.getElementById("result").scrollIntoView({behavior: "smooth"});
  } catch (e) {
    showError(e.message);
    setStatus("");
  } finally {
    button.disabled = false;
  }
}

function resetToExample() {
  if (!confirm("恢复成例子队伍？现在填的两队会被覆盖。")) return;
  state.config = normalizeConfig(state.options.example);
  save();
  start().catch((e) => showError(e.message));
}

// ---- 结果 ----

function renderResult() {
  const r = state.result;
  const section = document.getElementById("result");
  section.hidden = false;
  section.replaceChildren(
    ...(state.bestResponse ? [bestResponseCard(state.bestResponse)] : []),
    el("div", {class: "card"},
      el("div", {class: "result-head"},
        el("h2", {}, "结果"),
        el("button", {onclick: downloadReport}, "下载 Markdown 报告"),
      ),
      el("p", {class: "stale", id: "stale-note", hidden: true}, "配置改过了：下面还是上一次的结果，再点一次“打一场”或“搜索”更新。"),
      el("p", {class: "outcome"}, r.outcome),
      el("p", {class: "muted"}, `${r.settings.league_name}；赛季规则：${r.settings.season}`),
      r.settings.custom_log.map((line) => el("p", {class: "muted"}, `覆盖文件：${line}`)),
      r.teams.map((team, side) => el("div", {class: `team-line side-${side}`},
        el("span", {class: "name"}, `${team.name}（${team.shields} 盾，${team.policy}）：`),
        team.members.map((m, slot) => `${slot ? "；" : ""}${team.names[slot]} CP ${m.cp} ${m.level} 级 IV ${m.ivs.join("/")}`),
      )),
    ),
    ...battleCards(r, {
      chart: {
        marks: changes(r).map((change, i) => ({turn: change.turn, label: `改${i + 1}`})),
        note: changes(r).length ? "绿色虚线是搜索应对改了的决定（改1、改2……，同上面的表）。" : "",
      },
      timeline: {highlight: changedTurns(r)},
    }),
  );
}

function downloadReport() {
  const r = state.result;
  const safe = (text) => text.replace(/[^\w一-鿿-]+/g, "_");
  const searched = state.bestResponse && r === state.bestResponse.result;
  const name = `${searched ? "best_response" : "3v3"}_${safe(r.teams[0].name)}_vs_${safe(r.teams[1].name)}.md`;
  downloadText(name, r.report_markdown, "text/markdown");
}

// ---- 手动对战（4c） ----
//
// 自己操作一队，和另一队的 TeamPolicy 打（回合制：每个要你决定的地方停下来等你点）。
// 你到现在做的每个决定存在 state.manual.decisions 里；每点一次，就把整串决定发给服务器（/api/manual-battle），
// 服务器从第 1 回合重打到下一个要你决定的地方，返回局面、能选什么和伤害表（pogo_sim/manual.py、web_api.manual_battle）。
// 所以"撤销上一步"就是去掉最后一个决定。这里只负责显示和把你点的选项发回去。

const MANUAL_KEY = "pogo_sim.manual.v1";

/** "手动对战：我操作哪一队"和"搜索应对：搜哪一队"的下拉框，选项是两队的队名。 */
function renderSideSelects() {
  if (!state.config) return;
  for (const id of ["manual-side", "br-side"]) {
    const select = document.getElementById(id);
    if (!select) continue;
    const current = select.value || "0";
    select.replaceChildren(...SIDES.map((side) => el("option", {value: String(side)}, state.config.team[side].name || `第 ${side} 方`)));
    select.value = current;
  }
}

/** 记住进行中的手动对战（配置、哪一方、到现在的决定），刷新页面以后可以接着打。 */
function saveManual() {
  if (state.manual) {
    const {config, side, decisions} = state.manual;
    localStorage.setItem(MANUAL_KEY, JSON.stringify({config, side, decisions}));
  }
  updateResumeButton();
}

function updateResumeButton() {
  document.getElementById("manual-resume").hidden = Boolean(state.manual) || !localStorage.getItem(MANUAL_KEY);
}

function startManual() {
  const side = Number(document.getElementById("manual-side").value);
  state.manual = {config: requestConfig(), side, decisions: [], data: null, seenEvents: 0, pending: false};
  saveManual();
  document.getElementById("result").hidden = true;
  stepManual();
}

function resumeManual() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(MANUAL_KEY) ?? "null");
  } catch {
    saved = null;
  }
  if (!saved?.config || !Array.isArray(saved.decisions)) { // 没有保存的进度（或者坏了）
    localStorage.removeItem(MANUAL_KEY);
    updateResumeButton();
    return;
  }
  state.manual = {...saved, data: null, seenEvents: Infinity, pending: false}; // 接着打：已有的事件不再播放动画
  document.getElementById("result").hidden = true;
  stepManual();
}

function quitManual() {
  state.manual = null;
  localStorage.removeItem(MANUAL_KEY);
  updateResumeButton();
  document.getElementById("arena").hidden = true;
}

/** 做一个决定（decision 为 undefined 时只是按现有的决定重打一遍），请服务器重打到下一个要你决定的地方。 */
async function stepManual(decision) {
  const manual = state.manual;
  if (!manual || manual.pending) return;
  if (decision) manual.decisions.push(decision);
  manual.pending = true;
  showError("");
  try {
    const data = await api("/api/manual-battle", {config: manual.config, side: manual.side, decisions: manual.decisions});
    const before = manual.seenEvents; // 这之后的事件是刚才发生的（高亮、播放动画）
    manual.data = data;
    saveManual();
    renderArena(before);
    if (data.status === "finished") {
      state.result = data.result;
      state.bestResponse = null;
      renderResult();
    }
  } catch (e) {
    if (decision) manual.decisions.pop();
    showError(e.message);
  } finally {
    manual.pending = false;
  }
}

function undoManual() {
  const manual = state.manual;
  if (!manual || manual.pending || manual.decisions.length === 0) return;
  manual.decisions.pop();
  manual.seenEvents = Infinity; // 撤销以后不播放动画
  document.getElementById("result").hidden = true;
  stepManual();
}

function restartManual() {
  if (!state.manual || !confirm("从头再打一次？现在这一场的决定会全部清掉。")) return;
  state.manual.decisions = [];
  state.manual.data = null;
  state.manual.seenEvents = 0;
  document.getElementById("result").hidden = true;
  stepManual();
}

/** 把一个选项（服务器给的，带 label）变成发回去的决定。 */
function decisionFrom(option, charge = 1) {
  const {kind, action, move_id, to, shield} = option;
  return {kind, action, move_id, charge, to, shield};
}

// ---- 对战区 ----

function renderArena(seenBefore) {
  const manual = state.manual;
  const data = manual.data;
  const arena = document.getElementById("arena");
  arena.hidden = false;
  const me = manual.side;
  const them = 1 - me;
  const header = el("div", {class: "arena-head"},
    el("h2", {}, `手动对战：你操作 ${manual.config.team[me].name}，对手是 ${manual.config.team[them].name}（TeamPolicy）`),
    el("div", {class: "arena-buttons"},
      el("button", {onclick: undoManual, disabled: manual.decisions.length === 0}, "撤销上一步"),
      el("button", {onclick: restartManual}, "从头再打"),
      el("button", {onclick: quitManual}, "结束手动对战"),
    ),
  );
  if (data.status === "finished") {
    const r = data.result;
    arena.replaceChildren(header, el("div", {class: "card"},
      el("p", {class: "outcome"}, r.outcome),
      el("p", {class: "muted"}, `你一共做了 ${data.decisions} 个决定。下面是这一场的完整结果：过程图、对位分段，以及对方每个决定的原因。`),
    ));
    return;
  }
  const newEvents = data.events.slice(seenBefore);
  manual.seenEvents = data.events.length;
  arena.replaceChildren(
    header,
    el("p", {class: "muted"},
      `第 ${data.turn} 回合 · 对战时间 ${clock(data.elapsed_ms)} · 第 ${data.question.index + 1} 个决定。` +
      "队伍用的是开始手动对战时填的配置；对方的打算（决定和原因）打完以后才能看。"),
    el("div", {class: "field"},
      renderSideState(data, me, "你"),
      renderSideState(data, them, "对方"),
    ),
    renderQuestion(data),
    renderLog(data, newEvents),
  );
  animateEvents(newEvents, data);
}

function typeColor(types, i) {
  return TYPE_COLORS[types[Math.min(i, types.length - 1)]] ?? "#9ca3af";
}

function energyBar(member) {
  const ticks = member.charged.map((c) => el("span", {class: "tick", style: `left: ${c.energy}%`, title: `${c.name} ${c.energy}`}));
  return el("span", {class: "energy-bar"},
    el("span", {class: "energy-fill", style: `width: ${member.energy}%`}), ticks);
}

function chargedStatus(member) {
  return member.charged.map((c) => el("span", {class: `move-status ${c.ready ? "ready" : ""}`},
    `${c.name} ${c.energy}：`,
    c.ready ? "够了" : c.fast_needed === null ? "不够" : `还差 ${c.fast_needed} 次快招`));
}

function renderSideState(data, side, who) {
  const state_ = data.sides[side];
  const active = state_.members[state_.active];
  const bench = state_.members.filter((m) => m.slot !== state_.active);
  const stages = [];
  if (active.atk_stage) stages.push(`攻 ${active.atk_stage > 0 ? "+" : ""}${active.atk_stage}`);
  if (active.def_stage) stages.push(`防 ${active.def_stage > 0 ? "+" : ""}${active.def_stage}`);
  const shields = "●".repeat(state_.shields) + "○".repeat(Math.max(0, state.options.max_shields - state_.shields));
  return el("div", {class: `side-panel side-${side}`},
    el("div", {class: "side-title"},
      el("span", {class: `name side-${side}`}, `${who}：${state_.name}`),
      el("span", {class: "muted"}, `盾 ${shields}`),
      el("span", {class: "muted"}, state_.switch_timer_ms > 0 ? `换人冷却 ${Math.ceil(state_.switch_timer_ms / 1000)} 秒` : "可以换人"),
    ),
    el("div", {class: "active-row"},
      el("div", {
        class: `token ${active.fainted ? "fainted" : ""}`,
        id: `token-${side}`,
        style: `background: ${typeColor(active.types, 0)}; border-color: ${typeColor(active.types, 1)}`,
        title: active.types.join(" / "),
      }, active.name.slice(0, 2)),
      el("div", {class: "active-info"},
        el("div", {class: "active-name"}, active.name, stages.length ? el("span", {class: "muted"}, `（${stages.join("，")}）`) : null),
        el("div", {}, hpBar(active.hp, active.max_hp)),
        el("div", {class: "energy-line-row"}, energyBar(active), ` 能量 ${active.energy}`),
        el("div", {class: "muted"}, `快招 ${active.fast.name}（${active.fast.turns} 回合，+${active.fast.energy} 能量）`),
        el("div", {class: "moves-status"}, chargedStatus(active)),
      ),
    ),
    el("div", {class: "bench"}, "后备：", bench.map((m) => el("span", {class: `bench-member ${m.fainted ? "fainted-text" : ""}`},
      `${m.name} ${m.hp}/${m.max_hp} · 能量 ${m.energy}`))),
  );
}

function renderQuestion(data) {
  const question = data.question;
  const options = question.options;
  const manual = state.manual;
  const button = (option, attrs = {}) => el("button", {
    ...attrs,
    onclick: () => stepManual(decisionFrom(option)),
  }, option.label);
  const parts = [];
  if (question.kind === "action") {
    const fast = options.find((o) => o.action === "fast");
    const wait = options.find((o) => o.action === "wait");
    parts.push(
      el("div", {class: "question-title"}, "该你出招了"),
      el("div", {class: "button-row"},
        button(fast, {class: "primary", title: "回车 / 空格"}),
        button(wait, {title: "W"}),
        options.filter((o) => o.action === "switch").map((o) => button(o, {class: "switch-button"})),
      ),
      renderChargedControls(data),
      renderDamageHints(data),
    );
  } else if (question.kind === "shield") {
    parts.push(
      el("div", {class: "question-title alert"}, "对方放大招了！开盾吗？"),
      el("div", {class: "muted"}, `你还有 ${data.sides[manual.side].shields} 个盾。看对方的能量判断它放的是哪一招。`),
      el("div", {class: "button-row"},
        options.map((o) => button(o, {class: o.shield ? "primary" : "", title: o.shield ? "Y" : "N"}))),
    );
  } else if (question.kind === "zero_turn_switch") {
    parts.push(
      el("div", {class: "question-title"}, "可以不花回合换人（大招后的空回合，或者对手正在选人）"),
      el("div", {class: "button-row"}, options.map((o) => button(o, {class: o.to === null ? "primary" : "switch-button"}))),
    );
  } else {
    const fainted = data.sides[manual.side].members[data.sides[manual.side].active];
    parts.push(
      el("div", {class: "question-title"}, `你的 ${fainted.name} 倒下了，换谁上？`),
      el("div", {class: "button-row"}, options.map((o) => button(o, {class: "switch-button"}))),
    );
  }
  parts.push(el("div", {class: "muted keys"}, "快捷键：回车或空格 = 快招 / 不换，W = 什么都不做，Y / N = 开盾 / 不开盾，Backspace = 撤销上一步"));
  return el("div", {class: "question card"}, parts);
}

/** 每个大招一行：能量够的有威力拖动条（默认 100%），旁边实时显示伤害；不够的写还差几次快招。 */
function renderChargedControls(data) {
  const manual = state.manual;
  const me = data.sides[manual.side];
  const active = me.members[me.active];
  const them = data.sides[1 - manual.side];
  const target = them.members[them.active];
  const damage = data.damage;
  const rows = active.charged.map((move) => {
    const option = data.question.options.find((o) => o.action === "charged" && o.move_id === move.id);
    if (!option) {
      return el("div", {class: "charged-row disabled"}, el("span", {class: "charged-name"}, `${move.name}（${move.energy} 能量）`),
        el("span", {class: "muted"}, move.fast_needed === null ? "能量不够" : `能量不够，还差 ${move.fast_needed} 次快招`));
    }
    const table = damage.my_charged[move.id];
    const minPercent = damage.percents[0];
    const readout = el("span", {class: "readout"});
    const slider = el("input", {type: "range", min: minPercent, max: 100, step: 1, value: 100, class: "charge-slider"});
    const update = () => {
      const percent = Number(slider.value);
      const dealt = table.damage[percent - minPercent];
      const left = Math.max(0, damage.target_hp - dealt);
      readout.textContent = `威力 ${percent}% → 打 ${dealt}，${target.name} HP ${damage.target_hp} → ${left}${left === 0 ? "（打倒）" : ""}`;
    };
    slider.addEventListener("input", update);
    update();
    const setTo = (percent) => () => { slider.value = percent; update(); };
    const hints = [];
    if (table.ko_min !== null && table.survive_max !== null) {
      hints.push(
        el("button", {class: "small", onclick: setTo(table.survive_max)}, `不打死最多 ${table.survive_max}%`),
        el("button", {class: "small", onclick: setTo(table.ko_min)}, `打死至少要 ${table.ko_min}%`),
      );
    } else if (table.ko_min !== null) {
      hints.push(el("span", {class: "muted"}, `最低威力也能打倒`));
    } else {
      hints.push(el("span", {class: "muted"}, `满威力也打不倒`));
    }
    hints.push(el("button", {class: "small", onclick: setTo(100)}, "100%"));
    return el("div", {class: "charged-row"},
      el("button", {class: "charged-go", onclick: () => stepManual(decisionFrom(option, Number(slider.value) / 100))}, `放 ${move.name}`),
      slider, readout, el("span", {class: "hints"}, hints));
  });
  const shieldNote = them.shields > 0
    ? `对方还有 ${them.shields} 个盾：开盾的话只打 1。对方判断开不开盾时看的是满威力的伤害。`
    : "对方没有盾了。";
  return el("div", {class: "charged-controls"}, el("div", {class: "muted"}, `大招（不开盾时的伤害）。${shieldNote}`), rows);
}

function renderDamageHints(data) {
  const manual = state.manual;
  const damage = data.damage;
  const me = data.sides[manual.side];
  const them = data.sides[1 - manual.side];
  const mine = me.members[me.active];
  const theirs = them.members[them.active];
  const theirCharged = theirs.charged.map((c) => `${c.name} ${damage.their_charged[c.id]}`).join("、");
  return el("div", {class: "muted damage-hints"},
    `你的 ${mine.fast.name} 每次打 ${damage.my_fast}；对方的 ${theirs.fast.name} 每次打你 ${damage.their_fast}，` +
    `大招满威力打你：${theirCharged}。`);
}

function renderLog(data, newEvents) {
  const names = SIDES.map((side) => data.sides[side].members.map((m) => m.name));
  const recent = data.events.slice(-14);
  const fresh = new Set(newEvents);
  return el("div", {class: "log card"},
    el("div", {class: "question-title"}, "战况（最近的事件；高亮的是刚才发生的）"),
    recent.length === 0 ? el("div", {class: "muted"}, "还没有事件。") : null,
    recent.map((event) => el("div", {class: `${eventClass(event)} ${fresh.has(event) ? "fresh" : ""}`},
      el("span", {class: "muted"}, `T${event.data.turn} `),
      el("span", {class: `who name side-${event.side}`}, names[event.side][event.slot]), " ", event.text)),
  );
}

/** 刚才发生的事件：挨了快招的抖一下并飘出伤害数字，挨了大招的闪一下，换上来的淡入。 */
function animateEvents(newEvents, data) {
  const hits = [{damage: 0, big: false}, {damage: 0, big: false}];
  const entered = new Set();
  for (const event of newEvents) {
    if (event.type === "move") {
      const target = 1 - event.side;
      hits[target].damage += event.data.damage;
      hits[target].big ||= event.data.is_charged;
    } else if (event.type === "switch") {
      entered.add(event.side);
    }
  }
  for (const side of SIDES) {
    const token = document.getElementById(`token-${side}`);
    if (!token) continue;
    if (entered.has(side)) token.classList.add("enter");
    if (hits[side].damage > 0) {
      token.classList.add(hits[side].big ? "hit-big" : "hit");
      token.parentElement.append(el("span", {class: `float-damage ${hits[side].big ? "big" : ""}`}, `-${hits[side].damage}`));
    }
  }
}

function onManualKey(event) {
  const data = state.manual?.data;
  if (!data || state.manual.pending) return;
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName) && document.activeElement.type !== "range") return;
  const key = event.key.toLowerCase();
  if (key === "backspace") { // 打完了也可以撤销最后一步
    event.preventDefault();
    undoManual();
    return;
  }
  if (data.status !== "decide") return;
  const options = data.question.options;
  let option = null;
  if (key === "enter" || key === " ") {
    option = options.find((o) => o.action === "fast") ?? options.find((o) => o.kind === "zero_turn_switch" && o.to === null);
  } else if (key === "w") {
    option = options.find((o) => o.action === "wait");
  } else if (key === "y" || key === "n") {
    option = options.find((o) => o.kind === "shield" && o.shield === (key === "y"));
  }
  if (option) {
    event.preventDefault();
    stepManual(decisionFrom(option));
  }
}

// ---- 搜索应对（4e） ----
//
// 对另一队的 3v3 策略（固定不变），逐步试探搜索一队更好的打法（pogo_sim/best_response.py、web_api.best_response）。
// 服务器返回搜索的概况、试过的每个决定点（每个选项打出来的结果）、搜索后的这一场和原策略那一场；
// 下面的过程图、分段、时间线显示其中一场，可以切换。

async function runBestResponse() {
  const button = document.getElementById("br-start");
  const side = Number(document.getElementById("br-side").value);
  button.disabled = true;
  showError("");
  setStatus("正在搜索……（每个决定点的每个选项都打一场，一般 0.5–2 秒）");
  try {
    const data = await api("/api/best-response", {config: requestConfig(), side});
    state.bestResponse = data;
    state.result = data.result;
    renderResult();
    setStatus(`搜索完了：打了 ${data.search.trials} 场，用时 ${data.search.seconds} 秒`);
    document.getElementById("result").scrollIntoView({behavior: "smooth"});
  } catch (e) {
    showError(e.message);
    setStatus("");
  } finally {
    button.disabled = false;
  }
}

/** 正在看的是搜索后的那一场时，改了的决定点（否则为空）。 */
function changes(r) {
  const br = state.bestResponse;
  return br && r === br.result ? br.tried.filter((t) => t.changed) : [];
}

function changedTurns(r) {
  return new Set(changes(r).map((t) => t.turn));
}

/** 一个决定点每个选项打出来的结果：绿是赢、灰是平、红是输；粗框是搜索后选的。 */
function optionChips(tried) {
  return el("div", {class: "br-options"}, tried.options.map((o) => el("span", {
    class: `br-option outcome-${o.score.outcome}${o.chosen ? " chosen" : ""}`,
  }, `${o.label}：${o.score.short}`, o.policy ? el("span", {class: "tag"}, "（原策略）") : null)));
}

function bestResponseCard(br) {
  const s = br.search;
  const showing = state.result === br.baseline ? "baseline" : "result";
  const view = (key, text) => el("button", {
    class: showing === key ? "current" : undefined,
    onclick: () => { state.result = br[key]; renderResult(); },
  }, text);
  const changed = br.tried.filter((t) => t.changed);
  const jump = (t) => () => { if (showing === "result") jumpToTurn(t.turn); };

  const changedRows = changed.map((t, i) => ({
    attrs: {class: "br-row", title: "点一下跳到时间线的这一回合", onclick: jump(t)},
    cells: [
      el("td", {class: "num"}, `改${i + 1}`),
      el("td", {class: "num"}, t.turn),
      t.kind_text,
      t.policy_choice,
      el("td", {}, el("b", {}, t.chosen)),
      `${t.before.short} → ${t.after.short}`,
      el("td", {}, optionChips(t)),
    ],
  }));
  const allRows = br.tried.map((t) => ({
    attrs: {class: `br-row${t.changed ? " br-changed" : ""}`, onclick: jump(t)},
    cells: [
      el("td", {class: "num"}, t.turn),
      t.kind_text,
      t.policy_choice,
      t.changed ? el("td", {}, el("b", {}, t.chosen)) : el("td", {class: "muted"}, "同原策略"),
      el("td", {}, optionChips(t)),
    ],
  }));

  return el("div", {class: "card"},
    el("h2", {}, `搜索应对：${s.team} 对 ${s.opponent} 的固定策略`),
    el("p", {class: "muted"},
      "先让双方都照原策略（TeamPolicy）打一场；然后沿着当前最好的一场，按顺序把 " + s.team +
      " 每个决定点的其余选项都试一遍（之前的决定照当前最好的一场，之后双方照各自的策略打完），严格更好就改。" +
      "比较时先看胜负，再看评分。结果不比原策略差，但不保证全局最优；搜索完全知道对方的策略会怎么应对，所以是针对这个策略的打法。"),
    el("p", {class: "br-summary"}, el("b", {}, "原策略："), s.baseline.text),
    el("p", {class: "br-summary"}, el("b", {}, "搜索后："), s.best.text),
    el("p", {class: "muted"},
      `${s.team} 一共做了 ${s.decisions} 个决定，其中 ${s.examined} 个有不止一个选项、都试过；改了 ${s.changed} 个。` +
      `一共打了 ${s.trials} 场，用时 ${s.seconds} 秒。`),
    el("div", {class: "br-view"}, "下面显示：", view("result", "搜索后的这一场"), view("baseline", "原策略那一场")),
    el("h2", {class: "sub"}, "改了哪些决定"),
    changed.length
      ? [
        el("p", {class: "muted"},
          "按搜索的顺序。“改之前 → 改之后”是当时最好的一场和改了以后的结果（从 " + s.team + " 看：胜负和评分）；" +
          "“各选项”是这个决定点每个选项打出来的结果（之前的决定照当时最好的一场，之后照各自的策略）。" +
          "后面的改动是在前面改过的基础上试的。图上的绿色虚线是改了的决定；点一行跳到时间线的那一回合。"),
        table(["", "回合", "决定", "原策略", "改成", "改之前 → 改之后", "各选项打出来的结果"], changedRows),
      ]
      : el("p", {}, "一个都没改：每个决定点上，原策略的选择已经是试过的选项里最好的。"),
    el("details", {class: "br-all"},
      el("summary", {}, `试过的全部决定点（${br.tried.length} 个）`),
      el("p", {class: "muted"}, "每个有不止一个选项的决定点一行，按搜索的顺序；改了的标绿。"),
      table(["回合", "决定", "原策略", "搜索后", "各选项打出来的结果"], allRows)),
  );
}

// ---- 队伍库和导入导出（4f） ----
//
// 队伍库在仓库的 teams/，一队一个 TOML 文件（格式见 pogo_sim/team_library.py）。网页能列出、载入、存进去，
// 不能删除（要删就手动删文件）；同名的先问再覆盖。导入 / 导出的是 3v3 配置文件，和命令行同一格式。
// 检查、写文件、读文件都在服务器（web_api 的 library_payload、save_library_team、import_team_battle、export_team_battle）。

function leagueName(cp) {
  return state.options.leagues.find((l) => l.cp === cp)?.name ?? `CP ${cp}`;
}

async function toggleLibrary(side) {
  state.libraryOpen = state.libraryOpen === side ? null : side;
  renderTeams();
  if (state.libraryOpen === null) return;
  state.library = null;
  try {
    state.library = await api("/api/team-library");
  } catch (e) {
    showError(e.message);
  }
  renderLibrary(side);
}

function renderLibrary(side) {
  document.getElementById(`library-${side}`)?.replaceChildren(...libraryContent(side));
}

/** 打开的队伍库（library.js）：每队一行的按钮是"载入到 这一队"。 */
function libraryContent(side) {
  return libraryPanel(state.library, {
    league: state.config.league,
    leagueName: leagueName(state.config.league),
    filter: state.libraryFilter,
    buttons: (entry) => el("button", {onclick: () => loadLibraryTeam(side, entry)},
      `载入到 ${state.config.team[side].name || `第 ${side} 方`}`),
  });
}

/** 把库里的一队填到第 side 方：用到的覆盖文件自动勾上；联盟不同只提示，不强制。 */
async function loadLibraryTeam(side, entry) {
  const {customFiles, added, notes} = libraryLoadPlan(entry, state.config.custom_files,
    state.options.custom_files.map((f) => f.name), state.config.league, leagueName(state.config.league));
  if (entry.unsupported.length) notes.push(`网页上改不了的策略参数没有载入：${entry.unsupported.join("、")}`);

  state.config.custom_files = customFiles;
  state.config.team[side] = normalizeSide(entry.team, side);
  state.libraryOpen = null;
  configChanged();
  showError("");
  if (added.length) {
    await start(); // 覆盖文件变了：重新读宝可梦列表
  } else {
    renderTeams();
    rebuildMembers();
  }
  setStatus(`已载入 ${entry.name}（teams/${entry.file}）${notes.length ? `。${notes.join("；")}` : ""}`);
}

/** 把第 side 方存进队伍库（library.js）。 */
async function saveLibraryTeam(side) {
  showError("");
  try {
    const status = await saveTeamToLibrary(requestConfig().team[side], buildSettings(), leagueName(state.config.league));
    if (status === null) return;
    setStatus(status);
    if (state.libraryOpen !== null) {
      state.library = await api("/api/team-library");
      renderLibrary(state.libraryOpen);
    }
  } catch (e) {
    showError(e.message);
  }
}

async function exportConfig() {
  showError("");
  try {
    const data = await api("/api/export-config", requestConfig());
    downloadText(data.filename, data.text, "application/toml");
    setStatus(`已导出 ${data.filename}`);
  } catch (e) {
    showError(e.message);
  }
}

async function importConfig(file) {
  showError("");
  try {
    const data = await api("/api/import-config", {text: await file.text(), name: file.name});
    const warnings = data.warnings.length ? `\n\n注意：\n- ${data.warnings.join("\n- ")}` : "";
    if (!confirm(`导入 ${file.name}？现在填的设置和两队会被换掉。${warnings}`)) return;
    state.config = normalizeConfig(data.config);
    state.libraryOpen = null;
    save();
    await start();
    setStatus(`已导入 ${file.name}${data.warnings.length ? `（${data.warnings.join("；")}）` : ""}`);
  } catch (e) {
    showError(e.message);
  }
}

// ---- 启动 ----

/** 按 state.config 画设置和两队，并请服务器建每只的配置。 */
async function start() {
  forgetMembers();
  renderSettings();
  await reloadCatalog();
  renderTeams();
  rebuildMembers();
}

async function init() {
  document.getElementById("run").addEventListener("click", runBattle);
  document.getElementById("reset").addEventListener("click", resetToExample);
  document.getElementById("manual-start").addEventListener("click", startManual);
  document.getElementById("manual-resume").addEventListener("click", resumeManual);
  document.getElementById("br-start").addEventListener("click", runBestResponse);
  document.getElementById("export-config").addEventListener("click", exportConfig);
  document.getElementById("import-config").addEventListener("click", () => document.getElementById("import-file").click());
  document.getElementById("import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // 同一个文件再选一次也能触发
    if (file) importConfig(file);
  });
  document.addEventListener("keydown", onManualKey);
  try {
    state.options = await api("/api/options");
    const pairing = takePairing();
    state.config = normalizeConfig(pairing?.config ?? loadSaved() ?? state.options.example);
    if (pairing) save();
    await start();
    updateResumeButton();
    if (pairing) {
      setStatus(`已载入队伍对队伍页里的一场：${pairing.title}${pairing.warnings.length ? `（${pairing.warnings.join("；")}）` : ""}`);
    }
  } catch (e) {
    showError(`页面加载失败：${e.message}`);
  }
}

init();
