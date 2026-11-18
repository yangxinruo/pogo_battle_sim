// 用 PvPoke 源码生成 3a（伤害层）的参考数据：CPM 表、属性克制表、伤害用例。
//
// 用法（在本仓库根目录运行）：
//   node tools/pvpoke_ref/export_damage_reference.js --pvpoke <PvPoke 仓库目录>
// 输出：tests/fixtures/pvpoke_damage_reference.json
//
// pytest 只读输出的 JSON，不需要 Node。只有想重新生成参考数据时才需要运行这个脚本。

"use strict";

const fs = require("fs");
const path = require("path");
const { loadPvPoke, evaluate } = require("./pvpoke_env.js");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const GAMEMASTER_PATH = path.join(REPO_ROOT, "data", "gamemaster.json");
const OUTPUT_PATH = path.join(REPO_ROOT, "tests", "fixtures", "pvpoke_damage_reference.json");

// 随机用例的数量和种子。种子固定，所以每次生成的用例完全相同。
const RANDOM_CASE_COUNT = 400;
const RANDOM_SEED = 20261118;

// 手挑的用例：每个覆盖一种需要特别确认的情况。
// 宝可梦写法：[species, level, [攻IV, 防IV, HP IV]]；attackerAtkStage / defenderDefStage 是能力等级。
const HANDPICKED_CASES = [
  { note: "基础：有 STAB 的快招", attacker: ["azumarill", 43, [4, 15, 13]], defender: ["medicham", 49, [7, 15, 14]], move: "BUBBLE" },
  { note: "基础：无 STAB 的大招", attacker: ["azumarill", 43, [4, 15, 13]], defender: ["medicham", 49, [7, 15, 14]], move: "ICE_BEAM" },
  { note: "效果绝佳 1.6", attacker: ["medicham", 49, [7, 15, 14]], defender: ["registeel", 25, [15, 15, 15]], move: "COUNTER" },
  { note: "双重效果绝佳 1.6×1.6（冰打龙/地面）", attacker: ["mamoswine", 25, [10, 12, 8]], defender: ["garchomp", 20, [12, 15, 15]], move: "POWDER_SNOW" },
  { note: "双重抵抗 0.625×0.625（火打水/龙）", attacker: ["charizard", 30, [10, 10, 10]], defender: ["kingdra", 30, [10, 10, 10]], move: "FIRE_SPIN" },
  { note: "免疫 0.390625（幽灵打一般）", attacker: ["gengar", 28, [15, 0, 0]], defender: ["snorlax", 22, [0, 15, 15]], move: "SHADOW_CLAW" },
  { note: "免疫 × 弱点（电打地面/飞行）", attacker: ["pikachu", 40, [15, 15, 15]], defender: ["gligar", 40, [15, 15, 15]], move: "THUNDER_SHOCK" },
  { note: "弱点 × 抵抗（格斗打一般/飞行）", attacker: ["medicham", 49, [7, 15, 14]], defender: ["pidgeot", 25, [5, 5, 5]], move: "COUNTER" },
  { note: "暗影攻方", attacker: ["swampert_shadow", 20, [0, 14, 11]], defender: ["registeel", 25, [15, 15, 15]], move: "MUD_SHOT" },
  { note: "暗影守方", attacker: ["medicham", 49, [7, 15, 14]], defender: ["registeel_shadow", 25, [15, 15, 15]], move: "COUNTER" },
  { note: "暗影对暗影", attacker: ["machamp_shadow", 19, [3, 15, 15]], defender: ["swampert_shadow", 20, [0, 14, 11]], move: "DYNAMIC_PUNCH" },
  { note: "攻击 +4（8/4）", attacker: ["medicham", 49, [7, 15, 14]], defender: ["azumarill", 43, [4, 15, 13]], move: "COUNTER", attackerAtkStage: 4 },
  { note: "攻击 −4（4/8）", attacker: ["medicham", 49, [7, 15, 14]], defender: ["azumarill", 43, [4, 15, 13]], move: "COUNTER", attackerAtkStage: -4 },
  { note: "防御 +2 / 攻击 +1", attacker: ["medicham", 49, [7, 15, 14]], defender: ["azumarill", 43, [4, 15, 13]], move: "POWER_UP_PUNCH", attackerAtkStage: 1, defenderDefStage: 2 },
  { note: "防御 −3 / 攻击 −1", attacker: ["azumarill", 43, [4, 15, 13]], defender: ["medicham", 49, [7, 15, 14]], move: "PLAY_ROUGH", attackerAtkStage: -1, defenderDefStage: -3 },
  { note: "暗影 + 能力等级叠加", attacker: ["machamp_shadow", 19, [3, 15, 15]], defender: ["registeel_shadow", 25, [15, 15, 15]], move: "COUNTER", attackerAtkStage: 3, defenderDefStage: -2 },
  { note: "威力 0 的招式：伤害 = 1", attacker: ["magikarp", 1, [0, 0, 0]], defender: ["snorlax", 40, [15, 15, 15]], move: "SPLASH" },
  { note: "51 级高攻", attacker: ["mewtwo", 51, [15, 15, 15]], defender: ["registeel", 51, [15, 15, 15]], move: "PSYSTRIKE" },
  { note: "Mega 专属招式，Mega 等级 1", attacker: ["mewtwo_mega_x", 20, [15, 15, 15]], defender: ["registeel", 25, [15, 15, 15]], move: "DYNAMIC_PUNCH_PLUS", megaLevel: 1 },
  { note: "Mega 专属招式，Mega 等级 2", attacker: ["mewtwo_mega_x", 20, [15, 15, 15]], defender: ["registeel", 25, [15, 15, 15]], move: "DYNAMIC_PUNCH_PLUS", megaLevel: 2 },
  { note: "Mega 专属招式，Mega 等级 3", attacker: ["mewtwo_mega_x", 20, [15, 15, 15]], defender: ["registeel", 25, [15, 15, 15]], move: "DYNAMIC_PUNCH_PLUS", megaLevel: 3 },
  { note: "Mega 专属招式，Mega 等级 4", attacker: ["mewtwo_mega_x", 20, [15, 15, 15]], defender: ["registeel", 25, [15, 15, 15]], move: "DYNAMIC_PUNCH_PLUS", megaLevel: 4 },
  { note: "Mega 的普通招式不吃加成", attacker: ["mewtwo_mega_x", 20, [15, 15, 15]], defender: ["registeel", 25, [15, 15, 15]], move: "DYNAMIC_PUNCH", megaLevel: 4 },
  // MOONBLAST_PLUS 是 19 个 "+" 招式里唯一没有 isMegaMove 标记的，PvPoke 因此不给它加成。
  // 疑似 PvPoke 数据遗漏（docs/mechanics.md 待确认问题）。这个用例把现状钉住。
  { note: "Moonblast+ 没有 isMegaMove 标记：不加成", attacker: ["clefable_mega", 20, [15, 15, 15]], defender: ["medicham", 49, [7, 15, 14]], move: "MOONBLAST_PLUS", megaLevel: 4 },
  // 下面 4 个落在取整边界上：常数用精确的 1.3 / 1.2 / 1.6 而不是 float32 值，伤害会差 1。
  // 是在 Python 里搜索 40 万个随机组合找到的（攻守同等级时攻防比比较"整"，容易碰上）。
  { note: "float32 边界", attacker: ["hatenna", 42, [12, 12, 5]], defender: ["steenee", 42, [2, 5, 14]], move: "DAZZLING_GLEAM" },
  { note: "float32 边界", attacker: ["jangmo_o", 18.5, [8, 2, 1]], defender: ["blaziken", 18.5, [5, 2, 11]], move: "DRAGON_PULSE" },
  { note: "float32 边界", attacker: ["solosis_shadow", 23.5, [10, 2, 11]], defender: ["bulbasaur", 23.5, [6, 6, 13]], move: "THUNDER" },
  { note: "float32 边界", attacker: ["sliggoo_hisuian", 28, [15, 12, 3]], defender: ["vigoroth", 28, [0, 11, 10]], move: "WATER_PULSE" },
];

// 一个简单的可复现随机数生成器（mulberry32），返回 [0, 1)。
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function parseArgs(argv) {
  const index = argv.indexOf("--pvpoke");
  if (index === -1 || !argv[index + 1]) {
    throw new Error("请用 --pvpoke <PvPoke 仓库目录> 指定 PvPoke 源码位置");
  }
  return { pvpokeDir: path.resolve(argv[index + 1]) };
}

// 在 PvPoke 环境里定义计算函数。输入输出都用普通 JSON 对象，避免跨环境传 PvPoke 的对象。
const PVPOKE_HELPERS = `
  var __makePokemon = function(battle, spec, index){
    const p = new Pokemon(spec.species, index, battle);
    p.initialize(battle.getCP());
    p.setLevel(spec.level);
    p.setIV("atk", spec.ivs[0]);
    p.setIV("def", spec.ivs[1]);
    p.setIV("hp", spec.ivs[2]);
    return p;
  };

  var __findMove = function(pokemon, moveId){
    const pools = [pokemon.fastMovePool, pokemon.chargedMovePool, pokemon.extraChargedMovePool];
    for (const pool of pools){
      const found = pool.find(m => m.moveId == moveId);
      if (found) { return found; }
    }
    // 不在这只宝可梦的招式池里：直接从 gamemaster 取一份（伤害公式不关心会不会这个招）。
    const data = GameMaster.getInstance().getMoveById(moveId);
    if (!data) { throw new Error("找不到招式 " + moveId); }
    return data;
  };

  var __computeDamage = function(c){
    const battle = new Battle();
    battle.setCP(10000); // 不让联盟上限干扰手动指定的等级和 IV
    const attacker = __makePokemon(battle, c.attacker, 0);
    const defender = __makePokemon(battle, c.defender, 1);
    if (c.megaLevel !== null) { attacker.setMegaLevel(c.megaLevel); }
    battle.setNewPokemon(attacker, 0, false);
    battle.setNewPokemon(defender, 1, false);
    attacker.statBuffs = [c.attackerAtkStage, 0];
    defender.statBuffs = [0, c.defenderDefStage];

    const move = __findMove(attacker, c.move);
    move.stab = attacker.getStab(move);

    return {
      damage: DamageCalculator.damage(attacker, defender, move),
      attack: attacker.getEffectiveStat(0),
      defense: defender.getEffectiveStat(1),
      effectiveness: defender.typeEffectiveness[move.type],
      stab: move.stab,
      attacker_cp: attacker.cp,
      defender_cp: defender.cp,
    };
  };

  var __eligibleSpecies = function(){
    // 随机用例只用已发布、没有形态变化的宝可梦（形态变化的特殊规则不在 3a 范围内）。
    return GameMaster.getInstance().data.pokemon
      .filter(p => p.released && !p.formChange)
      .map(p => p.speciesId)
      .sort();
  };

  var __movesOf = function(speciesId){
    const battle = new Battle();
    const p = new Pokemon(speciesId, 0, battle);
    // 普通招式的 damageMethod 是 "default"；Gulp Missile 之类按最大 HP 百分比算的不在 3a 范围内。
    const ids = [...p.fastMovePool, ...p.chargedMovePool, ...p.extraChargedMovePool]
      .filter(m => m.damageMethod === "default")
      .map(m => m.moveId);
    return { moves: [...new Set(ids)].sort(), isMega: p.hasTag("mega") };
  };
`;

function normalizeCase(raw) {
  // 把手写的简写形式转成统一格式。
  const side = ([species, level, ivs]) => ({ species, level, ivs });
  return {
    note: raw.note,
    attacker: side(raw.attacker),
    defender: side(raw.defender),
    move: raw.move,
    attackerAtkStage: raw.attackerAtkStage ?? 0,
    defenderDefStage: raw.defenderDefStage ?? 0,
    megaLevel: raw.megaLevel ?? null,
  };
}

function makeRandomCases(context, count, seed) {
  const random = mulberry32(seed);
  const pick = (array) => array[Math.floor(random() * array.length)];
  const randomInt = (low, high) => low + Math.floor(random() * (high - low + 1)); // 含两端
  const randomLevel = () => 1 + randomInt(0, 98) / 2; // 1 到 50，步长 0.5
  const randomIvs = () => [randomInt(0, 15), randomInt(0, 15), randomInt(0, 15)];
  const randomStage = () => (random() < 0.5 ? 0 : randomInt(-4, 4));

  const species = evaluate(context, "__eligibleSpecies()");
  const cases = [];
  const maxAttempts = count * 10; // 防止因为 bug 死循环
  for (let attempt = 0; cases.length < count; attempt++) {
    if (attempt >= maxAttempts) {
      throw new Error(`尝试 ${maxAttempts} 次只凑出 ${cases.length} 个随机用例，检查 __movesOf`);
    }
    const attackerId = pick(species);
    const info = evaluate(context, `__movesOf(${JSON.stringify(attackerId)})`);
    if (info.moves.length === 0) {
      continue;
    }
    cases.push({
      note: "随机",
      attacker: { species: attackerId, level: randomLevel(), ivs: randomIvs() },
      defender: { species: pick(species), level: randomLevel(), ivs: randomIvs() },
      move: pick(info.moves),
      attackerAtkStage: randomStage(),
      defenderDefStage: randomStage(),
      megaLevel: info.isMega ? randomInt(1, 4) : null,
    });
  }
  return cases;
}

function main() {
  const { pvpokeDir } = parseArgs(process.argv.slice(2));
  const { context, commit } = loadPvPoke(pvpokeDir, GAMEMASTER_PATH);
  evaluate(context, PVPOKE_HELPERS);

  // CPM 表：1 到 55 级，步长 0.5
  const levels = [];
  for (let doubled = 2; doubled <= 110; doubled++) {
    levels.push(doubled / 2);
  }
  const cpm = evaluate(
    context,
    `(function(){ const p = new Pokemon("bulbasaur", 0, new Battle());
       return ${JSON.stringify(levels)}.map(l => [l, p.getCPMByLevel(l)]); })()`
  );

  // 属性克制：每种招式属性 × 每种单属性和双属性组合
  const types = evaluate(context, "Pokemon.getAllTypes(true)");
  const defenderTypeSets = [];
  for (let i = 0; i < types.length; i++) {
    defenderTypeSets.push([types[i]]);
    for (let j = i + 1; j < types.length; j++) {
      defenderTypeSets.push([types[i], types[j]]);
    }
  }
  const typeEffectiveness = [];
  for (const defenderTypes of defenderTypeSets) {
    for (const moveType of types) {
      typeEffectiveness.push({
        move_type: moveType,
        defender_types: defenderTypes,
        value: evaluate(
          context,
          `DamageCalculator.getEffectiveness(${JSON.stringify(moveType)}, ${JSON.stringify(defenderTypes)})`
        ),
      });
    }
  }

  // 伤害用例
  const cases = [
    ...HANDPICKED_CASES.map(normalizeCase),
    ...makeRandomCases(context, RANDOM_CASE_COUNT, RANDOM_SEED),
  ];
  const damageCases = cases.map((c) => ({
    note: c.note,
    attacker: { ...c.attacker, atk_stage: c.attackerAtkStage, mega_level: c.megaLevel },
    defender: { ...c.defender, def_stage: c.defenderDefStage },
    move: c.move,
    expected: evaluate(context, `__computeDamage(${JSON.stringify(c)})`),
  }));

  const output = {
    source: {
      description: "PvPoke 源码计算的参考值，由 tools/pvpoke_ref/export_damage_reference.js 生成",
      pvpoke_commit: commit,
      gamemaster: "data/gamemaster.json",
      generated_on: new Date().toISOString().slice(0, 10),
      random_seed: RANDOM_SEED,
      license: "PvPoke 源码与数据为 MIT license",
    },
    cpm,
    type_effectiveness: typeEffectiveness,
    damage_cases: damageCases,
  };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output, null, 1) + "\n");
  console.log(
    `写入 ${path.relative(REPO_ROOT, OUTPUT_PATH)}：CPM ${cpm.length} 项，克制 ${typeEffectiveness.length} 项，伤害用例 ${damageCases.length} 个`
  );
}

main();
