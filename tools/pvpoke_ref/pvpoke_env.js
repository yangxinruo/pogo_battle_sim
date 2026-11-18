// 在 Node 里加载 PvPoke 的对战代码，用来生成参考数据（tests/fixtures/）。
//
// PvPoke 是给浏览器写的：脚本之间靠全局变量互相引用，数据用 jQuery 的 $.ajax 加载。
// 这里用 Node 的 vm 模块建一个"假浏览器"环境：
//   - $ 是一个什么都不做的替身，只有 $.ajax 真正干活：直接读本地的 gamemaster.json；
//   - host / webRoot / settings / window 给最小的值，够这几份脚本运行即可。
// 只加载对战需要的脚本，不加载界面代码。
//
// PvPoke 源码本身不在本仓库里（不 fork、不入库），路径由调用方传入。

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

// 按依赖顺序加载。路径相对于 PvPoke 仓库根目录。
const SCRIPTS = [
  "src/js/GameMaster.js",
  "src/js/pokemon/Pokemon.js",
  "src/js/pokemon/Player.js",
  "src/js/battle/DamageCalculator.js",
  "src/js/battle/timeline/TimelineEvent.js",
  "src/js/battle/timeline/TimelineAction.js",
  "src/js/battle/actions/ActionLogic.js",
  "src/js/battle/Battle.js",
];

// 一个可以无限链式调用的替身：$(...).eq(2).insertAfter(...) 之类的界面操作全部变成空操作。
function makeChainableStub() {
  const target = function () {};
  const stub = new Proxy(target, {
    get: (_t, prop) => (prop === Symbol.toPrimitive ? () => "" : stub),
    apply: () => stub,
  });
  return stub;
}

function readPvPokeCommit(pvpokeDir) {
  // 本地仓库是 detached HEAD（直接 checkout 某个 commit），HEAD 文件里就是 commit hash。
  const head = fs.readFileSync(path.join(pvpokeDir, ".git", "HEAD"), "utf8").trim();
  if (/^[0-9a-f]{40}$/.test(head)) {
    return head;
  }
  throw new Error(`无法从 .git/HEAD 读出 commit hash：${head}`);
}

/**
 * 建立 PvPoke 运行环境。
 * @param {string} pvpokeDir PvPoke 仓库根目录
 * @param {string} gamemasterPath 要使用的 gamemaster.json（用本仓库 data/ 里的快照）
 * @returns {{context: object, commit: string}} context 里可以拿到 Pokemon、Battle、DamageCalculator 等
 */
function loadPvPoke(pvpokeDir, gamemasterPath) {
  const gamemasterData = JSON.parse(fs.readFileSync(gamemasterPath, "utf8"));
  const chain = makeChainableStub();

  const $ = function () {
    return chain;
  };
  // GameMaster.js 只用 $.ajax 加载 gamemaster。浏览器里它是异步的：回调执行时，
  // GameMaster 的 createInstance 已经把所有方法定义完了。所以这里先把回调存起来，
  // 等 getInstance() 返回后再执行（见下面的 flushPendingRequests）。
  const pendingRequests = [];
  $.ajax = function (options) {
    pendingRequests.push(() => options.success(gamemasterData));
  };
  const flushPendingRequests = () => {
    while (pendingRequests.length > 0) {
      pendingRequests.shift()();
    }
  };

  const context = {
    console,
    $,
    jQuery: $,
    host: "http://localhost/", // 含 localhost 时 GameMaster 不会去找 .min.json（反正我们不联网）
    webRoot: "",
    siteVersion: "local",
    settings: {
      gamemaster: "gamemaster",
      hardMovesetLinks: false,
      colorblindMode: false,
    },
    window: {
      location: { href: "http://localhost/" },
      localStorage: { getItem: () => null, setItem: () => {} },
    },
  };
  vm.createContext(context);

  for (const relative of SCRIPTS) {
    const file = path.join(pvpokeDir, relative);
    const code = fs.readFileSync(file, "utf8");
    vm.runInContext(code, context, { filename: relative });
  }

  // 先触发一次 gamemaster 加载，再执行被推迟的回调，之后才能创建宝可梦。
  vm.runInContext("GameMaster.getInstance()", context);
  flushPendingRequests();

  return { context, commit: readPvPokeCommit(pvpokeDir) };
}

/**
 * 在 PvPoke 环境里求值一段表达式（class 声明不挂在 context 对象上，所以统一通过求值拿）。
 */
function evaluate(context, expression) {
  return vm.runInContext(expression, context);
}

module.exports = { loadPvPoke, evaluate };
