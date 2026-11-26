"use strict";
// 两个页面（index.html 打一场 3v3、stats.html 能力值排序）共用的小工具，在各页自己的脚本之前加载。
// 和其他脚本一样只负责显示，不算任何东西。

/** 建一个元素。attrs 里 on* 是事件，class 是类名；children 可以是元素、文字或数组。 */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

/** 下拉框。choices：[[值, 文字], ...]。 */
function select(choices, current, onChange, attrs = {}) {
  const node = el("select", {...attrs, onchange: (e) => onChange(e.target.value)},
    choices.map(([value, text]) => el("option", {value: String(value)}, text)));
  node.value = String(current ?? "");
  return node;
}

/** 调接口。body 为 undefined 时是 GET，否则 POST JSON。出错时抛出带服务器说明的 Error。 */
async function api(path, body) {
  const init = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  };
  const response = await fetch(path, init);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

/** 让浏览器把一段文字存成文件（下载报告、导出配置）。 */
function downloadText(filename, text, type = "text/plain") {
  const blob = new Blob([text], {type: `${type};charset=utf-8`});
  const url = URL.createObjectURL(blob);
  const link = el("a", {href: url, download: filename});
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function showError(message) {
  const box = document.getElementById("error");
  box.textContent = message;
  box.hidden = !message;
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

const TYPE_COLORS = {
  normal: "#a8a77a", fire: "#ee8130", water: "#6390f0", electric: "#f7d02c", grass: "#7ac74c", ice: "#96d9d6",
  fighting: "#c22e28", poison: "#a33ea1", ground: "#e2bf65", flying: "#a98ff3", psychic: "#f95587", bug: "#a6b91a",
  rock: "#b6a136", ghost: "#735797", dragon: "#6f35fc", dark: "#705746", steel: "#b7b7ce", fairy: "#d685ad",
};

/** 属性的小色点（每个属性一个）。 */
function typeDots(types) {
  return el("span", {class: "type-dots"},
    types.map((type) => el("i", {style: `background: ${TYPE_COLORS[type] ?? "#9ca3af"}`, title: type})));
}

/** 和 web_api.normalize_search 一样：小写、去掉重音、标点换成空格。 */
function normalizeSearch(text) {
  return text.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim();
}
