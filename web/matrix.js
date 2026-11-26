"use strict";
// 队伍对队伍页（第 4 步，4h）：我方一队或几队，对很多队对手各打一场 3v3。对手是手写的几队，以及从 PvPoke 排名的
// 环境前 N 随机抽的。和命令行 tools.run_team_matrix 同一套配置（pogo_sim/team_matrix.py 开头）和计算。
//
// 这里只负责填表和显示：建配置、抽样、对战、总表的数字、报告和 CSV 都在服务器（web_api 的 team_matrix_stream、
// matrix_battle 等，见 docs/mechanics.md 14.10）。场数多时要打十几秒，所以服务器边打边发（NDJSON，一行一项），
// 这里一边收一边填表；点"停止"就断开请求，服务器不再往下打。排序、看哪一队只是换个看法。
// 页面上的配置和队伍对队伍配置文件写法一样，只是每队只能改盾数和主动换不换人；浏览器会记住上次填的（localStorage）。
// 共用的部分：一队的编辑器在 editor.js，点一场看的 3v3 用 battle_view.js 画，队伍库在 library.js。

const MATRIX_KEY = "pogo_sim.team_matrix.config.v1";
const GROUPS = {team: "我方", opponent_team: "对手"}; // 两组手写的队伍；新加的一队按这个起名（"我方 2"、"对手 1"……）
// [opponent_sample] 里不写时的值（同 team_matrix 读配置时的默认值）。打开"随机抽"时先填的是服务器给的 sample_defaults。
const SAMPLE_FILE_DEFAULTS = {mega_top: 0, ivs: "rank1"};
const OUTCOME_ORDER = {赢: 2, 平: 1, 输: 0}; // 按结果排序用

const state = {
  options: null, // GET /api/options：联盟、赛季规则、覆盖文件、每队几只、盾数、主动换人
  matrixOptions: null, // GET /api/matrix-options：随机抽能选什么、打开随机抽时先填的值、例子配置
  config: null, // 页面上的配置（normalizeConfig）；发给服务器前用 requestConfig 整理
  run: null, // 正在跑：{controller}（AbortController，点"停止"时断开请求）
  // 跑的结果：start 事件的内容（settings、teams、opponents、sample、total），加上 results[我方][对手]（打完的一场，
  // 没打完的为 null）、done（打完几场）、status（"running" / "done" / "stopped" / "error"），打完以后还有
  // seconds、summary、report_markdown、csv（done 事件）
  result: null,
  resultConfig: null, // 算出 result 的那份配置：点一场看时发同一份，配置后来改了也对得上
  redraws: [], // 边打边显示时要重画的表（每收到一批结果调一次）
  view: {team: 0, sorts: {}}, // "每一场"看我方哪一队；每张表按哪一列排
  battle: null, // 正在看的一场：{team, opponent, from（点的那张表所在卡片的 id）, data（POST /api/matrix-battle 的结果）}
  battleNode: null,
  library: null, // GET /api/team-library 的结果；打开队伍库时重新读
  libraryOpen: null, // 哪一队下面打开了队伍库（队伍对象）
  libraryFilter: {sameLeague: true, query: ""},
};

// ---- 小工具 ----

// 每一队在页面上的名字（editor.js 里每只的 key 是 `${队的名字}-${第几只}`）：按对象记，加、去掉、重画都不变
const teamKeys = new WeakMap();
let nextTeamKey = 0;

function keyOf(team) {
  if (!teamKeys.has(team)) teamKeys.set(team, `t${nextTeamKey++}`);
  return teamKeys.get(team);
}

function memberKeys(team) {
  return team.member.map((_, slot) => `${keyOf(team)}-${slot}`);
}

function leagueName(cp) {
  return state.options.leagues.find((l) => l.cp === cp)?.name ?? `CP ${cp}`;
}

/** 这个联盟有排名文件的 PvPoke 排名（小联盟没有）。 */
function availableRankings() {
  return state.matrixOptions.pool.available[state.config.league] ?? [];
}

function groupOf(team) {
  return state.config.team.includes(team) ? "team" : "opponent_team";
}

// ---- 配置 ----

/** 例子配置、浏览器记住的配置或导入的配置整理成页面用的样子（缺的字段补上默认值）。 */
function normalizeConfig(raw) {
  const options = state.options;
  const config = {
    description: raw.description ?? "",
    league: raw.league ?? 1500,
    season: raw.season ?? options.seasons[0].key,
    custom_files: (raw.custom_files ?? []).filter((name) => options.custom_files.some((f) => f.name === name)),
    team: [],
    opponent_team: [],
    sample_on: raw.sample_on ?? Boolean(raw.opponent_sample), // 浏览器记住的配置里关掉了也留着随机抽的设置
    opponent_sample: normalizeSample(raw.opponent_sample),
  };
  for (const group of Object.keys(GROUPS)) {
    for (const team of raw[group] ?? []) config[group].push(normalizeMatrixTeam(team, newTeamName(config, group)));
  }
  return config;
}

/** 一队（editor.js 的 normalizeTeam）。name：没写队名时用的名字。 */
function normalizeMatrixTeam(team, name) {
  const options = state.options;
  return normalizeTeam(team, {name, size: options.team_size, shields: options.max_shields, switching: options.switching[0].key});
}

/** 新加的一队的名字：还没用过的"我方 N" / "对手 N"（随机抽的队伍叫"抽样 N"，不会撞）。 */
function newTeamName(config, group) {
  const used = new Set([...config.team, ...config.opponent_team].map((t) => t.name));
  for (let n = 1; ; n += 1) {
    const name = `${GROUPS[group]} ${n}`;
    if (!used.has(name)) return name;
  }
}

/** [opponent_sample] 整理成页面用的样子。没有（还没打开过随机抽）时用服务器给的 sample_defaults。 */
function normalizeSample(sample) {
  const fresh = state.matrixOptions.sample_defaults;
  const s = sample ? {...fresh, ...SAMPLE_FILE_DEFAULTS, shields: state.options.max_shields, ...sample} : fresh;
  return {
    rankings: s.rankings,
    top: s.top,
    mega_top: s.mega_top,
    count: s.count,
    seed: s.seed,
    ivs: s.ivs,
    shields: s.shields,
    policy: {switching: sample?.policy?.switching ?? state.options.switching[0].key},
  };
}

function sampleRequest(s) {
  const out = {rankings: s.rankings, top: s.top, mega_top: s.mega_top, count: s.count, seed: s.seed};
  if (s.ivs !== SAMPLE_FILE_DEFAULTS.ivs) out.ivs = s.ivs;
  out.shields = s.shields;
  out.policy = {switching: s.policy.switching};
  return out;
}

/** 发给服务器的配置：同队伍对队伍配置文件。没有手写的对手、没打开随机抽时不写那一项。 */
function requestConfig() {
  const c = state.config;
  const out = {league: c.league, season: c.season, custom_files: [...c.custom_files]};
  if (c.description) out.description = c.description;
  out.team = c.team.map(teamRequest);
  if (c.opponent_team.length) out.opponent_team = c.opponent_team.map(teamRequest);
  if (c.sample_on) out.opponent_sample = sampleRequest(c.opponent_sample);
  return out;
}

function buildSettings() {
  return {league: state.config.league, season: state.config.season, custom_files: state.config.custom_files};
}

function save() {
  localStorage.setItem(MATRIX_KEY, JSON.stringify(state.config));
}

function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(MATRIX_KEY));
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

  const description = document.getElementById("description");
  description.value = config.description;
  description.oninput = (e) => { config.description = e.target.value; configChanged(); };
}

async function reloadCatalog() {
  await loadCatalog(state.config.league, state.config.custom_files);
}

// ---- 我方队伍、手写的对手 ----

function renderAll() {
  for (const group of Object.keys(GROUPS)) renderGroup(group);
  renderSample();
}

function renderGroup(group) {
  const teams = state.config[group];
  const empty = group === "team" ? "还没有我方队伍：点“加一队”。" : "没有手写的对手。";
  document.getElementById(`${group}-list`).replaceChildren(...(teams.length
    ? teams.map((team) => renderTeam(group, team))
    : [el("p", {class: "muted"}, empty)]));
}

function renderTeam(group, team) {
  const open = state.libraryOpen === team;
  const lastOfOurs = group === "team" && state.config.team.length === 1;
  return teamEditor(team, {
    prefix: keyOf(team),
    class: group === "team" ? "side-0" : "side-1",
    maxShields: state.options.max_shields,
    switching: state.options.switching,
    settings: buildSettings,
    onChange: configChanged,
    nameTitle: "队名（所有队伍不能同名；随机抽的队伍叫“抽样 1”……）",
    tools: el("span", {class: "library-buttons"},
      el("button", {onclick: () => saveLibraryTeam(team), title: "存进仓库的 teams/（一队一个文件，文件名按队名）"}, "存进队伍库"),
      el("button", {onclick: () => toggleLibrary(team)}, open ? "收起队伍库" : "从队伍库载入"),
      el("button", {
        onclick: () => removeTeam(group, team),
        disabled: lastOfOurs,
        title: lastOfOurs ? "我方至少要有一队" : "从页面上去掉这一队（不动队伍库）",
      }, "去掉"),
    ),
    panel: open ? el("div", {class: "library", id: `library-${keyOf(team)}`}, libraryContent(team)) : null,
  });
}

function addTeam(group) {
  const team = normalizeMatrixTeam({}, newTeamName(state.config, group));
  state.config[group].push(team);
  configChanged();
  renderGroup(group);
  for (const key of memberKeys(team)) scheduleBuild(key);
  document.querySelector(`#member-${keyOf(team)}-0 .species-picker input`)?.focus(); // 直接打开选首发的下拉框
}

function removeTeam(group, team) {
  const filled = team.member.some((m) => m.species);
  if (filled && !confirm(`从页面上去掉 ${team.name}？（不动队伍库；存过的还在 teams/ 里）`)) return;
  for (const key of memberKeys(team)) forgetMember(key);
  state.config[group] = state.config[group].filter((t) => t !== team);
  if (state.libraryOpen === team) state.libraryOpen = null;
  configChanged();
  renderGroup(group);
}

// ---- 随机抽 ----

function renderSample() {
  const c = state.config;
  const available = availableRankings();
  const toggle = document.getElementById("sample-on");
  toggle.checked = c.sample_on;
  toggle.disabled = !available.length && !c.sample_on;
  const holder = document.getElementById("sample");
  const parts = [];
  if (!available.length) {
    parts.push(el("p", {class: "bad"},
      `${leagueName(c.league)}没有 PvPoke 排名（data/rankings/ 里没有这个联盟的文件），随机抽用不了，只能手写对手。`));
  }
  if (!c.sample_on) {
    if (available.length) parts.push(el("p", {class: "muted"}, "没有随机抽的对手。勾上上面的框就可以加。"));
    holder.replaceChildren(...parts);
    return;
  }
  const s = c.opponent_sample;
  const options = state.matrixOptions.pool;
  const update = (key, value) => { s[key] = value; configChanged(); };
  const number = (key, min) => el("input", {
    type: "number",
    class: "top-n",
    step: 1,
    min,
    value: s[key] ?? "",
    onchange: (e) => update(key, e.target.value === "" ? null : Number(e.target.value)),
  });
  const shields = Array.from({length: state.options.max_shields + 1}, (_, n) => [n, `${n} 盾`]);
  parts.push(
    el("div", {class: "pool-row"},
      el("label", {}, "排名 ", select(
        options.rankings.map((r) => [r.key, `${r.key}：${r.name}${available.includes(r.key) ? "" : "（这个联盟没有）"}`]),
        s.rankings,
        (value) => update("rankings", value),
      )),
      el("label", {}, "非 Mega 前 ", number("top", 1), " 只"),
      el("label", {title: "大于 0：每队正好 1 只 Mega，从 Mega 前几只里抽；0：不带 Mega"},
        "Mega 前 ", number("mega_top", 0), " 只（0 是不带 Mega）"),
      el("label", {}, "抽 ", number("count", 1), " 队"),
      el("label", {title: "同一个种子每次抽出同样的队伍"}, "随机种子 ", number("seed")),
      el("label", {}, "IV ", select(options.ivs.map((v) => [v.key, v.name]), s.ivs, (value) => update("ivs", value))),
    ),
    el("div", {class: "pool-row"},
      el("span", {class: "muted"}, "抽出来的每一队："),
      select(shields, s.shields, (value) => update("shields", Number(value))),
      select(state.options.switching.map((o) => [o.key, o.name]), s.policy.switching,
        (value) => { s.policy.switching = value; configChanged(); }),
    ),
    el("p", {class: "muted"},
      "每一队：有 Mega 时先从 Mega 候选里抽 1 只，再从非 Mega 候选里抽满一队；同一种（按图鉴编号，暗影、Mega、地区形态都算同一种）" +
      "不重复，出场顺序随机，均匀抽、不按名次加权，成员相同的队伍只留一个。配招用 PvPoke 的推荐。抽出来的队伍叫“抽样 1”……“抽样 N”。"),
  );
  holder.replaceChildren(...parts);
}

function toggleSample(on) {
  state.config.sample_on = on;
  configChanged();
  renderSample();
}

// ---- 队伍库（4f 的队伍库，一队 3 只；每一队可以载入、存进去） ----

async function toggleLibrary(team) {
  state.libraryOpen = state.libraryOpen === team ? null : team;
  renderAll();
  if (state.libraryOpen === null) return;
  state.library = null;
  try {
    state.library = await api("/api/team-library");
  } catch (e) {
    showError(e.message);
  }
  renderLibrary(team);
}

function renderLibrary(team) {
  document.getElementById(`library-${keyOf(team)}`)?.replaceChildren(...libraryContent(team));
}

/** 打开的队伍库（library.js）：每队一行的按钮是"载入到这一队"。 */
function libraryContent(team) {
  return libraryPanel(state.library, {
    league: state.config.league,
    leagueName: leagueName(state.config.league),
    filter: state.libraryFilter,
    buttons: (entry) => el("button", {onclick: () => loadLibraryTeam(team, entry)}, "载入到这一队"),
  });
}

/** 把库里的一队填到这一队（换掉队名、盾数、主动换人和 3 只）：用到的覆盖文件自动勾上；联盟不同只提示，不强制。 */
async function loadLibraryTeam(team, entry) {
  const {customFiles, added, notes} = libraryLoadPlan(entry, state.config.custom_files,
    state.options.custom_files.map((f) => f.name), state.config.league, leagueName(state.config.league));
  if (entry.unsupported.length) notes.push(`网页上改不了的策略参数没有载入：${entry.unsupported.join("、")}`);

  const group = groupOf(team);
  Object.assign(team, normalizeMatrixTeam(entry.team, team.name)); // 同一个对象：页面上的 key 不变
  state.config.custom_files = customFiles;
  state.libraryOpen = null;
  configChanged();
  showError("");
  if (added.length) {
    await start(); // 覆盖文件变了：重新读宝可梦列表
  } else {
    renderGroup(group);
    for (const key of memberKeys(team)) scheduleBuild(key);
  }
  setStatus(`已载入 ${entry.name}（teams/${entry.file}）${notes.length ? `。${notes.join("；")}` : ""}`);
}

/** 把这一队存进队伍库（library.js）。 */
async function saveLibraryTeam(team) {
  showError("");
  try {
    const status = await saveTeamToLibrary(teamRequest(team), buildSettings(), leagueName(state.config.league));
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

// ---- 跑：边打边收结果 ----

async function runMatrix() {
  if (state.run) return;
  const config = requestConfig();
  const controller = new AbortController();
  state.run = {controller};
  updateRunButtons();
  showError("");
  setStatus("正在建配置、抽样……（环境前 N 第一次要建，可能要几秒）");
  try {
    const response = await fetch("/api/team-matrix", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(config),
      signal: controller.signal,
    });
    if (!response.ok) { // 配置写错了：服务器还没开始打，回的是一般的 JSON 错误
      const data = await response.json();
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    state.resultConfig = structuredClone(config);
    await readLines(response, onEvent);
    if (state.result?.status === "running") throw new Error("连接断了，没有打完");
  } catch (e) {
    const r = state.result;
    if (e.name === "AbortError") {
      if (r?.status === "running") {
        r.status = "stopped";
        refreshProgress();
        setStatus(`停了：打完 ${r.done} / ${r.total} 场`);
      } else {
        setStatus("停了");
      }
    } else {
      if (r?.status === "running") {
        r.status = "error";
        refreshProgress();
      }
      showError(e.message);
      setStatus("");
    }
  } finally {
    state.run = null;
    updateRunButtons();
  }
}

/** 一行一行读 NDJSON：每读完一行就交给 onLine（读到一半的行留到下一块）。 */
async function readLines(response, onLine) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += value;
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.trim()) onLine(JSON.parse(line));
    }
  }
  if (buffer.trim()) onLine(JSON.parse(buffer));
}

/** 服务器发来的一项（web_api.team_matrix_stream）：start → progress（一批打完的） → done；算到一半出错时是 error。 */
function onEvent(event) {
  if (event.type === "start") {
    state.result = {
      ...event,
      results: event.teams.map(() => event.opponents.map(() => null)),
      done: 0,
      status: "running",
    };
    state.view.team = Math.min(state.view.team, event.teams.length - 1);
    closeBattle(false);
    renderResult();
    setStatus(`正在打：0 / ${event.total} 场`);
    document.getElementById("result").scrollIntoView({behavior: "smooth"});
  } else if (event.type === "progress") {
    const r = state.result;
    for (const item of event.results) r.results[item.team][item.opponent] = item;
    r.done = event.done;
    refreshProgress();
    for (const redraw of state.redraws) redraw();
    setStatus(`正在打：${r.done} / ${r.total} 场`);
  } else if (event.type === "done") {
    Object.assign(state.result, {
      status: "done",
      seconds: event.seconds,
      summary: event.summary,
      report_markdown: event.report_markdown,
      csv: event.csv,
    });
    renderResult();
    setStatus(`跑完了：${state.result.total} 场，${event.seconds} 秒`);
  } else if (event.type === "error") {
    throw new Error(event.error);
  }
}

function stopMatrix() {
  state.run?.controller.abort();
}

function updateRunButtons() {
  document.getElementById("run").disabled = Boolean(state.run);
  document.getElementById("stop").disabled = !state.run;
}

function resetToExample() {
  if (!confirm("恢复成例子？现在填的设置、我方队伍和对手会被覆盖。")) return;
  state.config = normalizeConfig(state.matrixOptions.example);
  state.libraryOpen = null;
  save();
  setStatus("");
  start().catch((e) => showError(e.message));
}

// ---- 结果 ----

function renderResult() {
  const r = state.result;
  const section = document.getElementById("result");
  state.redraws = [];
  section.hidden = false;
  section.replaceChildren(
    resultHead(r),
    summaryCard(r),
    r.teams.length > 1 ? compareCard(r) : null,
    resultsCard(r),
    opponentsCard(r),
  );
  if (state.battleNode) placeBattle();
  markSelected();
}

function resultHead(r) {
  const done = r.status === "done";
  return el("div", {class: "card"},
    el("div", {class: "result-head"},
      el("h2", {}, "结果"),
      el("span", {class: "library-buttons"},
        el("button", {onclick: downloadReport, disabled: !done, title: done ? undefined : "全部打完才有"}, "下载 Markdown 报告"),
        el("button", {onclick: downloadCsv, disabled: !done, title: done ? "全部对战，一场一行（同命令行的 --csv）" : "全部打完才有"}, "下载 CSV"),
      ),
    ),
    el("p", {class: "stale", id: "stale-note", hidden: true},
      "配置改过了：下面还是上一次的结果，再点一次“跑队伍对队伍”更新（点一场看的也是上一次配置里的那一场）。"),
    el("div", {class: "progress-line", id: "progress-line"}, progressContent(r)),
    el("p", {}, `${r.settings.league_name}；赛季规则：${r.settings.season}。我方 ${r.teams.length} 队，` +
      `每一队对 ${r.opponents.length} 队对手各打一场 3v3，我方是第 0 方。对战是确定的，同一个配置每次结果相同。`),
    r.settings.custom_log.map((line) => el("p", {class: "muted"}, `覆盖文件：${line}`)),
    el("p", {class: "muted"},
      "评分从我方看：500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整，双方加起来 1000" +
      "（docs/mechanics.md 13.2 D1）。我方赢的加粗；底色从 0 红到 500 白到 1000 绿。点任何一场，在那张表下面看这一场的完整过程。"),
    r.teams.map((team) => teamLine(team, "side-0")),
  );
}

/** 进度条和一句话：打到哪了、打完用了几秒、停了还是出错了。 */
function progressContent(r) {
  const text = {
    running: `正在打：${r.done} / ${r.total} 场`,
    done: `打完了：${r.total} 场，${r.seconds} 秒（含建配置和抽样）`,
    stopped: `停了：打完 ${r.done} / ${r.total} 场。没打完不出总表、报告和 CSV；下面只有打完的那几场。`,
    error: `出错了：打完 ${r.done} / ${r.total} 场。没打完不出总表、报告和 CSV；下面只有打完的那几场。`,
  }[r.status];
  return [
    el("progress", {max: r.total || 1, value: r.done}),
    el("span", {class: r.status === "done" || r.status === "running" ? "" : "bad"}, text),
  ];
}

function refreshProgress() {
  document.getElementById("progress-line")?.replaceChildren(...progressContent(state.result));
}

/** 一队的一行：队名（盾数，策略）：每只的名字、CP、等级、IV。 */
function teamLine(team, sideClass) {
  return el("div", {class: `team-line ${sideClass}`},
    el("span", {class: "name"}, `${team.name}（${team.shields} 盾，${team.policy}）：`),
    team.members.map((m, slot) => `${slot ? "；" : ""}${team.member_names[slot]} CP ${m.cp} ${m.level} 级 IV ${m.ivs.join("/")}`),
  );
}

function summaryCard(r) {
  if (r.status !== "done") {
    return card("总表", el("p", {class: "muted"}, "全部打完以后才有总表（数字由服务器按全部对战算，同报告）。"));
  }
  const rows = r.summary.map((s) => [
    r.teams[s.team].name,
    s.group,
    el("td", {class: "num"}, s.battles),
    el("td", {class: "num"}, s.wins),
    el("td", {class: "num"}, s.draws),
    el("td", {class: "num"}, s.losses),
    ratingCell(s.mean_rating, {text: Math.round(s.mean_rating)}),
    el("td", {class: "num"}, `${s.mean_remaining[0].toFixed(2)} / ${s.mean_remaining[1].toFixed(2)}`),
  ]);
  return card("总表",
    el("p", {class: "muted"}, "一行是我方一队对一组对手。赢、平、输从我方看；平均评分是我方评分的平均。"),
    table(["我方队伍", "对手", el("th", {class: "num"}, "场数"), el("th", {class: "num"}, "赢"), el("th", {class: "num"}, "平"),
      el("th", {class: "num"}, "输"), el("th", {class: "num"}, "平均评分"), el("th", {class: "num"}, "平均剩余只数（我方 / 对方）")],
    rows, {class: "matchup-table"}),
  );
}

// ---- 结果：一场一格 ----

/** 一场在页面上的名字：我方第几队、对手第几队。 */
function cellId(team, opponent) {
  return `${team}:${opponent}`;
}

/** 评分格子：按评分上色（ratingColor），赢的加粗。opts：text（格子里写什么，默认是评分）、win、
 *  battle（{team, opponent, from}：这一格可以点，点了看这一场）。 */
function ratingCell(rating, opts = {}) {
  const attrs = {
    class: `num rating-cell${opts.win ? " win" : ""}`,
    style: `background: ${ratingColor(rating)}`,
  };
  if (opts.battle) {
    const {team, opponent, from} = opts.battle;
    attrs.class += " clickable";
    attrs["data-cell"] = cellId(team, opponent);
    attrs.title = "点一下看这一场";
    attrs.onclick = () => showBattle(team, opponent, from);
  }
  return el("td", attrs, opts.text ?? rating);
}

/** 还没打的一场（停了或者还在打）：结果那一列写"还没打"，其余写"—"。 */
function notPlayed(text = "—") {
  return el("td", {class: "muted", title: "还没打"}, text);
}

/** 对手那几列（对手队伍、哪一组、按出场顺序的成员），对照表和"每一场"共用。行是 {opponent, j}。 */
function opponentColumns() {
  return [
    {key: "order", title: "对手队伍", asc: true, tip: "按配置里的顺序排（手写的在前，抽样的按编号）", value: (row) => row.j,
      cell: (row) => el("td", {}, row.opponent.name)},
    {key: "group", title: "组", asc: true, value: (row) => row.opponent.group, cell: (row) => el("td", {}, row.opponent.group)},
    {key: "members", title: "对手（按出场顺序）", cell: (row) => el("td", {}, row.opponent.members.map((m, k) =>
      el("span", {class: "member-chip"}, typeDots(m.types), " ", row.opponent.member_names[k])))},
  ];
}

/** 对照：一行一队对手，一列我方一队的评分（我方两队以上时有）。正好两队时多一列差值。 */
function compareCard(r) {
  const rows = () => r.opponents.map((opponent, j) => ({opponent, j, results: r.teams.map((_, i) => r.results[i][j])}));
  const rating = (result) => (result ? result.ratings[0] : -1); // 没打完的排在最后（从大到小时）
  const columns = [
    ...opponentColumns(),
    ...r.teams.map((team, i) => ({
      key: `t${i}`, title: team.name, num: true, tip: `${team.name} 的评分`, value: (row) => rating(row.results[i]),
      cell: (row) => {
        const result = row.results[i];
        if (!result) return notPlayed();
        return ratingCell(result.ratings[0], {win: result.outcome === "赢", battle: {team: i, opponent: row.j, from: "compare-card"}});
      },
    })),
  ];
  if (r.teams.length === 2) {
    const diff = (row) => (row.results.every(Boolean) ? row.results[0].ratings[0] - row.results[1].ratings[0] : null);
    columns.push({
      key: "diff", title: "差值", num: true, tip: `${r.teams[0].name} 减 ${r.teams[1].name}`,
      value: (row) => diff(row) ?? -Infinity,
      cell: (row) => {
        const d = diff(row);
        if (d === null) return el("td", {class: "muted"}, "");
        return el("td", {class: `num ${d > 0 ? "good" : d < 0 ? "bad" : ""}`}, d > 0 ? `+${d}` : String(d));
      },
    });
  }
  const tableNode = matrixTable("compare", columns, rows);
  state.redraws.push(tableNode.redraw);
  return el("div", {class: "card", id: "compare-card"},
    el("h2", {}, "对照"),
    el("p", {class: "muted"}, "一行是一队对手，一列是我方一队对它的评分（从我方看）。点表头排序，点一格看那一场。"),
    tableNode,
  );
}

/** 每一场：我方一队对每一队对手，一行一场（同报告的"X 的每一场"）。我方两队以上时可以选看哪一队。 */
function resultsCard(r) {
  const holder = el("div");
  const draw = () => {
    const i = state.view.team;
    const rows = () => r.opponents.map((opponent, j) => ({opponent, j, result: r.results[i][j]}));
    const pair = (key) => (row) => `${row.result[key][0]} 对 ${row.result[key][1]}`;
    const played = (cell, text) => (row) => (row.result ? cell(row) : notPlayed(text));
    const columns = [
      ...opponentColumns(),
      {key: "outcome", title: "结果", value: (row) => (row.result ? OUTCOME_ORDER[row.result.outcome] : -1),
        cell: played((row) => el("td", {class: row.result.outcome === "赢" ? "win-text" : ""},
          row.result.outcome, row.result.timed_out ? "（时间到）" : ""), "还没打")},
      {key: "rating", title: "评分", num: true, tip: "我方 对 对手", value: (row) => (row.result ? row.result.ratings[0] : -1),
        cell: played((row) => ratingCell(row.result.ratings[0], {text: pair("ratings")(row), win: row.result.outcome === "赢"}))},
      {key: "remaining", title: "剩余只数", num: true, tip: "我方 对 对手", value: (row) => (row.result ? row.result.remaining[0] - row.result.remaining[1] : -Infinity),
        cell: played((row) => el("td", {class: "num"}, pair("remaining")(row)))},
      {key: "shields", title: "剩余盾", num: true, tip: "我方 对 对手", value: (row) => (row.result ? row.result.shields_left[0] - row.result.shields_left[1] : -Infinity),
        cell: played((row) => el("td", {class: "num"}, pair("shields_left")(row)))},
      {key: "turns", title: "回合", num: true, value: (row) => (row.result ? row.result.turns : -1),
        cell: played((row) => el("td", {class: "num"}, row.result.turns))},
    ];
    const tableNode = matrixTable(`results-${i}`, columns, rows, {
      rowAttrs: (row) => (row.result ? {
        class: "clickable-row",
        "data-cell": cellId(i, row.j),
        title: "点一下看这一场",
        onclick: () => showBattle(i, row.j, "results-card"),
      } : {}),
    });
    state.redraws = state.redraws.filter((f) => f !== holder.redraw);
    holder.redraw = tableNode.redraw;
    state.redraws.push(holder.redraw);
    holder.replaceChildren(tableNode);
  };
  draw();
  const chooser = r.teams.length > 1
    ? el("label", {}, "我方队伍 ", select(r.teams.map((t, k) => [k, t.name]), state.view.team,
      (v) => { state.view.team = Number(v); draw(); }))
    : el("b", {}, r.teams[0].name);
  return el("div", {class: "card", id: "results-card"},
    el("h2", {}, "每一场"),
    el("div", {class: "view-controls"}, chooser,
      el("span", {class: "muted"}, "评分、剩余只数、剩余盾都是“我方 对 对手”。点一行看这一场。")),
    holder,
  );
}

/** 可以点表头排序的表（battle_view.js 的 sortableTable）：排序记在 state.view.sorts[sortKey]，一开始按配置里的顺序。 */
function matrixTable(sortKey, columns, rows, opts = {}) {
  return sortableTable(columns, rows, {
    sorts: state.view.sorts, key: sortKey, first: {key: "order", desc: false}, afterDraw: markSelected,
    attrs: {class: "matchup-table"}, ...opts,
  });
}

/** 对手队伍：手写的每一队；随机抽的说明、建不了配置不参加抽样的、候选。 */
function opponentsCard(r) {
  const hand = r.opponents.filter((o) => o.group !== "抽样");
  const parts = [];
  if (hand.length) {
    parts.push(el("h3", {}, `手写的（${hand.length} 队）`), hand.map((team) => teamLine(team, "side-1")));
  }
  const s = r.sample;
  if (s) {
    const sampled = r.opponents.length - hand.length;
    parts.push(
      el("h3", {}, `随机抽的（${sampled} 队）`),
      el("p", {}, `${s.description}。`),
      el("p", {class: "muted"}, `每队 ${s.shields} 盾；策略：${s.policy}。抽出来的每一队在上面的表里；#后面是 PvPoke 排名文件里的名次。`),
      s.candidates.map((pool) => el("details", {class: "opponents-details"},
        el("summary", {}, `候选：${pool.name}（${pool.members.length} 只${pool.skipped.length ? `，另有 ${pool.skipped.length} 只建不了配置、不参加抽样` : ""}）`),
        pool.skipped.length ? el("p", {class: "muted"}, "建不了配置、不参加抽样的：" +
          pool.skipped.map((k) => `${k.rank} ${k.name}（${k.reason}）`).join("；")) : null,
        table([el("th", {class: "num"}, "名次"), "宝可梦", el("th", {class: "num"}, "综合分")], pool.members.map((m) => [
          el("td", {class: "num"}, m.rank), m.label, el("td", {class: "num"}, m.score.toFixed(1)),
        ])),
        el("p", {class: "muted"}, "推荐配招来自 PvPoke；CP、等级、IV 按 IV 规则和赛季规则（下载的报告里有每只的详细配置）。"),
      )),
    );
  }
  return card("对手队伍", ...parts);
}

// ---- 点一场看这一场 ----

async function showBattle(team, opponent, from) {
  showError("");
  setStatus("正在打这一场……");
  let data;
  try {
    data = await api("/api/matrix-battle", {config: state.resultConfig, team, opponent});
  } catch (e) {
    showError(e.message);
    setStatus("");
    return;
  }
  state.battle = {team, opponent, from, data};
  state.battleNode?.remove();
  state.battleNode = battlePanel(team, opponent, data);
  placeBattle();
  markSelected();
  state.battleNode.scrollIntoView({behavior: "smooth", block: "start"});
  setStatus(`${data.teams[0].name} 对 ${data.teams[1].name}：${data.outcome}`);
}

/** 放在点的那张表所在的卡片下面。 */
function placeBattle() {
  const anchor = document.getElementById(state.battle.from) ?? document.getElementById("result").lastElementChild;
  anchor.after(state.battleNode);
}

function battlePanel(team, opponent, data) {
  const head = el("div", {class: "card"},
    el("div", {class: "result-head"},
      el("h2", {}, `这一场：${data.teams[0].name} 对 ${data.teams[1].name}`),
      el("span", {class: "library-buttons"},
        el("button", {onclick: () => openInBattlePage(team, opponent), title: "把这两队填到“打一场”页（新标签页），在那里可以改着试、手动对战、搜索应对"},
          "在打一场页打开"),
        el("button", {onclick: () => downloadBattleReport(data)}, "下载这一场的报告"),
        el("button", {onclick: () => backToCell()}, "回到那一行"),
        el("button", {onclick: () => closeBattle(true)}, "关掉"),
      ),
    ),
    el("p", {class: "outcome"}, data.outcome),
    data.teams.map((t, side) => el("div", {class: `team-line side-${side}`},
      el("span", {class: "name"}, `${t.name}（${t.shields} 盾，${t.policy}）：`),
      t.members.map((m, slot) => `${slot ? "；" : ""}${t.names[slot]} CP ${m.cp} ${m.level} 级 IV ${m.ivs.join("/")}`),
    )),
    el("p", {class: "muted"}, "和命令行 tools.run_team_matrix --battle 打的是同一场。换人、开盾的原因在下面的表和时间线里。"),
  );
  // 图左边写"我方""对手"：队名可能很长（例如 "Team A (Mega Froslass)"），写不下
  return el("div", {class: "battle-view", id: "battle"}, head, ...battleCards(data, {chart: {sideLabels: ["我方", "对手"]}}));
}

/** 关掉正在看的一场。back：滚回点的那一格。 */
function closeBattle(back) {
  const had = state.battle;
  state.battleNode?.remove();
  state.battleNode = null;
  if (back && had) backToCell();
  state.battle = null;
  markSelected();
}

/** 滚回点的那一格（在点的那张表里找）。 */
function backToCell() {
  const {team, opponent, from} = state.battle ?? {};
  if (team === undefined) return;
  const node = document.querySelector(`#${from} [data-cell="${cellId(team, opponent)}"]`);
  if (!node) return;
  node.scrollIntoView({behavior: "smooth", block: "center"});
  node.classList.add("flash");
  setTimeout(() => node.classList.remove("flash"), 1500);
}

/** 正在看的那一场的格子、行加框（几张表里都有的都加）。 */
function markSelected() {
  const id = state.battle ? cellId(state.battle.team, state.battle.opponent) : null;
  for (const node of document.querySelectorAll("#result [data-cell]")) node.classList.toggle("selected", node.dataset.cell === id);
}

/** "在打一场页打开"：服务器把这一场写成"打一场"页的配置（web_api.matrix_pairing_config），存在 PAIRING_KEY 里，
 *  再在新标签页打开"打一场"页；那边先问要不要换掉现在填的两队。 */
async function openInBattlePage(team, opponent) {
  showError("");
  try {
    const data = await api("/api/matrix-pairing", {config: state.resultConfig, team, opponent});
    const [a, b] = data.config.team.map((t) => t.name);
    localStorage.setItem(PAIRING_KEY, JSON.stringify({title: `${a} 对 ${b}`, config: data.config, warnings: data.warnings}));
    const opened = window.open("index.html", "_blank");
    setStatus(opened
      ? `已在新标签页打开“打一场”页（它会先问要不要换掉那里现在填的两队）${data.warnings.length ? `。${data.warnings.join("；")}` : ""}`
      : "浏览器没让开新标签页：自己打开“打一场”页，它会问要不要载入这一场。");
  } catch (e) {
    showError(e.message);
  }
}

// ---- 下载、导入导出 ----

/** 下载的文件名：matrix_我方第一队[_and_N_more]（同 web_api.export_matrix）。 */
function fileStem(names) {
  return `matrix_${safeName(names[0])}${names.length > 1 ? `_and_${names.length - 1}_more` : ""}`;
}

function safeName(text) {
  return text.replace(/[^\w一-鿿.-]+/g, "_").replace(/^[._]+|[._]+$/g, "");
}

function downloadReport() {
  const r = state.result;
  downloadText(`${fileStem(r.teams.map((t) => t.name))}.md`, r.report_markdown, "text/markdown");
}

function downloadCsv() {
  const r = state.result;
  downloadText(`${fileStem(r.teams.map((t) => t.name))}.csv`, r.csv, "text/csv");
}

function downloadBattleReport(data) {
  downloadText(`3v3_${safeName(data.teams[0].name)}_vs_${safeName(data.teams[1].name)}.md`, data.report_markdown, "text/markdown");
}

async function exportConfig() {
  showError("");
  try {
    const data = await api("/api/export-matrix", requestConfig());
    downloadText(data.filename, data.text, "application/toml");
    setStatus(`已导出 ${data.filename}`);
  } catch (e) {
    showError(e.message);
  }
}

async function importConfig(file) {
  showError("");
  try {
    const data = await api("/api/import-matrix", {text: await file.text(), name: file.name});
    const warnings = data.warnings.length ? `\n\n注意：\n- ${data.warnings.join("\n- ")}` : "";
    if (!confirm(`导入 ${file.name}？现在填的设置、我方队伍和对手会被换掉。${warnings}`)) return;
    // 导入的配置里没有随机抽时，保留现在填的随机抽设置（只是关掉）
    const previousSample = state.config.opponent_sample;
    state.config = normalizeConfig(data.config);
    if (!data.config.opponent_sample) state.config.opponent_sample = previousSample;
    state.libraryOpen = null;
    save();
    await start();
    setStatus(`已导入 ${file.name}${data.warnings.length ? `（${data.warnings.join("；")}）` : ""}`);
  } catch (e) {
    showError(e.message);
  }
}

// ---- 启动 ----

/** 按 state.config 画设置、我方队伍和对手，并请服务器建每只的配置。 */
async function start() {
  forgetMembers();
  renderSettings();
  await reloadCatalog();
  renderAll();
  rebuildMembers();
}

async function init() {
  document.getElementById("run").addEventListener("click", runMatrix);
  document.getElementById("stop").addEventListener("click", stopMatrix);
  document.getElementById("reset").addEventListener("click", resetToExample);
  document.getElementById("add-team").addEventListener("click", () => addTeam("team"));
  document.getElementById("add-opponent_team").addEventListener("click", () => addTeam("opponent_team"));
  document.getElementById("sample-on").addEventListener("change", (e) => toggleSample(e.target.checked));
  document.getElementById("export-config").addEventListener("click", exportConfig);
  document.getElementById("import-config").addEventListener("click", () => document.getElementById("import-file").click());
  document.getElementById("import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // 同一个文件再选一次也能触发
    if (file) importConfig(file);
  });
  try {
    [state.options, state.matrixOptions] = await Promise.all([api("/api/options"), api("/api/matrix-options")]);
    state.config = normalizeConfig(loadSaved() ?? state.matrixOptions.example);
    await start();
  } catch (e) {
    showError(`页面加载失败：${e.message}`);
  }
}

init();
