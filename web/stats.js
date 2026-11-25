"use strict";
// 能力值排序（第 4 步，4d）：每只宝可梦在一个联盟里的 CP、等级、IV、实际攻防 HP、坦度；可以筛选、点表头按任意列排序。
//
// 每只的等级、IV、能力值都由服务器算（GET /api/stats，见 pogo_sim/stat_table.py、web_api.stat_table_payload）；
// 这里只做筛选、排序和显示，以及自定义的一列 攻^a × 防^b × HP^c（显示成占筛选后第 1 名的百分比）。
// 设置、筛选和排序记在浏览器里（localStorage），下次打开还是这样。

const STATS_KEY = "pogo_sim.stats.v1";
const PAGE_SIZE = 200; // 一次显示几行
const TAG_FILTERS = [["mega", "Mega"], ["legendary", "传说"], ["mythical", "幻之"], ["ultrabeast", "究极异兽"], ["shadow", "暗影"]];

/** 页面上的选择（存进 localStorage）。 */
function defaultView() {
  return {
    league: 1500,
    season: "pvpoke",
    custom_files: [],
    exclude: [], // TAG_FILTERS 里勾了哪几个
    releasedOnly: true,
    type: "",
    top: null, // 只看 PvPoke 排名前几名；null 是不限
    search: "",
    weights: [1, 1, 1], // 自定义一列：攻^a × 防^b × HP^c
    sort: {key: "bulk", desc: true},
  };
}

const state = {
  options: null, // GET /api/options
  data: null, // GET /api/stats 的结果
  view: defaultView(),
  shown: PAGE_SIZE, // 现在显示前几行
  loadSeq: 0, // 最新一次请求的序号：旧请求的结果晚到时丢掉
};

// ---- 表的列 ----
// value(row)：排序用的数（null 的总排在最后）；text(row)：显示的文字（不写就显示 value）。
// asc：第一次点这一列时从小到大排（名字、排名）；其他列从大到小。

const fixed = (digits) => (x) => x.toFixed(digits);

const COLUMNS = [
  {key: "name", title: "宝可梦", value: (r) => r.name, text: nameCell, asc: true},
  {key: "rank", title: "排名", value: (r) => r.rank ?? r.mega_rank, text: rankText, asc: true,
    tip: "PvPoke 在这个联盟的排名；Mega 是 Mega 版排名（M 开头）"},
  {key: "cp", title: "CP", value: (r) => r.cp},
  {key: "level", title: "等级", value: (r) => r.level},
  {key: "ivs", title: "IV", value: null, text: (r) => r.ivs.join("/"), tip: "这个联盟 IV 排名第 1（攻/防/HP）"},
  {key: "atk", title: "攻", value: (r) => r.atk, text: (r) => fixed(1)(r.atk), tip: "实际攻击，含暗影倍率"},
  {key: "def", title: "防", value: (r) => r.def, text: (r) => fixed(1)(r.def), tip: "实际防御，含暗影倍率"},
  {key: "hp", title: "HP", value: (r) => r.hp},
  {key: "bulk", title: "坦度", value: (r) => r.bulk, text: (r) => Math.round(r.bulk).toLocaleString(), tip: "防 × HP"},
  {key: "stat_product", title: "能力值乘积（千）", value: (r) => r.stat_product,
    text: (r) => Math.round(r.stat_product / 1000).toLocaleString(), tip: "攻 × 防 × HP，除以 1000"},
  {key: "custom", title: "自定义", value: customValue, text: customText, tip: "攻^a × 防^b × HP^c，占筛选后第 1 名的百分比"},
  {key: "base_atk", title: "种族攻", value: (r) => r.base[0]},
  {key: "base_def", title: "种族防", value: (r) => r.base[1]},
  {key: "base_hp", title: "种族 HP", value: (r) => r.base[2]},
];

function nameCell(r) {
  const flags = [];
  if (r.custom) flags.push("覆盖文件");
  if (!r.released) flags.push("未实装");
  return [typeDots(r.types), " ", r.name, flags.length ? el("span", {class: "muted"}, ` · ${flags.join("、")}`) : null];
}

function rankText(r) {
  if (r.rank) return String(r.rank);
  if (r.mega_rank) return `M${r.mega_rank}`;
  return "—";
}

function customValue(r) {
  const [a, b, c] = state.view.weights;
  return r.atk ** a * r.def ** b * r.hp ** c;
}

function customText(r) {
  return `${(100 * customValue(r) / state.customBest).toFixed(1)}%`;
}

// ---- 筛选和排序 ----

/** 筛选后的行。覆盖文件里的总是列出（不看"只看已实装"和"排名前几名"），方便看新宝可梦排在哪。 */
function filteredRows() {
  const v = state.view;
  const words = normalizeSearch(v.search).split(" ").filter(Boolean);
  return state.data.rows.filter((r) => {
    if (v.exclude.some((tag) => r.tags.includes(tag))) return false; // Mega、暗影也是 gamemaster 的 tags
    if (v.type && !r.types.includes(v.type)) return false;
    if (words.length && !words.every((w) => ` ${r.search}`.includes(w))) return false;
    if (r.custom) return true;
    if (v.releasedOnly && !r.released) return false;
    if (v.top) {
      const rank = r.rank ?? r.mega_rank;
      if (!rank || rank > v.top) return false;
    }
    return true;
  });
}

function sortRows(rows) {
  const {key, desc} = state.view.sort;
  const column = COLUMNS.find((c) => c.key === key) ?? COLUMNS.find((c) => c.key === "bulk");
  const keyed = rows.map((row, index) => ({row, index, value: column.value(row)}));
  keyed.sort((x, y) => {
    if (x.value == null || y.value == null) return (x.value == null) - (y.value == null) || x.index - y.index;
    const order = typeof x.value === "string" ? x.value.localeCompare(y.value) : x.value - y.value;
    return (desc ? -order : order) || x.index - y.index;
  });
  return keyed.map((k) => k.row);
}

function setSort(column) {
  const sort = state.view.sort;
  if (sort.key === column.key) sort.desc = !sort.desc;
  else state.view.sort = {key: column.key, desc: !column.asc};
  state.shown = PAGE_SIZE;
  viewChanged();
}

// ---- 显示 ----

function renderTable() {
  if (!state.data) return;
  const rows = sortRows(filteredRows());
  state.customBest = Math.max(...rows.map(customValue), 0) || 1;
  const {key, desc} = state.view.sort;

  const header = el("tr", {}, el("th", {}, "#"), COLUMNS.map((column) => {
    const sortable = column.value !== null;
    const arrow = column.key === key ? (desc ? " ▼" : " ▲") : "";
    return el("th", {
      class: sortable ? "sortable" : null,
      title: column.tip ?? null,
      onclick: sortable ? () => setSort(column) : null,
    }, column.title + arrow);
  }));
  const body = rows.slice(0, state.shown).map((r, i) => el("tr", {class: r.custom ? "custom-row" : null},
    el("td", {class: "num muted"}, i + 1),
    COLUMNS.map((column) => {
      const content = column.text ? column.text(r) : column.value(r);
      return el("td", {class: column.key === "name" ? "name" : "num"}, content);
    })));
  document.getElementById("stats-table").replaceChildren(
    el("table", {class: "stats"}, el("thead", {}, header), el("tbody", {}, body)));

  const sortName = COLUMNS.find((c) => c.key === key)?.title ?? key;
  const total = state.data.rows.length;
  let status = `共 ${total} 只，筛选后 ${rows.length} 只；按${sortName}${desc ? "从高到低" : "从低到高"}排。`;
  if (state.data.computed > 0) status += `（这次新算了 ${state.data.computed} 只，用了 ${state.data.seconds} 秒；之后读本地缓存）`;
  setStatus(status);

  const more = document.getElementById("more");
  more.replaceChildren(rows.length > state.shown
    ? el("button", {onclick: () => { state.shown += PAGE_SIZE; renderTable(); }},
      `再显示 ${Math.min(PAGE_SIZE, rows.length - state.shown)} 只（还有 ${rows.length - state.shown} 只）`)
    : "");
}

function renderSkipped() {
  const skipped = state.data?.skipped ?? [];
  document.getElementById("skipped").replaceChildren(skipped.length === 0 ? "" : el("details", {},
    el("summary", {}, `${skipped.length} 只在这个联盟没有合法配置（最低等级时 CP 就超过上限），没有列出`),
    el("ul", {class: "notes"}, skipped.map((s) => el("li", {}, `${s.name}：${s.reason}`)))));
}

function renderIntro() {
  const m = state.data?.shadow_multipliers;
  if (!m) return;
  document.getElementById("intro").textContent =
    "每只按赛季规则取这个联盟 IV 排名第 1 和合法的最高等级（和打一场时不填 IV、等级一样）。" +
    `攻、防含暗影倍率（攻 ×${m.atk}，防 ×${m.def.toFixed(3)}）。坦度 = 防 × HP；能力值乘积 = 攻 × 防 × HP。`;
}

// ---- 设置、筛选、自定义 ----

function renderSettings() {
  const {options, view} = state;
  document.getElementById("league").replaceWith(select(
    options.leagues.map((l) => [l.cp, `${l.name}（${l.cp === 10000 ? "不限 CP" : `CP ${l.cp}`}）`]),
    view.league,
    (value) => { view.league = Number(value); load(); },
    {id: "league"},
  ));
  document.getElementById("season").replaceWith(select(
    options.seasons.map((s) => [s.key, s.name]),
    view.season,
    (value) => { view.season = value; load(); },
    {id: "season"},
  ));
  document.getElementById("custom-files").replaceChildren(...options.custom_files.map((file) => el("label", {},
    el("input", {
      type: "checkbox",
      checked: view.custom_files.includes(file.name),
      onchange: (e) => {
        view.custom_files = options.custom_files.map((f) => f.name)
          .filter((name) => (name === file.name ? e.target.checked : view.custom_files.includes(name)));
        load();
      },
    }),
    ` 覆盖文件 ${file.name}`,
    file.description ? el("span", {class: "muted"}, `：${file.description}`) : null,
  )));
}

function renderFilters() {
  const view = state.view;
  const checkbox = (checked, onChange, text) => el("label", {},
    el("input", {type: "checkbox", checked, onchange: (e) => { onChange(e.target.checked); viewChanged(); }}), ` ${text}`);

  document.getElementById("filters").replaceChildren(
    el("span", {}, "排除：", TAG_FILTERS.map(([tag, text]) => checkbox(view.exclude.includes(tag), (on) => {
      view.exclude = TAG_FILTERS.map(([t]) => t).filter((t) => (t === tag ? on : view.exclude.includes(t)));
    }, text))),
    checkbox(view.releasedOnly, (on) => { view.releasedOnly = on; }, "只看已实装"),
    el("label", {}, "属性 ", select([["", "全部"], ...Object.keys(TYPE_COLORS).map((t) => [t, t])], view.type,
      (value) => { view.type = value; viewChanged(); })),
    el("label", {title: "Mega 看 Mega 版排名；覆盖文件里的总是列出"}, "只看 PvPoke 排名前 ",
      el("input", {
        type: "number", min: 1, step: 1, value: view.top ?? "", placeholder: "不限", class: "top-n",
        oninput: (e) => { view.top = Number(e.target.value) > 0 ? Number(e.target.value) : null; viewChanged(); },
      }), " 名"),
    el("label", {}, "搜名字 ", el("input", {
      value: view.search, placeholder: "如 mega、azu、zygarde 100", autocomplete: "off",
      oninput: (e) => { view.search = e.target.value; viewChanged(); },
    })),
    el("span", {class: "muted"}, "覆盖文件里的总是列出（不看已实装和排名），整行标黄。"),
  );
}

function renderFormula() {
  const view = state.view;
  const names = ["攻", "防", "HP"];
  const inputs = names.map((name, i) => el("label", {}, `${name}^`, el("input", {
    type: "number", step: 0.1, value: view.weights[i], class: "weight",
    oninput: (e) => {
      const w = Number(e.target.value);
      view.weights[i] = Number.isFinite(w) ? w : 0;
      viewChanged();
    },
  })));
  const preset = (text, weights) => el("button", {
    onclick: () => { view.weights = [...weights]; view.sort = {key: "custom", desc: true}; renderFormula(); viewChanged(); },
  }, text);
  document.getElementById("formula").replaceChildren(
    el("span", {}, inputs[0], " × ", inputs[1], " × ", inputs[2]),
    preset("= 坦度（0, 1, 1）", [0, 1, 1]),
    preset("= 能力值乘积（1, 1, 1）", [1, 1, 1]),
    el("span", {class: "muted"}, "显示成占筛选后第 1 名的百分比；点表头\"自定义\"按它排。"),
  );
}

// ---- 读数据 ----

async function load() {
  save();
  const seq = ++state.loadSeq;
  const {league, season, custom_files} = state.view;
  const params = new URLSearchParams({league, season});
  for (const name of custom_files) params.append("custom", name);
  setStatus("正在算……（一个联盟第一次打开要算几秒，之后读本地缓存）");
  showError("");
  try {
    const data = await api(`/api/stats?${params}`);
    if (seq !== state.loadSeq) return; // 这期间又改过设置，以后面那次为准
    state.data = data;
  } catch (e) {
    if (seq !== state.loadSeq) return;
    state.data = null;
    showError(e.message);
    setStatus("");
    document.getElementById("stats-table").replaceChildren();
    return;
  }
  state.shown = PAGE_SIZE;
  renderIntro();
  renderSkipped();
  renderTable();
}

function viewChanged() {
  save();
  renderTable();
}

function save() {
  localStorage.setItem(STATS_KEY, JSON.stringify(state.view));
}

/** 浏览器记住的选择；读不了或者和现在的选项对不上的部分用默认值。 */
function loadSaved() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(STATS_KEY) ?? "{}") ?? {};
  } catch {
    saved = {};
  }
  const view = {...defaultView(), ...saved};
  const {options} = state;
  if (!options.leagues.some((l) => l.cp === view.league)) view.league = defaultView().league;
  if (!options.seasons.some((s) => s.key === view.season)) view.season = options.seasons[0].key;
  view.custom_files = (view.custom_files ?? []).filter((name) => options.custom_files.some((f) => f.name === name));
  if (!Array.isArray(view.weights) || view.weights.length !== 3) view.weights = defaultView().weights;
  if (!Array.isArray(view.exclude)) view.exclude = [];
  return view;
}

async function init() {
  try {
    state.options = await api("/api/options");
  } catch (e) {
    showError(`连不上服务器：${e.message}`);
    return;
  }
  state.view = loadSaved();
  renderSettings();
  renderFilters();
  renderFormula();
  await load();
}

init();
