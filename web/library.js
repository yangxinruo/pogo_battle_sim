"use strict";
// 队伍库的列表（4f；4g 起"打一场"页和九宫格页共用，4h 起还有队伍对队伍页；在 editor.js 之后加载）：
// 筛选（只看现在的联盟、搜队名 / 宝可梦 / 说明）、每队一行（右边的按钮由页面定）、读不了的文件；
// 载入一队时要勾上哪些覆盖文件、状态栏里写什么；以及把一队存进队伍库（先问说明，同名的问过再覆盖）。
//
// 队伍库在仓库的 teams/，一队一个 TOML 文件（格式见 pogo_sim/team_library.py），读写都在服务器
// （GET /api/team-library、POST /api/team-library/save）。网页能列出、载入、存进去，不能删除（要删就手动删文件）。

/** 打开的队伍库面板的内容。lib 是 GET /api/team-library 的结果（还没读到时为 null）。opts：
 *  - league、leagueName：现在的联盟（CP 上限）和它的名字（"只看现在的联盟"用）
 *  - filter：{sameLeague, query}，由页面保存，这里直接改它
 *  - buttons(entry)：每队一行右边的按钮 */
function libraryPanel(lib, opts) {
  if (!lib) return [el("p", {class: "muted"}, "正在读队伍库……")];
  const filter = opts.filter;
  const list = el("div", {class: "library-list"});
  const refresh = () => list.replaceChildren(...libraryRows(lib, opts));
  const controls = el("div", {class: "row"},
    el("label", {}, el("input", {
      type: "checkbox",
      checked: filter.sameLeague,
      onchange: (e) => { filter.sameLeague = e.target.checked; refresh(); },
    }), ` 只看${opts.leagueName}`),
    el("input", {
      type: "search",
      placeholder: "搜队名、宝可梦、说明",
      value: filter.query,
      oninput: (e) => { filter.query = e.target.value; refresh(); },
    }),
    el("span", {class: "muted"}, `${lib.dir}：一共 ${lib.teams.length} 队。网页不能删除，要删就手动删文件。`),
  );
  refresh();
  const broken = lib.broken.length
    ? el("div", {class: "library-broken"}, el("div", {}, `读不了的文件（${lib.broken.length} 个）：`),
      lib.broken.map((b) => el("div", {class: "bad"}, `${b.file}：${b.error}`)))
    : null;
  return [controls, list, broken].filter(Boolean);
}

function libraryRows(lib, opts) {
  const filter = opts.filter;
  const words = normalizeSearch(filter.query).split(" ").filter(Boolean);
  const rows = lib.teams.filter((entry) => {
    if (filter.sameLeague && entry.league !== opts.league) return false;
    const text = normalizeSearch([entry.name, entry.note, entry.file,
      ...entry.team.member.flatMap((m) => [m.species, speciesName(m.species)])].join(" "));
    return words.every((word) => text.includes(word));
  });
  if (rows.length === 0) {
    return [el("p", {class: "muted"},
      lib.teams.length ? "没有符合筛选的队伍。" : "队伍库还是空的：在“打一场”页的一队上点“存进队伍库”。")];
  }
  return rows.map((entry) => el("div", {class: "library-row"},
    el("div", {class: "library-main"},
      el("b", {}, entry.name), " ",
      el("span", {class: "muted"}, `${entry.league_name} · ${entry.file}`),
      el("div", {}, entry.team.member.map((m) => speciesName(m.species)).join(" / ")),
      entry.note ? el("div", {class: "muted"}, entry.note) : null,
      entry.custom_files.length ? el("div", {class: "muted"}, `用到的覆盖文件：${entry.custom_files.join("、")}`) : null,
    ),
    el("span", {class: "library-buttons"}, opts.buttons(entry)),
  ));
}

/** 载入库里的一队之前：这一队用到的覆盖文件没勾的自动勾上；联盟不同只提示，不强制。
 *  current：现在勾着的覆盖文件；available：data/custom/ 里有的；league、leagueName：现在的联盟。
 *  返回 {customFiles: 勾上以后的覆盖文件（按 available 的顺序）, added: 新勾上的, notes: 状态栏里的提示}。 */
function libraryLoadPlan(entry, current, available, league, leagueName) {
  const missing = entry.custom_files.filter((name) => !current.includes(name));
  const added = missing.filter((name) => available.includes(name));
  const absent = missing.filter((name) => !available.includes(name));
  const notes = [];
  if (added.length) notes.push(`自动勾上了覆盖文件 ${added.join("、")}`);
  if (absent.length) notes.push(`这一队用到的覆盖文件 ${absent.join("、")} 不在 data/custom/ 里`);
  if (entry.league !== league) {
    notes.push(`这一队记的联盟是${entry.league_name}，现在是${leagueName}（不强制，按现在的联盟建配置）`);
  }
  return {customFiles: available.filter((name) => current.includes(name) || added.includes(name)), added, notes};
}

/** 把一队存进队伍库（POST /api/team-library/save）：先问说明；同名的文件已经有了，问过再覆盖。
 *  team：一队发给服务器的写法（editor.js 的 teamRequest）；settings：{league, season, custom_files}；
 *  leagueName：现在的联盟的名字。返回状态栏里写的话（点了取消时为 null）；服务器出错时抛出 Error。 */
async function saveTeamToLibrary(team, settings, leagueName) {
  const note = prompt(`把 ${team.name} 存进队伍库（仓库的 teams/，文件名按队名）。\n说明（可选，可以留空）：`, "");
  if (note === null) return null;
  const body = {...settings, team, note};
  let data = await api("/api/team-library/save", body);
  if (!data.saved) {
    const old = data.existing;
    const desc = old.error ?? `${old.name}，${old.league_name}：${old.team.member.map((m) => speciesName(m.species)).join(" / ")}` +
      (old.note ? `（${old.note}）` : "");
    if (!confirm(`队伍库里已经有 teams/${data.file}：\n${desc}\n\n覆盖吗？（teams/ 在 git 里：提交过的旧版本能找回，没提交的找不回）`)) {
      return "没有存";
    }
    data = await api("/api/team-library/save", {...body, overwrite: true});
  }
  const used = data.custom_files.length ? `，记下了用到的覆盖文件 ${data.custom_files.join("、")}` : "";
  return `已存进队伍库：teams/${data.file}（${leagueName}${used}）`;
}
