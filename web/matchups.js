"use strict";
// 1v1 九宫格页（第 4 步，4g）：每个测试对象对每个对手，0–2 盾对 0–2 盾各打一场 1v1，双方都用简单规则策略。
// 对手是手写的几只和 PvPoke 排名里的环境前 N（可以几组）。和命令行 tools.run_matchups 同一套配置
// （pogo_sim/matchups.py 开头）和计算。
//
// 这里只负责填表和显示：建配置、检查、对战、总表的数字、报告和 CSV 都在服务器
// （web_api 的 matchups、matchup_battle 等，见 docs/mechanics.md 14.9）。排序、对照表里选哪种盾数只是换个看法。
// 页面上的配置和九宫格配置文件写法一样；浏览器会记住上次填的（localStorage）。
// 共用的部分：一只宝可梦的编辑器在 editor.js，点一格看的那一场用 battle_view.js 画，队伍库的列表在 library.js。

const MATCHUPS_KEY = "pogo_sim.matchups.config.v1";
const GROUPS = {subject: "测试对象", opponent: "手写的对手"};
const POOL_IVS_DEFAULT = "rank1"; // 环境前 N 不写 ivs 时的 IV 规则（同 rankings.PoolSpec 的默认值），这时不发给服务器

const state = {
  options: null, // GET /api/options：联盟、赛季规则、覆盖文件
  matchupOptions: null, // GET /api/matchup-options：策略参数、环境前 N 的选项、九宫格的盾数、例子配置
  config: null, // 页面上的配置（normalizeConfig）；发给服务器前用 requestConfig 整理
  result: null, // POST /api/matchups 的结果
  resultConfig: null, // 算出 result 的那份配置：点一格看一场时发同一份，配置后来改了也对得上
  view: {subject: {}, compare: {}, sorts: {}}, // 每组环境前 N 看哪个测试对象、对照表比什么；每张表按哪一列排
  battle: null, // 正在看的一场：{cell, data}（data 是 POST /api/matchup-battle 的结果）
  battleNode: null,
  library: null, // GET /api/team-library 的结果；打开队伍库时重新读
  libraryOpen: null, // 哪一组下面打开了队伍库（"subject" / "opponent" / null）
  libraryFilter: {sameLeague: true, query: ""},
};

// ---- 小工具 ----

// 每只宝可梦在页面上的名字（editor.js 的 key）：按对象记，加、去掉、重画都不变
const memberKeys = new WeakMap();
let nextMemberKey = 0;

function keyOf(member) {
  if (!memberKeys.has(member)) memberKeys.set(member, `m${nextMemberKey++}`);
  return memberKeys.get(member);
}

function leagueName(cp) {
  return state.options.leagues.find((l) => l.cp === cp)?.name ?? `CP ${cp}`;
}

function moveName(id) {
  return editor.catalog?.moves[id]?.name ?? id;
}

/** 这个联盟有排名文件的 PvPoke 排名（小联盟没有）。 */
function availableRankings() {
  return state.matchupOptions.pool.available[state.config.league] ?? [];
}

function shieldCounts() {
  return state.matchupOptions.shield_counts;
}

// ---- 配置 ----

/** 例子配置、浏览器记住的配置或导入的配置整理成页面用的样子（缺的字段补上默认值）。 */
function normalizeConfig(raw) {
  const {options, matchupOptions} = state;
  return {
    description: raw.description ?? "",
    league: raw.league ?? 1500,
    season: raw.season ?? options.seasons[0].key,
    custom_files: (raw.custom_files ?? []).filter((name) => options.custom_files.some((f) => f.name === name)),
    policy: Object.fromEntries(matchupOptions.policy.map((p) => [p.key, raw.policy?.[p.key] ?? p.default])),
    subject: (raw.subject ?? []).map(normalizeMember),
    opponent: (raw.opponent ?? []).map(normalizeMember),
    opponent_pool: (raw.opponent_pool ?? []).map(normalizePool),
  };
}

function normalizePool(pool) {
  return {
    name: pool.name ?? "",
    rankings: pool.rankings ?? "mega",
    kind: pool.kind ?? "non_mega",
    top: pool.top ?? 50,
    ivs: pool.ivs ?? POOL_IVS_DEFAULT,
  };
}

/** 一组环境前 N 不写名字时服务器起的名字（同 rankings.parse_pool_spec），页面上当灰字提示。 */
function defaultPoolName(pool) {
  const kind = state.matchupOptions.pool.kinds.find((k) => k.key === pool.kind)?.name ?? pool.kind;
  return `${kind} 前 ${pool.top}（${pool.rankings} 排名）`;
}

function poolRequest(pool) {
  const out = {rankings: pool.rankings, kind: pool.kind, top: pool.top};
  if (pool.name) out.name = pool.name;
  if (pool.ivs !== POOL_IVS_DEFAULT) out.ivs = pool.ivs;
  return out;
}

/** 发给服务器的配置：同九宫格配置文件。没写的可选项不写；策略参数只写和默认值不同的。 */
function requestConfig() {
  const c = state.config;
  const out = {league: c.league, season: c.season, custom_files: [...c.custom_files]};
  if (c.description) out.description = c.description;
  const policy = {};
  for (const p of state.matchupOptions.policy) {
    if (c.policy[p.key] !== p.default) policy[p.key] = c.policy[p.key];
  }
  if (Object.keys(policy).length) out.policy = policy;
  out.subject = c.subject.map(memberRequest);
  if (c.opponent.length) out.opponent = c.opponent.map(memberRequest);
  if (c.opponent_pool.length) out.opponent_pool = c.opponent_pool.map(poolRequest);
  return out;
}

function buildSettings() {
  return {league: state.config.league, season: state.config.season, custom_files: state.config.custom_files};
}

function save() {
  localStorage.setItem(MATCHUPS_KEY, JSON.stringify(state.config));
}

function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(MATCHUPS_KEY));
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
      renderAll();
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
        renderAll();
        rebuildMembers();
      },
    }),
    ` 覆盖文件 ${file.name}`,
    file.description ? el("span", {class: "muted"}, `：${file.description}`) : null,
  ));
  document.getElementById("custom-files").replaceChildren(...files);
  renderPolicy();

  const description = document.getElementById("description");
  description.value = config.description;
  description.oninput = (e) => { config.description = e.target.value; configChanged(); };
}

/** 1v1 策略的参数（SimplePolicyConfig，双方相同），按服务器给的参数表画：下拉框、勾选框、数字。 */
function renderPolicy() {
  const policy = state.config.policy;
  const controls = state.matchupOptions.policy.map((p) => {
    const changed = (value) => { policy[p.key] = value; configChanged(); };
    if (p.type === "choice") {
      const choices = p.choices.map((c) => [c.key, c.key === p.default ? `${c.name}（默认）` : c.name]);
      return el("label", {}, `${p.name} `, select(choices, policy[p.key], changed));
    }
    if (p.type === "bool") {
      return el("label", {}, el("input", {
        type: "checkbox",
        checked: policy[p.key],
        onchange: (e) => changed(e.target.checked),
      }), ` ${p.name}`, el("span", {class: "muted"}, p.default ? "（默认开）" : "（默认关）"));
    }
    // 数字：现在只有开盾的 HP 线（0–1）
    return el("label", {}, `${p.name} `, el("input", {
      type: "number",
      step: 0.05,
      min: 0,
      max: 1,
      value: policy[p.key] ?? "",
      oninput: (e) => changed(e.target.value === "" ? null : Number(e.target.value)),
    }), el("span", {class: "muted"}, `（默认 ${p.default}）`));
  });
  document.getElementById("policy").replaceChildren(el("span", {class: "muted"}, "1v1 策略（双方相同）："), ...controls);
}

async function reloadCatalog() {
  await loadCatalog(state.config.league, state.config.custom_files);
}

// ---- 测试对象、手写的对手 ----

function renderAll() {
  renderGroup("subject");
  renderPools();
  renderGroup("opponent");
  renderLibrary();
}

function renderGroup(group) {
  const list = state.config[group];
  const empty = group === "subject" ? "还没有测试对象：点“加一只”或“从队伍库加”。" : "没有手写的对手。";
  document.getElementById(`${group}-list`).replaceChildren(...(list.length
    ? list.map((member, i) => memberEditor(keyOf(member), member, {
      role: `${i + 1}`,
      tools: el("button", {class: "small", onclick: () => removeMember(group, member)}, "去掉"),
      settings: buildSettings,
      onChange: configChanged,
    }))
    : [el("p", {class: "muted"}, empty)]));
}

function addMember(group) {
  const member = normalizeMember({});
  state.config[group].push(member);
  renderGroup(group);
  configChanged();
  scheduleBuild(keyOf(member));
  document.querySelector(`#member-${keyOf(member)} .species-picker input`)?.focus(); // 直接打开选宝可梦的下拉框
}

function removeMember(group, member) {
  forgetMember(keyOf(member));
  state.config[group] = state.config[group].filter((m) => m !== member);
  renderGroup(group);
  configChanged();
}

// ---- 环境前 N ----

function renderPools() {
  const available = availableRankings();
  const pools = state.config.opponent_pool;
  const parts = pools.map(poolEditor);
  if (!available.length) {
    parts.unshift(el("p", {class: "bad"},
      `${leagueName(state.config.league)}没有 PvPoke 排名（data/rankings/ 里没有这个联盟的文件），环境前 N 用不了，只能手写对手。`));
  } else if (!pools.length) {
    parts.push(el("p", {class: "muted"}, "没有环境前 N。"));
  }
  document.getElementById("pool-list").replaceChildren(...parts);
  document.getElementById("add-pool").disabled = !available.length;
}

function poolEditor(pool, i) {
  const options = state.matchupOptions.pool;
  const available = availableRankings();
  const update = (key, value) => {
    pool[key] = value;
    configChanged();
    renderPools(); // 名字的灰字提示跟着变
  };
  return el("div", {class: "pool-row"},
    el("span", {class: "role"}, `${i + 1}`),
    el("label", {}, "名字 ", el("input", {
      class: "pool-name",
      value: pool.name,
      placeholder: defaultPoolName(pool),
      oninput: (e) => { pool.name = e.target.value; configChanged(); },
    })),
    el("label", {}, "排名 ", select(
      options.rankings.map((r) => [r.key, `${r.key}：${r.name}${available.includes(r.key) ? "" : "（这个联盟没有）"}`]),
      pool.rankings,
      (value) => update("rankings", value),
    )),
    select(options.kinds.map((k) => [k.key, k.name]), pool.kind, (value) => update("kind", value)),
    el("label", {}, "前 ", el("input", {
      type: "number",
      class: "top-n",
      min: 1,
      step: 1,
      value: pool.top ?? "",
      onchange: (e) => update("top", e.target.value === "" ? null : Number(e.target.value)),
    }), " 只"),
    el("label", {}, "IV ", select(options.ivs.map((v) => [v.key, v.name]), pool.ivs, (value) => update("ivs", value))),
    el("button", {class: "small", onclick: () => removePool(pool)}, "去掉"),
  );
}

function addPool() {
  const available = availableRankings();
  state.config.opponent_pool.push(normalizePool({rankings: available.includes("mega") ? "mega" : available[0]}));
  configChanged();
  renderPools();
}

function removePool(pool) {
  state.config.opponent_pool = state.config.opponent_pool.filter((p) => p !== pool);
  configChanged();
  renderPools();
}

// ---- 从队伍库加（4f 的队伍库，一队 3 只） ----

async function toggleLibrary(group) {
  state.libraryOpen = state.libraryOpen === group ? null : group;
  renderLibrary();
  if (state.libraryOpen === null) return;
  state.library = null;
  renderLibrary();
  try {
    state.library = await api("/api/team-library");
  } catch (e) {
    showError(e.message);
  }
  renderLibrary();
}

function renderLibrary() {
  for (const group of Object.keys(GROUPS)) {
    const open = state.libraryOpen === group;
    const panel = document.getElementById(`library-panel-${group}`);
    document.getElementById(`library-${group}`).textContent = open ? "收起队伍库" : "从队伍库加";
    panel.hidden = !open;
    if (!open) continue;
    panel.replaceChildren(...libraryPanel(state.library, {
      league: state.config.league,
      leagueName: leagueName(state.config.league),
      filter: state.libraryFilter,
      buttons: (entry) => el("button", {onclick: () => addFromLibrary(group, entry)},
        `${entry.team.member.length} 只都加进${GROUPS[group]}`),
    }));
  }
}

/** 把库里一队的每只加到测试对象（或手写的对手）后面：用到的覆盖文件自动勾上；联盟不同只提示。 */
async function addFromLibrary(group, entry) {
  const {customFiles, added, notes} = libraryLoadPlan(entry, state.config.custom_files,
    state.options.custom_files.map((f) => f.name), state.config.league, leagueName(state.config.league));
  const members = entry.team.member.map(normalizeMember);
  state.config.custom_files = customFiles;
  state.config[group].push(...members);
  configChanged();
  showError("");
  if (added.length) { // 覆盖文件变了：重新读宝可梦列表，全部重画、重新建配置
    renderSettings();
    await reloadCatalog();
    renderAll();
    rebuildMembers();
  } else {
    renderGroup(group);
    for (const member of members) scheduleBuild(keyOf(member));
  }
  setStatus(`已把 ${entry.name}（teams/${entry.file}）的 ${members.length} 只加进${GROUPS[group]}` +
    `${notes.length ? `。${notes.join("；")}` : ""}`);
}

// ---- 跑九宫格 ----

async function runMatchups() {
  const button = document.getElementById("run");
  button.disabled = true;
  showError("");
  setStatus("正在跑……（环境前 N 第一次要建配置，可能要几秒）");
  try {
    const config = requestConfig();
    state.result = await api("/api/matchups", config);
    state.resultConfig = structuredClone(config);
    state.battle = null;
    state.battleNode = null;
    renderResult();
    setStatus(`跑完了：${state.result.battles} 场，${state.result.seconds} 秒`);
    document.getElementById("result").scrollIntoView({behavior: "smooth"});
  } catch (e) {
    showError(e.message);
    setStatus("");
  } finally {
    button.disabled = false;
  }
}

function resetToExample() {
  if (!confirm("恢复成例子？现在填的设置、测试对象和对手会被覆盖。")) return;
  state.config = normalizeConfig(state.matchupOptions.example);
  save();
  start().catch((e) => showError(e.message));
}

// ---- 结果：上色的格子、可以排序的表 ----

/** 评分的底色：0 红 → 500 白 → 1000 绿，连续渐变。 */
function ratingColor(rating) {
  const t = Math.max(-1, Math.min(1, (rating - 500) / 500));
  return t >= 0 ? `rgba(22, 163, 74, ${(0.55 * t).toFixed(3)})` : `rgba(220, 38, 38, ${(-0.55 * t).toFixed(3)})`;
}

/** 一个评分格子：按评分上色，赢的加粗。给了 cell（哪一场）就可以点，点了在下面看这一场。 */
function ratingCell(rating, cell) {
  const attrs = {
    class: `num rating-cell${rating > state.matchupOptions.win_rating ? " win" : ""}`,
    style: `background: ${ratingColor(rating)}`,
  };
  if (cell) {
    attrs.class += " clickable";
    attrs["data-cell"] = cellId(cell);
    attrs.title = "点一下看这一场";
    attrs.onclick = () => showBattle(cell);
  }
  return el("td", attrs, Math.round(rating));
}

/** 一场在九宫格里的位置：第几个测试对象、第几组环境前 N（手写的对手为 null）、第几个对手、双方的盾数。 */
function cellId(cell) {
  return `${cell.pool ?? "h"}:${cell.subject}:${cell.opponent}:${cell.shields.join("-")}`;
}

function compareValues(a, b) {
  return typeof a === "string" ? a.localeCompare(b) : a - b;
}

/** 可以点表头排序的表（点表头只重画这一张）。columns：[{key, title, tip, value(row)（排序用；没有就不能排）,
 *  asc（第一次点时从小到大）, num（数字列，表头靠右）, cell(row)}]。排序记在 state.view.sorts[sortKey]，first 是一开始的排序 {key, desc}。 */
function sortableTable(sortKey, columns, rows, first) {
  const holder = el("div");
  const draw = () => {
    const sort = state.view.sorts[sortKey] ?? first;
    const column = columns.find((c) => c.key === sort.key);
    const sorted = [...rows];
    if (column?.value) sorted.sort((a, b) => compareValues(column.value(a), column.value(b)) * (sort.desc ? -1 : 1));
    const header = columns.map((c) => el("th", {
      class: [c.value ? "sortable" : "", c.num ? "num" : ""].join(" ").trim() || undefined,
      title: c.tip,
      onclick: c.value ? () => {
        state.view.sorts[sortKey] = {key: c.key, desc: sort.key === c.key ? !sort.desc : !c.asc};
        draw();
      } : undefined,
    }, c.title, c.key === sort.key ? (sort.desc ? " ↓" : " ↑") : ""));
    holder.replaceChildren(table(header, sorted.map((row) => columns.map((c) => c.cell(row))), {class: "matchup-table"}));
    markSelected();
  };
  draw();
  return holder;
}

function pokemonCell(member) {
  return el("td", {}, typeDots(member.types), " ", member.marked);
}

function movesText(member) {
  return `${moveName(member.fast)} / ${member.charged.map(moveName).join(", ")}`;
}

// ---- 结果 ----

function renderResult() {
  const r = state.result;
  const section = document.getElementById("result");
  section.hidden = false;
  section.replaceChildren(
    resultHead(r),
    ...(r.opponents.length ? [handwrittenCard(r)] : []),
    ...r.pools.map((pool, p) => poolCard(r, pool, p)),
  );
}

function resultHead(r) {
  const win = state.matchupOptions.win_rating;
  const outside = [...r.subjects, ...r.opponents].some((m) => m.outside_movepool.length);
  return el("div", {class: "card"},
    el("div", {class: "result-head"},
      el("h2", {}, "结果"),
      el("span", {class: "library-buttons"},
        el("button", {onclick: downloadReport}, "下载 Markdown 报告"),
        el("button", {onclick: downloadCsv, title: "全部评分，一场一行（同命令行的 --csv）"}, "下载 CSV"),
      ),
    ),
    el("p", {class: "stale", id: "stale-note", hidden: true},
      "配置改过了：下面还是上一次的结果，再点一次“跑九宫格”更新（点格子看的也是上一次配置里的那一场）。"),
    el("p", {}, `${r.settings.league_name}；赛季规则：${r.settings.season}；一共 ${r.battles} 场，${r.seconds} 秒` +
      "（含建配置：环境前 N 第一次要建，之后用服务器里的缓存）。"),
    r.settings.custom_log.map((line) => el("p", {class: "muted"}, `覆盖文件：${line}`)),
    el("p", {class: "muted"},
      `评分是 PvPoke 的对战评分，从测试对象一方看：500 × 对手损失的 HP 比例 + 500 × 自己剩余的 HP 比例。大于 ${win} 算赢，加粗；` +
      "底色从 0 红到 500 白到 1000 绿。点任何一格，在那张表下面看这一场的过程图和时间线。"),
    table(["测试对象", "宝可梦", "CP", "等级", "IV", "配招"], r.subjects.map((m) => [
      m.marked,
      el("span", {}, typeDots(m.types), " ", m.species_name),
      el("td", {class: "num"}, m.cp),
      el("td", {class: "num"}, m.level),
      m.ivs.join("/"),
      movesText(m),
    ])),
    outside ? el("p", {class: "muted"}, "* 带了招式池外的招式（假设）。") : null,
  );
}

/** 手写的对手：总表（行是测试对象，列是对手），以及每一对的九宫格。 */
function handwrittenCard(r) {
  const summary = table(
    ["测试对象 \\ 对手", ...r.opponents.map((o) => o.marked)],
    r.subjects.map((s, i) => [s.marked, ...r.opponents.map((_, j) => {
      const grid = r.grids[i][j];
      return el("td", {class: "num rating-cell", style: `background: ${ratingColor(grid.average)}`},
        `赢 ${grid.wins}/9 · 平均 ${Math.round(grid.average)}`);
    })]),
  );
  const grids = r.subjects.flatMap((s, i) => r.opponents.map((o, j) =>
    gridTable(`${s.marked} 对 ${o.marked}`, r.grids[i][j], {subject: i, pool: null, opponent: j})));
  return el("div", {class: "card"},
    el("h2", {}, "手写的对手"),
    el("p", {class: "muted"}, "总表每格是九场里赢了几场和九场的平均评分（底色按平均评分）。下面每一对一个九宫格：行是自己的盾数，列是对手的盾数。"),
    summary,
    el("div", {class: "grids"}, grids),
    el("details", {class: "opponents-details"}, el("summary", {}, "对手的配置"),
      table(["对手", "宝可梦", "CP", "等级", "IV", "配招"], r.opponents.map((m) => [
        m.marked, el("span", {}, typeDots(m.types), " ", m.species_name), el("td", {class: "num"}, m.cp),
        el("td", {class: "num"}, m.level), m.ivs.join("/"), movesText(m),
      ]))),
  );
}

/** 一个九宫格：行是自己的盾数，列是对手的盾数，每格可以点。 */
function gridTable(title, grid, cell) {
  const shields = shieldCounts();
  const header = [title, ...shields.map((b) => el("th", {class: "num"}, `对手 ${b} 盾`))];
  const rows = shields.map((a) => [
    `自己 ${a} 盾`,
    ...shields.map((b) => ratingCell(grid.ratings[a][b], {...cell, shields: [a, b]})),
  ]);
  return el("div", {class: "grid-box"},
    table(header, rows, {class: "matchup-grid"}),
    el("div", {class: "muted"}, `赢 ${grid.wins}/9，平均 ${Math.round(grid.average)}`));
}

/** 一组环境前 N：来源、总表、对照（两个以上测试对象时）、一个测试对象对每一只的九宫格、对手的配置。 */
function poolCard(r, pool, p) {
  const shields = shieldCounts();
  const n = pool.members.length;
  const summary = table(
    ["测试对象", ...shields.map((s) => el("th", {class: "num"}, `${s} 对 ${s} 盾`)), el("th", {class: "num"}, "九种盾数"),
      el("th", {class: "num"}, "平均评分")],
    r.subjects.map((s, i) => {
      const sum = pool.summary[i];
      return [
        s.marked,
        ...sum.same_shield_wins.map((wins) => el("td", {class: "num"}, `赢 ${wins} / ${n}`)),
        el("td", {class: "num"}, `赢 ${sum.wins} / ${9 * n}`),
        ratingCell(sum.average),
      ];
    }),
  );
  return el("div", {class: "card"},
    el("h2", {}, `环境前 N：${pool.name}`),
    el("p", {class: "muted"}, `${pool.description}。名次是 PvPoke 排名文件里的名次，配招来自 PvPoke 的推荐。`),
    pool.skipped.length ? el("p", {class: "muted"}, `前 N 只里建不了配置、跳过的：` +
      pool.skipped.map((s) => `${s.rank} ${s.name}（${s.reason}）`).join("；")) : null,
    el("h3", {}, "总表"),
    el("p", {class: "muted"}, "双方同样盾数时赢了几只；九种盾数（0–2 盾对 0–2 盾）一共赢了几格；全部评分的平均。"),
    summary,
    r.subjects.length > 1 ? compareView(r, pool, p) : null,
    subjectView(r, pool, p),
    el("details", {class: "opponents-details"}, el("summary", {}, "对手的配置"),
      table(["名次", "对手", "综合分", "CP", "等级", "IV", "配招"], pool.members.map((m) => [
        el("td", {class: "num"}, m.rank), pokemonCell(m), el("td", {class: "num"}, m.score.toFixed(1)),
        el("td", {class: "num"}, m.cp), el("td", {class: "num"}, m.level), m.ivs.join("/"), movesText(m),
      ]))),
  );
}

/** 对照：一行一个对手，一列一个测试对象；比哪种盾数（或九格平均、九格赢了几格）可以选。两个测试对象时多一列差值。 */
function compareView(r, pool, p) {
  const holder = el("div");
  const metrics = [
    ["average", "九格平均"],
    ["wins", "九格赢了几格"],
    ...shieldCounts().flatMap((a) => shieldCounts().map((b) => [`${a}-${b}`, `自己 ${a} 盾 对 对手 ${b} 盾`])),
  ];
  const draw = () => {
    const metric = state.view.compare[p] ?? "average";
    const shields = metric.includes("-") ? metric.split("-").map(Number) : null;
    const value = (grid) => (metric === "average" ? grid.average : metric === "wins" ? grid.wins : grid.ratings[shields[0]][shields[1]]);
    const valueCell = (grid, cell) => (metric === "wins" ? el("td", {class: "num"}, `${grid.wins}/9`)
      : ratingCell(value(grid), shields ? {...cell, shields} : undefined));
    const rows = pool.members.map((member, j) => ({member, j, grids: r.subjects.map((_, i) => pool.grids[i][j])}));
    const columns = [
      {key: "rank", title: "名次", asc: true, num: true, value: (row) => row.member.rank, cell: (row) => el("td", {class: "num"}, row.member.rank)},
      {key: "name", title: "对手", asc: true, value: (row) => row.member.marked, cell: (row) => pokemonCell(row.member)},
      ...r.subjects.map((s, i) => ({
        key: `s${i}`, title: s.marked, num: true, value: (row) => value(row.grids[i]),
        cell: (row) => valueCell(row.grids[i], {subject: i, pool: p, opponent: row.j}),
      })),
    ];
    if (r.subjects.length === 2) {
      const diff = (row) => value(row.grids[0]) - value(row.grids[1]);
      columns.push({
        key: "diff", title: "差值", num: true, tip: `${r.subjects[0].marked} 减 ${r.subjects[1].marked}`, value: diff,
        cell: (row) => {
          const d = diff(row);
          const text = metric === "wins" ? String(d) : String(Math.round(d));
          return el("td", {class: `num ${d > 0 ? "good" : d < 0 ? "bad" : ""}`}, d > 0 ? `+${text}` : text);
        },
      });
    }
    holder.replaceChildren(
      el("div", {class: "view-controls"},
        el("label", {}, "比 ", select(metrics, metric, (v) => { state.view.compare[p] = v; draw(); }))),
      sortableTable(`compare-${p}`, columns, rows, {key: "rank", desc: false}),
    );
  };
  draw();
  return [el("h3", {}, "对照"), holder];
}

/** 一个测试对象对这组每一只的九宫格：一行一个对手，九格按"自己的盾数 对 对手的盾数"排，可以点表头排序。 */
function subjectView(r, pool, p) {
  const holder = el("div");
  const shields = shieldCounts();
  const pairs = shields.flatMap((a) => shields.map((b) => [a, b]));
  const draw = () => {
    const i = Math.min(state.view.subject[p] ?? 0, r.subjects.length - 1);
    const rows = pool.members.map((member, j) => ({member, j, grid: pool.grids[i][j]}));
    const columns = [
      {key: "rank", title: "名次", asc: true, num: true, value: (row) => row.member.rank, cell: (row) => el("td", {class: "num"}, row.member.rank)},
      {key: "name", title: "对手", asc: true, value: (row) => row.member.marked, cell: (row) => pokemonCell(row.member)},
      {key: "score", title: "综合分", num: true, tip: "PvPoke 的综合分（0–100）", value: (row) => row.member.score,
        cell: (row) => el("td", {class: "num"}, row.member.score.toFixed(1))},
      ...pairs.map(([a, b]) => ({
        key: `${a}-${b}`, title: `${a} 对 ${b}`, num: true, tip: `自己 ${a} 盾，对手 ${b} 盾`, value: (row) => row.grid.ratings[a][b],
        cell: (row) => ratingCell(row.grid.ratings[a][b], {subject: i, pool: p, opponent: row.j, shields: [a, b]}),
      })),
      {key: "wins", title: "赢", num: true, tip: "九格里赢了几格", value: (row) => row.grid.wins, cell: (row) => el("td", {class: "num"}, `${row.grid.wins}/9`)},
      {key: "average", title: "平均", num: true, tip: "九格的平均评分", value: (row) => row.grid.average, cell: (row) => ratingCell(row.grid.average)},
    ];
    const chooser = r.subjects.length > 1
      ? el("label", {}, "测试对象 ", select(r.subjects.map((s, k) => [k, s.marked]), i, (v) => { state.view.subject[p] = Number(v); draw(); }))
      : el("span", {}, r.subjects[0].marked);
    holder.replaceChildren(
      el("div", {class: "view-controls"}, chooser,
        el("span", {class: "muted"}, "一行是对一个对手的九宫格，列名是“自己的盾数 对 对手的盾数”。")),
      sortableTable(`subject-${p}`, columns, rows, {key: "rank", desc: false}),
    );
  };
  draw();
  return [el("h3", {}, "每一只的九宫格"), holder];
}

// ---- 点一格看这一场 ----

async function showBattle(cell) {
  showError("");
  setStatus("正在打这一场……");
  let data;
  try {
    data = await api("/api/matchup-battle", {config: state.resultConfig, ...cell});
  } catch (e) {
    showError(e.message);
    setStatus("");
    return;
  }
  state.battle = {cell, data};
  state.battleNode?.remove();
  state.battleNode = battlePanel(cell, data);
  // 放在点的那一格所在的卡片下面
  const anchor = document.querySelector(`[data-cell="${cellId(cell)}"]`)?.closest(".card");
  (anchor ?? document.getElementById("result").lastElementChild).after(state.battleNode);
  markSelected();
  state.battleNode.scrollIntoView({behavior: "smooth", block: "start"});
  setStatus(`${data.teams[0].name} 对 ${data.teams[1].name}：${data.outcome}`);
}

function battlePanel(cell, data) {
  const [a, b] = cell.shields;
  const head = el("div", {class: "card"},
    el("div", {class: "result-head"},
      el("h2", {}, `这一场：${data.teams[0].name} 对 ${data.teams[1].name}（自己 ${a} 盾，对手 ${b} 盾）`),
      el("span", {class: "library-buttons"},
        el("button", {onclick: () => backToCell(cell)}, "回到那一格"),
        el("button", {onclick: closeBattle}, "关掉"),
      ),
    ),
    el("p", {class: "outcome"}, data.outcome),
    data.teams.map((team, side) => {
      const m = team.members[0];
      return el("div", {class: `team-line side-${side}`},
        el("span", {class: "name"}, `${team.name}：`),
        `${m.species_name}，CP ${m.cp}，${m.level} 级，IV ${m.ivs.join("/")}，${movesText(m)}`);
    }),
    el("p", {class: "muted"}, "双方都用简单规则策略；时间线里的“决定”是策略给的原因。"),
  );
  return el("div", {class: "battle-view", id: "battle"},
    head, card("战斗过程", ...chartView(data, {sideLabels: ["测试对象", "对手"]})), card("时间线", ...timelineView(data)));
}

function closeBattle() {
  const cell = state.battle?.cell;
  state.battle = null;
  state.battleNode?.remove();
  state.battleNode = null;
  markSelected();
  if (cell) backToCell(cell);
}

/** 滚回点的那一格（同一场可能在几张表里，取第一个）。 */
function backToCell(cell) {
  const td = document.querySelector(`[data-cell="${cellId(cell)}"]`);
  if (!td) return;
  td.scrollIntoView({behavior: "smooth", block: "center"});
  td.classList.add("flash");
  setTimeout(() => td.classList.remove("flash"), 1500);
}

/** 正在看的那一场的格子加框（几张表里都有的都加）。 */
function markSelected() {
  const id = state.battle ? cellId(state.battle.cell) : null;
  for (const td of document.querySelectorAll("td[data-cell]")) td.classList.toggle("selected", td.dataset.cell === id);
}

// ---- 下载、导入导出 ----

/** 下载的文件名：1v1_第一个测试对象[_and_N_more]（同 web_api.export_matchups）。 */
function fileStem(labels) {
  const safe = labels[0].replace(/[^\w一-鿿.-]+/g, "_").replace(/^[._]+|[._]+$/g, "");
  return `1v1_${safe}${labels.length > 1 ? `_and_${labels.length - 1}_more` : ""}`;
}

function downloadReport() {
  const r = state.result;
  downloadText(`${fileStem(r.subjects.map((s) => s.label))}.md`, r.report_markdown, "text/markdown");
}

function downloadCsv() {
  const r = state.result;
  downloadText(`${fileStem(r.subjects.map((s) => s.label))}.csv`, r.csv, "text/csv");
}

async function exportConfig() {
  showError("");
  try {
    const data = await api("/api/export-matchups", requestConfig());
    downloadText(data.filename, data.text, "application/toml");
    setStatus(`已导出 ${data.filename}`);
  } catch (e) {
    showError(e.message);
  }
}

async function importConfig(file) {
  showError("");
  try {
    const data = await api("/api/import-matchups", {text: await file.text(), name: file.name});
    if (!confirm(`导入 ${file.name}？现在填的设置、测试对象和对手会被换掉。`)) return;
    state.config = normalizeConfig(data.config);
    state.libraryOpen = null;
    save();
    await start();
    setStatus(`已导入 ${file.name}`);
  } catch (e) {
    showError(e.message);
  }
}

// ---- 启动 ----

/** 按 state.config 画设置、测试对象和对手，并请服务器建每只的配置。 */
async function start() {
  forgetMembers();
  renderSettings();
  await reloadCatalog();
  renderAll();
  rebuildMembers();
}

async function init() {
  document.getElementById("run").addEventListener("click", runMatchups);
  document.getElementById("reset").addEventListener("click", resetToExample);
  document.getElementById("add-subject").addEventListener("click", () => addMember("subject"));
  document.getElementById("add-opponent").addEventListener("click", () => addMember("opponent"));
  document.getElementById("add-pool").addEventListener("click", addPool);
  document.getElementById("library-subject").addEventListener("click", () => toggleLibrary("subject"));
  document.getElementById("library-opponent").addEventListener("click", () => toggleLibrary("opponent"));
  document.getElementById("export-config").addEventListener("click", exportConfig);
  document.getElementById("import-config").addEventListener("click", () => document.getElementById("import-file").click());
  document.getElementById("import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // 同一个文件再选一次也能触发
    if (file) importConfig(file);
  });
  try {
    [state.options, state.matchupOptions] = await Promise.all([api("/api/options"), api("/api/matchup-options")]);
    state.config = normalizeConfig(loadSaved() ?? state.matchupOptions.example);
    await start();
  } catch (e) {
    showError(`页面加载失败：${e.message}`);
  }
}

init();
