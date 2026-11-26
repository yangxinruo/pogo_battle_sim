"use strict";
// 一只宝可梦的编辑器（4g 起几页共用；在 common.js 之后、各页自己的脚本之前加载）：
// 选宝可梦（可以搜的下拉框）、形态、配招、更多设置（名字、IV、等级、挚友、Mega 等级、招式池外的招），
// 以及服务器按赛季规则建配置的结果（CP、等级、IV、说明）。还有一队的编辑器（4h 起"打一场"页和队伍对队伍页共用）：
// 队名、盾数、主动换不换人，加上每只的编辑器。
//
// 和其他脚本一样只负责显示和填表：建配置、检查都在服务器（POST /api/build，web_api.build_member）。
// 一只宝可梦的写法同配置文件里的一只（[[team.member]]、[[subject]]、[[opponent]]），见 memberRequest。
//
// 用法：页面先 loadCatalog(联盟, 覆盖文件)，再对每只调 memberEditor(key, member, opts) 得到它的元素放进页面。
// key 是这一只在页面上独一无二的名字（例如 "0-1"、"subject-3"），元素的 id 和建配置的结果都按它存。
// member 是 normalizeMember 整理过的对象，编辑器直接改它，改完调 opts.onChange()（页面记住配置等）。

const BUILD_DELAY_MS = 300; // 改完一只后等这么久再请服务器建配置（连续输入时只请一次）
const PICKER_LIMIT = 100; // 下拉框里最多列出几个（太多时继续输入缩小范围）

const editor = {
  catalog: null, // GET /api/species：{species: [...], moves: {招式 ID: {...}}}
  speciesById: new Map(),
  members: new Map(), // key → {member, opts}：页面上画着的每只（重新画这一只、建配置时用）
  builds: new Map(), // key → 建配置的结果（POST /api/build）：{info} 或 {error}
  buildTimers: new Map(),
  buildSeq: new Map(), // 每只最新一次建配置请求的序号：旧请求的结果晚到时丢掉
  openDetails: new Set(), // 展开了"更多设置"的是哪几只（重新画这一只时保持展开）
};

// ---- 一只宝可梦的配置 ----

/** 例子配置、浏览器记住的配置或导入的配置里的一只，整理成页面用的样子（缺的字段补上默认值）。 */
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

/** 一只宝可梦发给服务器的写法：同配置文件里的一只，没填的可选项不写。 */
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

// ---- 一队的配置 ----

/** 配置里的一队整理成页面用的样子。defaults：{name, size（每队几只）, shields, switching}，缺的字段用它。
 *  页面上每队只能改盾数和主动换不换人（switching），其余的策略参数用默认值。 */
function normalizeTeam(team, defaults) {
  return {
    name: team.name ?? defaults.name,
    shields: team.shields ?? defaults.shields,
    policy: {switching: team.policy?.switching ?? defaults.switching},
    member: Array.from({length: defaults.size}, (_, slot) => normalizeMember(team.member?.[slot] ?? {})),
  };
}

/** 一队发给服务器的写法：同配置文件里的一队（3v3 的 [[team]]，队伍对队伍的 [[team]]、[[opponent_team]]）。 */
function teamRequest(team) {
  return {
    name: team.name,
    shields: team.shields,
    policy: {switching: team.policy.switching},
    member: team.member.map(memberRequest),
  };
}

// ---- 宝可梦和招式 ----

/** 读宝可梦列表（推荐配招和排名跟联盟走；覆盖文件新加的宝可梦和招式也在里面）。 */
async function loadCatalog(league, customFiles) {
  const params = new URLSearchParams({league});
  for (const name of customFiles) params.append("custom", name);
  editor.catalog = await api(`/api/species?${params}`);
  editor.speciesById = new Map(editor.catalog.species.map((s) => [s.id, s]));
  for (const species of editor.catalog.species) species.nameKey = normalizeSearch(species.name);
}

function speciesName(id) {
  return editor.speciesById.get(id)?.name ?? id;
}

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
  const move = editor.catalog.moves[moveId];
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
  return Object.entries(editor.catalog.moves).filter(([, m]) => m.fast === fast).map(([id]) => id).sort();
}

/** 选了宝可梦以后先填的配招：PvPoke 在这个联盟的推荐配招，没有就取招式池里的前几个。 */
function defaultMoves(species) {
  if (species.recommended) {
    const [fast, ...charged] = species.recommended;
    return {fast, charged};
  }
  return {fast: species.fast[0] ?? "", charged: species.charged.slice(0, 2)};
}

/** 同一图鉴编号的各形态（普通、暗影、Mega、地区形态……）；只有一种时为空。 */
function formsOf(species) {
  const forms = editor.catalog.species.filter((s) => s.dex === species.dex);
  return forms.length > 1 ? forms : [];
}

// ---- 选宝可梦：可以搜的下拉框 ----
// 点一下输入框就列出全部宝可梦（有 PvPoke 排名时按这个联盟的排名，排名外的按图鉴编号）。
// 输入名字的一部分可以缩小范围：拆成几个词，每个词都要在 web_api.search_text 给的文字里出现，不分先后，
// 所以 "mega venu"、"venusaur mega"、"zygarde 100"、"legendary" 都能搜到。
// 选好一只以后，旁边的"形态"下拉框列出同一图鉴编号的各形态（普通、暗影、Mega……），可以直接换。

/** 搜宝可梦，返回排好序的列表。
 *  排序：名字以输入开头的最前；其次每个词都是某个词的开头；然后按 PvPoke 普通排名（排名外的在后面）、图鉴顺序。 */
function searchSpecies(query) {
  const q = normalizeSearch(query);
  const words = q.split(" ").filter(Boolean);
  const found = [];
  editor.catalog.species.forEach((species, index) => {
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
  const ranked = editor.catalog.species.some((s) => s.rank);
  const order = ranked ? "按 PvPoke 这个联盟的排名列出（排名外的和 Mega 按图鉴编号排在后面）" : "按图鉴编号列出";
  return `${order}。输入可以搜：${hint}`;
}

/** 选宝可梦的输入框和下拉列表。打开时输入框先清空（原来的名字留作灰字提示），没选就关掉时恢复原样。 */
function speciesPicker(key, member, species) {
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
    else setSpecies(key, id);
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
    const exact = q && editor.catalog.species.find((s) => s.nameKey === q || normalizeSearch(s.id) === q);
    if (exact) pick(exact.id);
    else close();
  });
  return el("span", {class: "species-picker"}, input, menu);
}

// ---- 编辑器 ----

/** 一只宝可梦的编辑器。opts：
 *  - role：最左边的标签（"首发"、"后备 1"、"测试对象 2"……）
 *  - tools：标题行最后加的元素（例如"去掉"按钮），可以没有
 *  - settings()：建配置用的 {league, season, custom_files}
 *  - onChange()：这一只改了以后调用（页面记住配置、标出结果过时了） */
function memberEditor(key, member, opts) {
  editor.members.set(key, {member, opts});
  const species = editor.speciesById.get(member.species);
  const changed = () => memberChanged(key);
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

  return el("div", {class: "member", id: `member-${key}`},
    el("div", {class: "member-head"},
      el("span", {class: "role"}, opts.role),
      speciesPicker(key, member, species),
      forms.length ? el("label", {class: "forms", title: "同一图鉴编号的其他形态：普通、暗影、Mega、地区形态……"}, "形态 ",
        select(forms.map((s) => [s.id, s.name]), species.id, (id) => setSpecies(key, id))) : null,
      el("span", {class: "muted"}, speciesNote),
      opts.tools ?? null,
    ),
    moves.length ? el("div", {class: "moves"}, moves) : null,
    memberDetails(key, member, species),
    el("div", {class: "build", id: `build-${key}`}, buildText(key)),
  );
}

/** 一队的编辑器：卡片，标题行是队名、盾数、主动换不换人，下面是每只的编辑器（首发、后备 1、后备 2）。
 *  team 是 normalizeTeam 整理过的对象，编辑器直接改它。opts：
 *  - prefix：每只的 key 是 `${prefix}-${第几只}`（memberEditor 的 key）
 *  - class：卡片另加的类名（例如 "side-0"），可以没有
 *  - maxShields、switching：盾数最多几个、主动换人能选什么（/api/options 的 max_shields、switching）
 *  - settings()、onChange()：同 memberEditor；onNameChange()：队名改了另外调用，可以没有
 *  - nameTitle：队名输入框的提示；tools：标题行最后加的元素（队伍库按钮、去掉……）；
 *    panel：标题行下面的元素（打开的队伍库），都可以没有 */
function teamEditor(team, opts) {
  const shields = Array.from({length: opts.maxShields + 1}, (_, n) => [n, `${n} 盾`]);
  return el("div", {class: `card team ${opts.class ?? ""}`.trim()},
    el("div", {class: "team-head"},
      el("input", {
        class: "team-name",
        value: team.name,
        title: opts.nameTitle ?? "队名",
        oninput: (e) => { team.name = e.target.value; opts.onChange(); opts.onNameChange?.(); },
      }),
      select(shields, team.shields, (v) => { team.shields = Number(v); opts.onChange(); }),
      select(opts.switching.map((s) => [s.key, s.name]), team.policy.switching,
        (v) => { team.policy.switching = v; opts.onChange(); }),
      opts.tools ?? null,
    ),
    opts.panel ?? null,
    team.member.map((member, slot) => memberEditor(`${opts.prefix}-${slot}`, member, {
      role: slot === 0 ? "首发" : `后备 ${slot}`,
      settings: opts.settings,
      onChange: opts.onChange,
    })),
  );
}

/** "更多设置"：名字、IV、等级、挚友、Mega 等级、招式池外的招，以及建配置的说明。 */
function memberDetails(key, member, species) {
  const changed = () => memberChanged(key);
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

  return el("details", {
    open: editor.openDetails.has(key),
    ontoggle: (e) => {
      if (e.target.open) editor.openDetails.add(key);
      else editor.openDetails.delete(key);
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
          refreshMember(key); // 能选的招式变了
          changed();
        },
      }), " 允许招式池外的招"),
    ),
    el("div", {class: "muted"}, "IV 三项都填才生效；不填 IV 和等级时按赛季规则取 IV 排名第 1 和合法的最高等级。"),
    el("ul", {class: "notes", id: `notes-${key}`}, buildNotes(key)),
  );
}

/** 重新画这一只（换了宝可梦、能选的招式变了）。 */
function refreshMember(key) {
  const {member, opts} = editor.members.get(key);
  document.getElementById(`member-${key}`)?.replaceWith(memberEditor(key, member, opts));
}

/** 选了宝可梦（ID）：换成它的推荐配招。 */
function setSpecies(key, id) {
  const {member} = editor.members.get(key);
  member.species = id;
  const species = editor.speciesById.get(id);
  if (species) {
    const moves = defaultMoves(species);
    member.fast = moves.fast;
    member.charged = moves.charged;
    if (!species.mega) member.mega_level = null;
  }
  refreshMember(key);
  memberChanged(key);
}

function memberChanged(key) {
  editor.members.get(key).opts.onChange();
  scheduleBuild(key);
}

/** 页面整个重画、要换掉全部编辑器之前调用：忘掉以前画过的每只和它们建配置的结果。 */
function forgetMembers() {
  for (const key of [...editor.members.keys()]) forgetMember(key);
}

/** 这一只从页面上去掉了：忘掉它（不再建配置）。 */
function forgetMember(key) {
  clearTimeout(editor.buildTimers.get(key));
  editor.members.delete(key);
  editor.builds.delete(key);
  editor.buildTimers.delete(key);
}

// ---- 建配置（服务器算 CP、等级、IV） ----

function scheduleBuild(key) {
  clearTimeout(editor.buildTimers.get(key));
  editor.buildTimers.set(key, setTimeout(() => runBuild(key), BUILD_DELAY_MS));
}

/** 页面上画着的每只都重新建配置（联盟、赛季规则、覆盖文件改了）。 */
function rebuildMembers() {
  for (const key of editor.members.keys()) scheduleBuild(key);
}

async function runBuild(key) {
  const seq = (editor.buildSeq.get(key) ?? 0) + 1;
  editor.buildSeq.set(key, seq);
  const entry = editor.members.get(key);
  if (!entry) return; // 这期间被去掉了
  const {member, opts} = entry;
  let build;
  if (!member.species) {
    build = {error: "还没选宝可梦"};
  } else {
    try {
      build = {info: await api("/api/build", {...opts.settings(), member: memberRequest(member)})};
    } catch (e) {
      build = {error: e.message};
    }
  }
  if (editor.buildSeq.get(key) !== seq) return; // 这期间又改过，以后面那次为准
  editor.builds.set(key, build);
  document.getElementById(`build-${key}`)?.replaceChildren(buildText(key));
  document.getElementById(`notes-${key}`)?.replaceChildren(...buildNotes(key));
}

/** 建配置的结果写成一行：CP、等级、IV、Mega 等级、HP、攻、防；出错时是错误信息。 */
function buildText(key) {
  const build = editor.builds.get(key);
  if (!build) return el("span", {class: "muted"}, "……");
  if (build.error) return el("span", {class: "bad"}, build.error);
  const info = build.info;
  const parts = [`CP ${info.cp}`, `${info.level} 级`, `IV ${info.ivs.join("/")}`];
  if (info.mega_level !== null) parts.push(`Mega 等级 ${info.mega_level}`);
  parts.push(`HP ${info.hp}`, `攻 ${info.atk.toFixed(1)}`, `防 ${info.def.toFixed(1)}`);
  return el("span", {}, parts.join(" · "));
}

/** 建配置的说明（等级怎么定的、招式池外的招……），放在"更多设置"里。 */
function buildNotes(key) {
  const info = editor.builds.get(key)?.info;
  return info ? info.notes.map((note) => el("li", {}, note)) : [];
}
