"use strict";
// 网页界面（第 4 步，4a）：选队伍、打一场 3v3、看结果和逐回合时间线。
//
// 这里只负责填表和显示，不算任何东西：建配置、检查、对战、统计都在 Python 引擎里，
// 通过 tools/run_web.py 的接口拿结果（每个接口返回什么见 pogo_sim/web_api.py）。
// 页面上的配置和 3v3 配置文件（pogo_sim/team_battle.py 开头）写法一样；浏览器会记住上次填的（localStorage）。

const STORAGE_KEY = "pogo_sim.team_battle.config.v1";
const SIDES = [0, 1];
const BUILD_DELAY_MS = 300; // 改完一只后等这么久再请服务器建配置（连续输入时只请一次）

const state = {
  options: null, // GET /api/options：下拉选项和例子配置
  catalog: null, // GET /api/species：{species: [...], moves: {招式 ID: {...}}}
  speciesById: new Map(),
  config: null, // 页面上的配置（normalizeConfig）；发给服务器前用 requestConfig 整理
  builds: [[], []], // 每只的建配置结果（POST /api/build）：{info} 或 {error}
  buildTimers: new Map(),
  buildSeq: new Map(), // 每只最新一次建配置请求的序号：旧请求的结果晚到时丢掉
  openDetails: new Set(), // 展开了"更多设置"的是哪几只（重新画这一只时保持展开）
  result: null, // POST /api/team-battle 的结果（手动对战打完以后是那一场的结果）
  manual: null, // 手动对战：{config, side, decisions, data（服务器最近一次的回答）, seenEvents, pending}
  showDecisions: true, // 时间线里显示决定和原因
};

// ---- 小工具（其余在 common.js） ----

function memberKey(side, slot) {
  return `${side}-${slot}`;
}

// ---- 配置 ----

/** 把例子配置或浏览器记住的配置整理成页面用的样子（缺的字段补上默认值）。 */
function normalizeConfig(raw) {
  const options = state.options;
  return {
    league: raw.league ?? 1500,
    season: raw.season ?? options.seasons[0].key,
    custom_files: (raw.custom_files ?? []).filter((name) => options.custom_files.some((f) => f.name === name)),
    team: SIDES.map((side) => normalizeTeam(raw.team?.[side] ?? {}, side)),
  };
}

function normalizeTeam(team, side) {
  const size = state.options.team_size;
  return {
    name: team.name ?? (side === 0 ? "Team A" : "Team B"),
    shields: team.shields ?? state.options.max_shields,
    policy: {switching: team.policy?.switching ?? state.options.switching[0].key},
    member: Array.from({length: size}, (_, slot) => normalizeMember(team.member?.[slot] ?? {})),
  };
}

function normalizeMember(member) {
  return {
    species: member.species ?? "",
    fast: member.fast ?? "",
    charged: [...(member.charged ?? [])],
    label: member.label ?? "",
    ivs: member.ivs ?? [null, null, null], // 三项都填了才发给服务器，否则按赛季规则取 IV 排名第 1
    level: member.level ?? null,
    best_buddy: member.best_buddy ?? false,
    mega_level: member.mega_level ?? null,
    outside_movepool: member.outside_movepool ?? false,
  };
}

/** 一只宝可梦发给服务器的写法：同配置文件里的 [[team.member]]，没填的可选项不写。 */
function memberRequest(member) {
  const out = {species: member.species, fast: member.fast, charged: member.charged.filter(Boolean)};
  if (member.label) out.label = member.label;
  if (member.ivs.every((v) => Number.isInteger(v))) out.ivs = member.ivs;
  if (member.level !== null) out.level = member.level;
  if (member.best_buddy) out.best_buddy = true;
  if (member.mega_level !== null) out.mega_level = member.mega_level;
  if (member.outside_movepool) out.outside_movepool = true;
  return out;
}

/** 打一场时发给服务器的配置：同 3v3 配置文件。 */
function requestConfig() {
  const config = state.config;
  return {
    league: config.league,
    season: config.season,
    custom_files: config.custom_files,
    team: config.team.map((team) => ({
      name: team.name,
      shields: team.shields,
      policy: {switching: team.policy.switching},
      member: team.member.map(memberRequest),
    })),
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

/** 配置改了：记住，并标出下面的结果是改之前的。 */
function configChanged() {
  save();
  const note = document.getElementById("stale-note");
  if (note) note.hidden = false;
}

// ---- 宝可梦和招式的显示 ----

/** 宝可梦名字后面的说明：属性、覆盖文件、未实装、PvPoke 在这个联盟的排名。 */
function speciesFacts(species) {
  const facts = [species.types.join("/")];
  if (species.custom) facts.push("覆盖文件");
  if (!species.released) facts.push("未实装");
  if (species.rank) facts.push(`PvPoke 第 ${species.rank}`);
  if (species.mega_rank) facts.push(`Mega 版排名第 ${species.mega_rank}`);
  return facts.join(" · ");
}

function moveText(moveId) {
  const move = state.catalog.moves[moveId];
  if (!move) return `${moveId}（没有这个招式）`;
  if (move.fast) {
    return `${move.name} · ${move.type} · 威力 ${move.power} · +${move.energy} 能量 · ${move.turns} 回合`;
  }
  return `${move.name} · ${move.type} · 威力 ${move.power} · ${move.energy} 能量`;
}

/** 下拉框里能选的招式：招式池（勾了"招式池外"时是全部同类招式），现在选的总在里面。 */
function moveChoices(ids, current, optional) {
  const list = [...ids];
  if (current && !list.includes(current)) list.unshift(current);
  const choices = list.map((id) => [id, moveText(id)]);
  return optional ? [["", "（不带）"], ...choices] : choices;
}

function allMoves(fast) {
  return Object.entries(state.catalog.moves).filter(([, m]) => m.fast === fast).map(([id]) => id).sort();
}

/** 选了宝可梦以后先填的配招：PvPoke 在这个联盟的推荐配招，没有就取招式池里的前几个。 */
function defaultMoves(species) {
  if (species.recommended) {
    const [fast, ...charged] = species.recommended;
    return {fast, charged};
  }
  return {fast: species.fast[0] ?? "", charged: species.charged.slice(0, 2)};
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
      rebuildAll();
    },
    {id: "league"},
  ));
  document.getElementById("season").replaceWith(select(
    options.seasons.map((s) => [s.key, s.name]),
    config.season,
    (value) => {
      config.season = value;
      configChanged();
      rebuildAll();
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
        rebuildAll();
      },
    }),
    ` 覆盖文件 ${file.name}`,
    file.description ? el("span", {class: "muted"}, `：${file.description}`) : null,
  ));
  document.getElementById("custom-files").replaceChildren(...files);
}

async function reloadCatalog() {
  const params = new URLSearchParams({league: state.config.league});
  for (const name of state.config.custom_files) params.append("custom", name);
  state.catalog = await api(`/api/species?${params}`);
  state.speciesById = new Map(state.catalog.species.map((s) => [s.id, s]));
  for (const species of state.catalog.species) species.nameKey = normalizeSearch(species.name);
}

// ---- 选宝可梦：可以搜的下拉框 ----
// 点一下输入框就列出全部宝可梦（有 PvPoke 排名时按这个联盟的排名，排名外的按图鉴编号）。
// 输入名字的一部分可以缩小范围：拆成几个词，每个词都要在 web_api.search_text 给的文字里出现，不分先后，
// 所以 "mega venu"、"venusaur mega"、"zygarde 100"、"legendary" 都能搜到。
// 选好一只以后，旁边的"形态"下拉框列出同一图鉴编号的各形态（普通、暗影、Mega……），可以直接换。

const PICKER_LIMIT = 100; // 下拉框里最多列出几个（太多时继续输入缩小范围）

/** 搜宝可梦，返回排好序的列表。
 *  排序：名字以输入开头的最前；其次每个词都是某个词的开头；然后按 PvPoke 普通排名（排名外的在后面）、图鉴顺序。 */
function searchSpecies(query) {
  const q = normalizeSearch(query);
  const words = q.split(" ").filter(Boolean);
  const found = [];
  state.catalog.species.forEach((species, index) => {
    const text = ` ${species.search}`;
    if (!words.every((w) => text.includes(w))) return;
    let tier = 2;
    if (species.nameKey.startsWith(q)) tier = 0;
    else if (words.every((w) => text.includes(` ${w}`))) tier = 1;
    found.push({species, tier, rank: species.rank ?? Infinity, index});
  });
  found.sort((a, b) => a.tier - b.tier || (a.rank - b.rank || 0) || a.index - b.index);
  return found.map((f) => f.species);
}

function pickerNote(typed, count) {
  const hint = "名字用英文，几个词不分先后，如 mega venu、zygarde 100";
  if (typed) return count ? `搜到 ${count} 个（↑↓ 选，回车确定，Esc 取消）` : `没有搜到。${hint}`;
  const ranked = state.catalog.species.some((s) => s.rank);
  const order = ranked ? "按 PvPoke 这个联盟的排名列出（排名外的和 Mega 按图鉴编号排在后面）" : "按图鉴编号列出";
  return `${order}。输入可以搜：${hint}`;
}

/** 选宝可梦的输入框和下拉列表。打开时输入框先清空（原来的名字留作灰字提示），没选就关掉时恢复原样。 */
function speciesPicker(side, slot, member, species) {
  const currentText = species ? species.name : member.species;
  const input = el("input", {
    class: "species",
    value: currentText,
    placeholder: "点一下选，或输入名字搜",
    autocomplete: "off",
    spellcheck: "false",
  });
  const menu = el("div", {class: "species-menu", hidden: true});
  let results = [];
  let active = 0;

  const optionNodes = () => menu.querySelectorAll(".species-option");
  const highlight = (i) => {
    const nodes = optionNodes();
    if (nodes.length === 0) return;
    active = Math.max(0, Math.min(i, nodes.length - 1));
    nodes.forEach((node, j) => node.classList.toggle("active", j === active));
    nodes[active].scrollIntoView({block: "nearest"});
  };
  const show = () => {
    const typed = input.value.trim() !== "";
    results = searchSpecies(input.value);
    const rows = results.slice(0, PICKER_LIMIT).map((s, i) => el("div", {
      class: "species-option",
      onmousedown: (e) => { e.preventDefault(); pick(s.id); }, // preventDefault：不让输入框先失去焦点
      onmousemove: () => { if (active !== i) highlight(i); },
    }, typeDots(s.types), el("span", {class: "option-name"}, s.name), el("span", {class: "muted"}, speciesFacts(s))));
    if (results.length > PICKER_LIMIT) {
      rows.push(el("div", {class: "menu-note"}, `还有 ${results.length - PICKER_LIMIT} 个没列出，继续输入可以缩小范围`));
    }
    menu.replaceChildren(el("div", {class: "menu-note"}, pickerNote(typed, results.length)), ...rows);
    menu.hidden = false;
    menu.scrollTop = 0;
    highlight(0);
  };
  const close = () => {
    menu.hidden = true;
    input.value = currentText;
    input.placeholder = "点一下选，或输入名字搜";
  };
  const open = () => {
    input.value = "";
    input.placeholder = currentText || "点一下选，或输入名字搜";
    show();
  };
  const pick = (id) => {
    close();
    if (id === member.species) input.blur(); // 选回原来那只：配招不动
    else setSpecies(side, slot, id);
  };

  input.addEventListener("focus", open);
  input.addEventListener("click", () => { if (menu.hidden) open(); });
  input.addEventListener("input", show);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (menu.hidden) open();
      else highlight(active + (e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!menu.hidden && results.length > 0) pick(results[active].id);
    } else if (e.key === "Escape") {
      close();
      input.blur();
    }
  });
  input.addEventListener("blur", () => {
    if (menu.hidden) return;
    // 输入了完整的名字或 ID 但没点选：也算选了；其他情况恢复原样
    const q = normalizeSearch(input.value);
    const exact = q && state.catalog.species.find((s) => s.nameKey === q || normalizeSearch(s.id) === q);
    if (exact) pick(exact.id);
    else close();
  });
  return el("span", {class: "species-picker"}, input, menu);
}

/** 同一图鉴编号的各形态（普通、暗影、Mega、地区形态……）；只有一种时为空。 */
function formsOf(species) {
  const forms = state.catalog.species.filter((s) => s.dex === species.dex);
  return forms.length > 1 ? forms : [];
}

// ---- 两队 ----

function renderTeams() {
  renderManualSideSelect();
  document.getElementById("teams").replaceChildren(...SIDES.map(renderTeam));
  for (const side of SIDES) {
    state.config.team[side].member.forEach((_, slot) => renderBuild(side, slot));
  }
}

function renderTeam(side) {
  const team = state.config.team[side];
  const {options} = state;
  const shields = Array.from({length: options.max_shields + 1}, (_, n) => [n, `${n} 盾`]);
  return el("div", {class: `card team side-${side}`},
    el("div", {class: "team-head"},
      el("input", {
        class: "team-name",
        value: team.name,
        title: "队名（两队不能同名）",
        oninput: (e) => { team.name = e.target.value; configChanged(); renderManualSideSelect(); },
      }),
      select(shields, team.shields, (v) => { team.shields = Number(v); configChanged(); }),
      select(options.switching.map((s) => [s.key, s.name]), team.policy.switching,
        (v) => { team.policy.switching = v; configChanged(); }),
    ),
    team.member.map((_, slot) => renderMember(side, slot)),
  );
}

function renderMember(side, slot) {
  const member = state.config.team[side].member[slot];
  const species = state.speciesById.get(member.species);
  const changed = () => memberChanged(side, slot);
  const setCharged = (i) => (value) => {
    member.charged[i] = value;
    changed();
  };

  let speciesNote = "";
  if (species) speciesNote = speciesFacts(species);
  else if (member.species) speciesNote = el("span", {class: "bad"}, "没有这个宝可梦");
  const forms = species ? formsOf(species) : [];

  const moves = [];
  if (species) {
    const fastIds = member.outside_movepool ? allMoves(true) : species.fast;
    const chargedIds = member.outside_movepool ? allMoves(false) : species.charged;
    moves.push(
      el("span", {}, "快招"),
      select(moveChoices(fastIds, member.fast, false), member.fast, (v) => { member.fast = v; changed(); }),
      el("span", {}, "大招 1"),
      select(moveChoices(chargedIds, member.charged[0], false), member.charged[0], setCharged(0)),
      el("span", {}, "大招 2"),
      select(moveChoices(chargedIds, member.charged[1], true), member.charged[1] ?? "", setCharged(1)),
    );
    if (species.extra_charged.length > 0) {
      moves.push(
        el("span", {}, "大招 3"),
        select(moveChoices(species.extra_charged, member.charged[2], true), member.charged[2] ?? "", setCharged(2)),
      );
    }
  }

  return el("div", {class: "member", id: `member-${memberKey(side, slot)}`},
    el("div", {class: "member-head"},
      el("span", {class: "role"}, slot === 0 ? "首发" : `后备 ${slot}`),
      speciesPicker(side, slot, member, species),
      forms.length ? el("label", {class: "forms", title: "同一图鉴编号的其他形态：普通、暗影、Mega、地区形态……"}, "形态 ",
        select(forms.map((s) => [s.id, s.name]), species.id, (id) => setSpecies(side, slot, id))) : null,
      el("span", {class: "muted"}, speciesNote),
    ),
    moves.length ? el("div", {class: "moves"}, moves) : null,
    renderDetails(side, slot, member, species),
    el("div", {class: "build", id: `build-${memberKey(side, slot)}`}),
  );
}

/** "更多设置"：名字、IV、等级、挚友、Mega 等级、招式池外的招，以及建配置的说明。 */
function renderDetails(side, slot, member, species) {
  const key = memberKey(side, slot);
  const changed = () => memberChanged(side, slot);
  const number = (value, attrs, onValue) => el("input", {
    type: "number",
    value: value ?? "",
    ...attrs,
    oninput: (e) => {
      const v = e.target.value === "" ? null : Number(e.target.value);
      onValue(Number.isNaN(v) ? null : v);
      changed();
    },
  });
  const ivNames = ["攻", "防", "HP"];

  const details = el("details", {
    open: state.openDetails.has(key),
    ontoggle: (e) => {
      if (e.target.open) state.openDetails.add(key);
      else state.openDetails.delete(key);
    },
  },
    el("summary", {}, "更多设置（IV、等级、名字……）"),
    el("div", {class: "details-grid"},
      el("label", {}, "名字 ", el("input", {
        value: member.label,
        placeholder: species?.name ?? "",
        oninput: (e) => { member.label = e.target.value; changed(); },
      })),
      el("label", {}, "IV ",
        ivNames.map((name, i) => number(member.ivs[i], {min: 0, max: 15, step: 1, placeholder: name, title: name},
          (v) => { member.ivs[i] = v; }))),
      el("label", {}, "等级 ", number(member.level, {min: 1, max: 55, step: 0.5, placeholder: "自动"},
        (v) => { member.level = v; })),
      el("label", {}, el("input", {
        type: "checkbox",
        checked: member.best_buddy,
        onchange: (e) => { member.best_buddy = e.target.checked; changed(); },
      }), " 挚友"),
      species?.mega ? el("label", {}, "Mega 等级 ", select(
        [["", "自动"], [1, "1"], [2, "2"], [3, "3"], [4, "4"]],
        member.mega_level ?? "",
        (v) => { member.mega_level = v === "" ? null : Number(v); changed(); },
      )) : null,
      el("label", {}, el("input", {
        type: "checkbox",
        checked: member.outside_movepool,
        onchange: (e) => {
          member.outside_movepool = e.target.checked;
          refreshMember(side, slot); // 能选的招式变了
          changed();
        },
      }), " 允许招式池外的招"),
    ),
    el("div", {class: "muted"}, "IV 三项都填才生效；不填 IV 和等级时按赛季规则取 IV 排名第 1 和合法的最高等级。"),
    el("ul", {class: "notes", id: `notes-${key}`}),
  );
  return details;
}

function refreshMember(side, slot) {
  document.getElementById(`member-${memberKey(side, slot)}`).replaceWith(renderMember(side, slot));
  renderBuild(side, slot);
}

/** 选了宝可梦（ID）：换成它的推荐配招。 */
function setSpecies(side, slot, id) {
  const member = state.config.team[side].member[slot];
  member.species = id;
  const species = state.speciesById.get(id);
  if (species) {
    const moves = defaultMoves(species);
    member.fast = moves.fast;
    member.charged = moves.charged;
    if (!species.mega) member.mega_level = null;
  }
  refreshMember(side, slot);
  memberChanged(side, slot);
}

function memberChanged(side, slot) {
  configChanged();
  scheduleBuild(side, slot);
}

// ---- 建配置（服务器算 CP、等级、IV） ----

function scheduleBuild(side, slot) {
  const key = memberKey(side, slot);
  clearTimeout(state.buildTimers.get(key));
  state.buildTimers.set(key, setTimeout(() => runBuild(side, slot), BUILD_DELAY_MS));
}

function rebuildAll() {
  for (const side of SIDES) {
    state.config.team[side].member.forEach((_, slot) => scheduleBuild(side, slot));
  }
}

async function runBuild(side, slot) {
  const key = memberKey(side, slot);
  const seq = (state.buildSeq.get(key) ?? 0) + 1;
  state.buildSeq.set(key, seq);
  const member = state.config.team[side].member[slot];
  let build;
  if (!member.species) {
    build = {error: "还没选宝可梦"};
  } else {
    try {
      const {league, season, custom_files} = state.config;
      build = {info: await api("/api/build", {league, season, custom_files, member: memberRequest(member)})};
    } catch (e) {
      build = {error: e.message};
    }
  }
  if (state.buildSeq.get(key) !== seq) return; // 这期间又改过，以后面那次为准
  state.builds[side][slot] = build;
  renderBuild(side, slot);
}

function renderBuild(side, slot) {
  const key = memberKey(side, slot);
  const box = document.getElementById(`build-${key}`);
  const notes = document.getElementById(`notes-${key}`);
  if (!box) return;
  const build = state.builds[side][slot];
  if (!build) {
    box.replaceChildren(el("span", {class: "muted"}, "……"));
    return;
  }
  if (build.error) {
    box.replaceChildren(el("span", {class: "bad"}, build.error));
    notes?.replaceChildren();
    return;
  }
  const info = build.info;
  const parts = [`CP ${info.cp}`, `${info.level} 级`, `IV ${info.ivs.join("/")}`];
  if (info.mega_level !== null) parts.push(`Mega 等级 ${info.mega_level}`);
  parts.push(`HP ${info.hp}`, `攻 ${info.atk.toFixed(1)}`, `防 ${info.def.toFixed(1)}`);
  box.replaceChildren(el("span", {}, parts.join(" · ")));
  notes?.replaceChildren(...info.notes.map((note) => el("li", {}, note)));
}

// ---- 打一场 ----

async function runBattle() {
  const button = document.getElementById("run");
  button.disabled = true;
  showError("");
  setStatus("正在打……");
  try {
    state.result = await api("/api/team-battle", requestConfig());
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

function renderResult() {
  const r = state.result;
  const section = document.getElementById("result");
  section.hidden = false;
  section.replaceChildren(
    el("div", {class: "card"},
      el("div", {class: "result-head"},
        el("h2", {}, "结果"),
        el("button", {onclick: downloadReport}, "下载 Markdown 报告"),
      ),
      el("p", {class: "stale", id: "stale-note", hidden: true}, "配置改过了：下面还是上一次打的结果，再点一次“打一场”更新。"),
      el("p", {class: "outcome"}, r.outcome),
      el("p", {class: "muted"}, `${r.settings.league_name}；赛季规则：${r.settings.season}`),
      r.settings.custom_log.map((line) => el("p", {class: "muted"}, `覆盖文件：${line}`)),
      r.teams.map((team, side) => el("div", {class: `team-line side-${side}`},
        el("span", {class: "name"}, `${team.name}（${team.shields} 盾，${team.policy}）：`),
        team.members.map((m, slot) => `${slot ? "；" : ""}${team.names[slot]} CP ${m.cp} ${m.level} 级 IV ${m.ivs.join("/")}`),
      )),
    ),
    card("战斗过程", ...chartView(r)),
    card("对位分段", ...segmentsView(r)),
    card("每只的情况",
      el("p", {class: "muted"}, "挨大招：被大招打中时开盾挡下的次数 / 队伍还有盾但没开的次数。被盾挡下的大招算 1 点伤害。"),
      membersTable(r)),
    card("开局对位评分", ...openingTables(r)),
    card("换人", switchesTable(r)),
    card("大招和开盾", chargedTable(r)),
    card("时间线", ...timelineView(r)),
  );
}

function membersTable(r) {
  const rows = r.members.map((s) => {
    const counts = new Map();
    for (const move of s.charged_moves) counts.set(move, (counts.get(move) ?? 0) + 1);
    const charged = [...counts].map(([move, n]) => `${move} ×${n}`).join(", ") || "—";
    return [
      r.teams[s.side].name,
      nameOf(r, s.side, s.slot),
      hpBar(s.hp, s.max_hp),
      el("td", {class: "num"}, s.energy),
      el("td", {class: "num"}, s.damage_dealt),
      el("td", {class: "num"}, s.damage_taken),
      el("td", {class: "num"}, s.fast_moves),
      el("td", {class: "text"}, charged),
      `${s.charged_shielded} / ${s.charged_unshielded}`,
      s.fainted_turn !== null ? `第 ${s.fainted_turn} 回合` : "—",
    ];
  });
  return table(["队伍", "宝可梦", "剩余 HP", "剩余能量", "造成伤害", "受到伤害", "快招", "大招", "挨大招：开盾 / 没开", "倒下"], rows);
}

function openingTables(r) {
  const parts = [el("p", {class: "muted"},
    "TeamPolicy 选人、换人看的就是这种评分：行上那只对列上那只打 1v1，双方满 HP、0 能量，盾数从 0 到两队开局的盾数，按 [4, 4, 1] 加权平均。500 是平手。")];
  if (r.opening.length === 1) {
    parts.push(el("p", {class: "muted"}, `从 ${r.teams[0].name} 一方看；${r.teams[1].name} 一方约等于 1000 减它。`));
  }
  for (const opening of r.opening) {
    const mine = opening.side;
    const theirs = 1 - mine;
    const header = [`${r.teams[mine].name} \\ ${r.teams[theirs].name}`,
      ...r.teams[theirs].names.map((_, slot) => el("th", {}, nameOf(r, theirs, slot)))];
    const rows = opening.ratings.map((row, slot) => [
      nameOf(r, mine, slot),
      ...row.map((rating) => el("td", {class: `num rating ${rating > 500 ? "good" : rating < 500 ? "bad" : ""}`}, rating)),
    ]);
    parts.push(table(header, rows));
  }
  return parts;
}

function switchesTable(r) {
  if (r.switches.length === 0) return el("p", {}, "没有换人。");
  const rows = r.switches.map((s) => [
    el("td", {class: "num"}, s.turn),
    r.teams[s.side].name,
    el("span", {}, nameOf(r, s.side, s.from_slot), " → ", nameOf(r, s.side, s.to_slot)),
    s.kind_text,
    el("td", {class: "text"}, s.reason),
  ]);
  return table(["回合", "队伍", "换人", "类型", "原因"], rows);
}

function chargedTable(r) {
  if (r.charged.length === 0) return el("p", {}, "没有放大招。");
  const rows = r.charged.map((c) => [
    el("td", {class: "num"}, c.turn),
    nameOf(r, c.side, c.attacker_slot),
    c.move_id,
    nameOf(r, 1 - c.side, c.target_slot),
    c.shielded ? "开盾挡下" : `${c.damage} 伤害，剩 HP ${c.hp_after}`,
    el("td", {class: "text"}, c.shield_reason ?? "没有盾"),
  ]);
  return table(["回合", "出招", "大招", "挨打", "结果", "开不开盾的原因"], rows);
}

// ---- 时间线 ----

function timelineView(r) {
  const holder = el("div", {id: "timeline-table"});
  const controls = el("div", {class: "timeline-controls"},
    el("label", {}, el("input", {
      type: "checkbox",
      checked: state.showDecisions,
      onchange: (e) => {
        state.showDecisions = e.target.checked;
        holder.replaceChildren(timelineTable(r));
      },
    }), " 显示决定和原因"),
    el("span", {class: "muted"}, "　每回合一行（没有事件的回合不列）；最后一列是回合结束时双方在场那只的 HP、能量和全队剩下的盾。"),
  );
  holder.replaceChildren(timelineTable(r));
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

function timelineTable(r) {
  const rows = [];
  for (const entry of r.timeline) {
    const events = entry.events.filter((e) => state.showDecisions || e.type !== "decision");
    if (events.length === 0) continue;
    const cells = SIDES.map((side) => el("td", {class: `events-${side}`},
      events.filter((e) => e.side === side).map((e) => el("div", {class: eventClass(e)},
        el("span", {class: "who"}, r.teams[side].names[e.slot]), " ", e.text))));
    rows.push({attrs: {id: `turn-${entry.turn}`}, cells: [
      el("td", {class: "turn"}, `T${entry.turn}`),
      ...cells,
      entry.sides ? el("td", {}, SIDES.map((side) => sideState(r, side, entry.sides[side]))) : el("td", {}, ""),
    ]});
  }
  return table(["回合", r.teams[0].name, r.teams[1].name, "回合结束时"], rows, {class: "timeline"});
}

// ---- 战斗过程图和对位分段（4b） ----
//
// 图的数据（招式带、逐回合的 HP 和能量、对位分段）都由服务器算好（pogo_sim/battle_summary.py、web_api.chart_payload），
// 这里只把它们画成 SVG：上面两条是双方的招式带，下面两条是双方的 HP，共用一根横轴（回合）。

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

function chartView(r) {
  const legend = el("div", {class: "chart-legend"},
    SIDES.map((side) => el("span", {class: "legend-team"},
      el("span", {class: `name side-${side}`}, r.teams[side].name), "：",
      r.teams[side].names.map((name, slot) => el("span", {class: "legend-item"},
        el("span", {class: "swatch", style: `background: ${memberColor(side, slot)}`}), name)))),
  );
  const help = el("p", {class: "muted"},
    "招式带：小块是快招（宽度是招式的回合数），竖条是大招（空心是被开盾挡下，旁边写伤害），紫线是换人，✕ 是倒下。" +
    "HP：粗线是在场那只，细的淡线是后备，虚线是在场那只的能量（0–100）。鼠标移上去看这一回合的详情，点一下跳到下面时间线的那一行。");
  const holder = el("div", {class: "chart-holder", id: "chart-holder"});
  // 先放进页面再画：要知道可用的宽度
  requestAnimationFrame(() => drawChart(r, holder));
  return [legend, help, holder];
}

function drawChart(r, holder) {
  const chart = r.chart;
  const layout = chartLayout(chart.turns, holder.clientWidth || 1000);
  const {x, laneY, hpY, axisY} = layout;
  const {laneHeight, hpHeight, left} = CHART;
  const parts = [];

  // 背景和左边的标签
  for (const side of SIDES) {
    const team = r.teams[side].name;
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

function segmentsView(r) {
  const help = el("p", {class: "muted"},
    "在场的两只不变的一段时间算一段，任一方换人就开始新的一段。HP 和能量是这一段开始之前 → 最后一回合结束时；" +
    "大招后面是伤害，“挡下”是被对方开盾挡下；开盾是挡下对方大招的次数。鼠标移到一行上，图上会标出这一段。");
  const rows = r.segments.map((segment, i) => ({
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

function downloadReport() {
  const r = state.result;
  const safe = (text) => text.replace(/[^\w一-鿿-]+/g, "_");
  const blob = new Blob([r.report_markdown], {type: "text/markdown;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const link = el("a", {href: url, download: `3v3_${safe(r.teams[0].name)}_vs_${safe(r.teams[1].name)}.md`});
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---- 手动对战（4c） ----
//
// 自己操作一队，和另一队的 TeamPolicy 打（回合制：每个要你决定的地方停下来等你点）。
// 你到现在做的每个决定存在 state.manual.decisions 里；每点一次，就把整串决定发给服务器（/api/manual-battle），
// 服务器从第 1 回合重打到下一个要你决定的地方，返回局面、能选什么和伤害表（pogo_sim/manual.py、web_api.manual_battle）。
// 所以"撤销上一步"就是去掉最后一个决定。这里只负责显示和把你点的选项发回去。

const MANUAL_KEY = "pogo_sim.manual.v1";

function renderManualSideSelect() {
  const select = document.getElementById("manual-side");
  if (!select || !state.config) return;
  const current = select.value || "0";
  select.replaceChildren(...SIDES.map((side) => el("option", {value: String(side)}, state.config.team[side].name || `第 ${side} 方`)));
  select.value = current;
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

// ---- 启动 ----

/** 按 state.config 画设置和两队，并请服务器建每只的配置。 */
async function start() {
  state.builds = [[], []];
  renderSettings();
  await reloadCatalog();
  renderTeams();
  rebuildAll();
}

async function init() {
  document.getElementById("run").addEventListener("click", runBattle);
  document.getElementById("reset").addEventListener("click", resetToExample);
  document.getElementById("manual-start").addEventListener("click", startManual);
  document.getElementById("manual-resume").addEventListener("click", resumeManual);
  document.addEventListener("keydown", onManualKey);
  let resizeTimer;
  window.addEventListener("resize", () => {  // 窗口宽度变了，按新的宽度重画过程图
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const holder = document.getElementById("chart-holder");
      if (state.result && holder) drawChart(state.result, holder);
    }, 200);
  });
  try {
    state.options = await api("/api/options");
    state.config = normalizeConfig(loadSaved() ?? state.options.example);
    await start();
    updateResumeButton();
  } catch (e) {
    showError(`页面加载失败：${e.message}`);
  }
}

init();
