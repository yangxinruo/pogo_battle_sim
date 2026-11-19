// 用 PvPoke 源码生成 2b（IV 排名）的参考数据。
//
// 用法（在本仓库根目录运行）：
//   node tools/pvpoke_ref/export_iv_reference.js --pvpoke <PvPoke 仓库目录>
// 输出：tests/fixtures/pvpoke_iv_reference.json
//
// 每个用例调用 PvPoke 的 Pokemon.generateIVCombinations("overall", 1, 4096)，记录完整的排名顺序。
// pytest 只读输出的 JSON，不需要 Node。

"use strict";

const fs = require("fs");
const path = require("path");
const { loadPvPoke, evaluate } = require("./pvpoke_env.js");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const GAMEMASTER_PATH = path.join(REPO_ROOT, "data", "gamemaster.json");
const OUTPUT_PATH = path.join(REPO_ROOT, "tests", "fixtures", "pvpoke_iv_reference.json");

// 详细记录前几名（等级、CP、实际能力值、乘积），其余只记录顺序和等级。
const TOP_DETAIL_COUNT = 20;

// battleLevelCap：对战设置里的等级上限（PvPoke 默认 50）。宝可梦自己的上限可能不同（supermega 在 PvPoke 里是 52）。
const CASES = [
  { note: "常见：超级联盟", species: "azumarill", cp: 1500 },
  { note: "很多组合被 50 级上限挡住", species: "medicham", cp: 1500 },
  { note: "最佳伙伴：等级上限 51", species: "medicham", cp: 1500, battleLevelCap: 51 },
  { note: "普通雪妖女（Mega 雪妖女的原型）", species: "froslass", cp: 1500 },
  { note: "暗影，非传说：IV 下限 0", species: "swampert_shadow", cp: 1500 },
  { note: "传说：IV 下限 1", species: "registeel", cp: 1500 },
  { note: "暗影传说：IV 下限 6", species: "registeel_shadow", cp: 1500 },
  { note: "野外出现的传说（wildlegendary）：IV 下限 0", species: "latias", cp: 2500 },
  { note: "究极异兽：IV 下限 1", species: "nihilego", cp: 2500 },
  { note: "不能交换：IV 下限 10", species: "jirachi", cp: 1500 },
  { note: "levelFloor 15：部分组合在 15 级就超过 2500", species: "mewtwo_mega_x", cp: 2500 },
  { note: "levelFloor 15：全部组合在 15 级就超过 1500，排名为空", species: "mewtwo_mega_x", cp: 1500 },
  { note: "小小杯忽略 levelFloor（20）", species: "snom", cp: 500 },
  { note: "supermega 在 PvPoke 里等级上限 52：50 级到不了 2500", species: "sableye_mega", cp: 2500 },
  { note: "supermega 在超级联盟", species: "sableye_mega", cp: 1500 },
  { note: "大师联盟：全部在 50 级（supermega 不提到 52）", species: "clefable_mega", cp: 10000 },
  { note: "大师联盟，种族攻击 = 种族防御：攻防 IV 互换的组合乘积在数学上相等", species: "kingdra", cp: 10000 },
];

function parseArgs(argv) {
  const index = argv.indexOf("--pvpoke");
  if (index === -1 || !argv[index + 1]) {
    throw new Error("请用 --pvpoke <PvPoke 仓库目录> 指定 PvPoke 源码位置");
  }
  return { pvpokeDir: path.resolve(argv[index + 1]) };
}

// 在 PvPoke 环境里排名。输入输出都是普通 JSON 对象。
const PVPOKE_HELPERS = `
  var __rankIVs = function(spec){
    const battle = new Battle();
    battle.setCP(spec.cp);
    battle.setLevelCap(spec.battleLevelCap);
    // 宝可梦的等级上限在构造时从 battle 读取，所以要先设好 battle 再创建宝可梦。
    const poke = new Pokemon(spec.species, 0, battle);
    if (!poke.speciesId) { throw new Error("找不到宝可梦 " + spec.species); }
    poke.initialize(battle.getCP());
    const combinations = poke.generateIVCombinations("overall", 1, 4096);
    return {
      level_cap: poke.levelCap,
      level_floor: poke.baseLevelFloor,
      combinations: combinations.map(c => ({
        ivs: [c.ivs.atk, c.ivs.def, c.ivs.hp],
        level: c.level, cp: c.cp, atk: c.atk, def: c.def, hp: c.hp, overall: c.overall,
      })),
    };
  };
`;

// 一个 IV 组合编成 3 个十六进制字符（攻、防、HP 各一位），等级编成 2 个十六进制字符（等级 × 2）。
function encodeOrder(combinations) {
  return combinations.map(c => c.ivs.map(v => v.toString(16)).join("")).join("");
}

function encodeLevels(combinations) {
  return combinations.map(c => (c.level * 2).toString(16).padStart(2, "0")).join("");
}

function main() {
  const { pvpokeDir } = parseArgs(process.argv.slice(2));
  const { context, commit } = loadPvPoke(pvpokeDir, GAMEMASTER_PATH);
  evaluate(context, PVPOKE_HELPERS);

  const cases = CASES.map(c => {
    const spec = { species: c.species, cp: c.cp, battleLevelCap: c.battleLevelCap ?? 50 };
    const result = evaluate(context, `__rankIVs(${JSON.stringify(spec)})`);
    return {
      note: c.note,
      species: spec.species,
      cp: spec.cp,
      battle_level_cap: spec.battleLevelCap,
      pvpoke_level_cap: result.level_cap,
      pvpoke_level_floor: result.level_floor,
      count: result.combinations.length,
      order: encodeOrder(result.combinations),
      levels: encodeLevels(result.combinations),
      top: result.combinations.slice(0, TOP_DETAIL_COUNT),
    };
  });

  const output = {
    source: {
      description:
        "PvPoke 源码的 IV 排名（Pokemon.generateIVCombinations），由 tools/pvpoke_ref/export_iv_reference.js 生成。" +
        "order：按名次排列，每个组合 3 个十六进制字符（攻、防、HP IV）；" +
        "levels：同样顺序，每个组合 2 个十六进制字符（等级 × 2）；top：前几名的详细数值。",
      pvpoke_commit: commit,
      gamemaster: "data/gamemaster.json",
      generated_on: new Date().toISOString().slice(0, 10),
      license: "PvPoke 源码与数据为 MIT license",
    },
    cases,
  };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output) + "\n");
  console.log(`写入 ${path.relative(REPO_ROOT, OUTPUT_PATH)}：${cases.length} 个用例`);
  for (const c of cases) {
    console.log(`  ${c.species} ${c.cp}：${c.count} 个组合，等级上限 ${c.pvpoke_level_cap}，最低等级 ${c.pvpoke_level_floor}`);
  }
}

main();
