// 用 PvPoke 源码生成 3b（回合结算）的参考数据：整场 1v1 的逐回合状态。
//
// 每一场的做法：
//   1. 让 PvPoke 的 AI 正常模拟一场，得到时间线；
//   2. 用 PvPoke 自己的 setSandboxMode(true) 把时间线转成"剧本"（哪一回合放哪个大招、开没开盾、
//      概率性能力变化有没有触发）；
//   3. 在沙盒模式下按剧本重放，逐回合记录双方的 HP、能量、冷却、能力等级、盾数。
// 第 3 步的结果和第 1 步应该完全相同（脚本会检查）。Python 测试用同一个剧本驱动我们的引擎，逐回合对比。
//
// 用法（在本仓库根目录运行）：
//   node tools/pvpoke_ref/export_battle_reference.js --pvpoke <PvPoke 仓库目录>
// 输出：tests/fixtures/pvpoke_battle_reference.json

"use strict";

const fs = require("fs");
const path = require("path");
const { loadPvPoke, evaluate } = require("./pvpoke_env.js");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const GAMEMASTER_PATH = path.join(REPO_ROOT, "data", "gamemaster.json");
const OUTPUT_PATH = path.join(REPO_ROOT, "tests", "fixtures", "pvpoke_battle_reference.json");

// 对局清单。每个对局按 SHIELD_SETUPS 里的每种盾数各跑一场，extraShields 是额外加跑的盾数组合。
// 宝可梦写法：[species, fast, [charged...]]；等级和 IV 用 PvPoke 该联盟的默认值。
const MATCHUPS = [
  { note: "基础：3 回合快招对 2 回合快招", cp: 1500,
    pokemon: [["azumarill", "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"]], ["medicham", "COUNTER", ["ICE_PUNCH", "PSYCHIC"]]],
    extraShields: [[2, 0], [0, 2]] },
  { note: "必定提升自己攻击（Power-Up Punch）", cp: 1500,
    pokemon: [["medicham", "COUNTER", ["POWER_UP_PUNCH", "ICE_PUNCH"]], ["registeel", "LOCK_ON", ["FOCUS_BLAST", "ZAP_CANNON"]]] },
  { note: "1 回合对 1 回合；Moonblast 10% 降对手攻击", cp: 1500,
    pokemon: [["registeel", "LOCK_ON", ["FOCUS_BLAST", "ZAP_CANNON"]], ["altaria", "DRAGON_BREATH", ["SKY_ATTACK", "MOONBLAST"]]] },
  { note: "2 回合对 1 回合", cp: 1500,
    pokemon: [["swampert", "MUD_SHOT", ["HYDRO_CANNON", "EARTHQUAKE"]], ["walrein", "POWDER_SNOW", ["ICICLE_SPEAR", "EARTHQUAKE"]]] },
  { note: "暗影；Close Combat 降自己防御", cp: 1500,
    pokemon: [["machamp_shadow", "COUNTER", ["CLOSE_COMBAT", "ROCK_SLIDE"]], ["registeel", "LOCK_ON", ["FOCUS_BLAST", "ZAP_CANNON"]]] },
  { note: "Night Slash 12.5% 概率；Obstruct 同时改双方", cp: 1500,
    pokemon: [["obstagoon", "COUNTER", ["NIGHT_SLASH", "OBSTRUCT"]], ["medicham", "COUNTER", ["ICE_PUNCH", "PSYCHIC"]]],
    extraShields: [[2, 0], [0, 2]] },
  { note: "4 回合长快招；Lunge 必定降对手攻击", cp: 1500,
    pokemon: [["galvantula", "VOLT_SWITCH", ["LUNGE", "DISCHARGE"]], ["azumarill", "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"]]] },
  { note: "Ancient Power 10% 概率提升双项", cp: 1500,
    pokemon: [["mamoswine", "POWDER_SNOW", ["AVALANCHE", "ANCIENT_POWER"]], ["altaria", "DRAGON_BREATH", ["SKY_ATTACK", "MOONBLAST"]]] },
  { note: "镜像：攻击相等（CMP 平手，双方大招都生效）", cp: 1500,
    pokemon: [["azumarill", "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"]], ["azumarill", "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"]]] },
  { note: "幽灵/草对地面/水", cp: 1500,
    pokemon: [["trevenant", "SHADOW_CLAW", ["SEED_BOMB", "SHADOW_BALL"]], ["swampert", "MUD_SHOT", ["HYDRO_CANNON", "EARTHQUAKE"]]] },
  { note: "高耐久长对局（能量溢出）", cp: 1500,
    pokemon: [["lickitung", "LICK", ["BODY_SLAM", "POWER_WHIP"]], ["umbreon", "SNARL", ["FOUL_PLAY", "LAST_RESORT"]]] },
  { note: "Brave Bird 降自己防御", cp: 1500,
    pokemon: [["skarmory", "AIR_SLASH", ["BRAVE_BIRD", "SKY_ATTACK"]], ["medicham", "COUNTER", ["ICE_PUNCH", "PSYCHIC"]]] },
  { note: "Icy Wind 必定降对手攻击", cp: 1500,
    pokemon: [["dewgong", "ICE_SHARD", ["ICY_WIND", "DRILL_RUN"]], ["swampert", "MUD_SHOT", ["HYDRO_CANNON", "EARTHQUAKE"]]] },
  { note: "5 回合快招（Incinerate）", cp: 1500,
    pokemon: [["typhlosion", "INCINERATE", ["BLAST_BURN", "THUNDER_PUNCH"]], ["registeel", "LOCK_ON", ["FOCUS_BLAST", "ZAP_CANNON"]]] },
  { note: "超级联盟", cp: 2500,
    pokemon: [["giratina_altered", "SHADOW_CLAW", ["DRAGON_CLAW", "SHADOW_SNEAK"]], ["registeel", "LOCK_ON", ["FOCUS_BLAST", "ZAP_CANNON"]]] },
  { note: "大师联盟：Mega 第三个大招，Mega 等级 4", cp: 10000,
    pokemon: [["mewtwo_mega_x", "PSYCHO_CUT", ["FOCUS_BLAST", "PSYSTRIKE", "DYNAMIC_PUNCH_PLUS"]], ["dialga", "DRAGON_BREATH", ["DRACO_METEOR", "IRON_HEAD"]]] },
];

const SHIELD_SETUPS = [[0, 0], [1, 1], [2, 2]];

function parseArgs(argv) {
  const index = argv.indexOf("--pvpoke");
  if (index === -1 || !argv[index + 1]) {
    throw new Error("请用 --pvpoke <PvPoke 仓库目录> 指定 PvPoke 源码位置");
  }
  return { pvpokeDir: path.resolve(argv[index + 1]) };
}

// 在 PvPoke 环境里跑一场。输入输出都是普通 JSON 对象。
const PVPOKE_HELPERS = `
  var __setupBattle = function(spec){
    const battle = new Battle();
    battle.setCP(spec.cp);
    const pokemon = spec.pokemon.map((p, i) => {
      const poke = new Pokemon(p.species, i, battle);
      poke.initialize(battle.getCP());
      poke.selectMove("fast", p.fast);
      p.charged.forEach((moveId, k) => poke.selectMove("charged", moveId, k));
      if (poke.fastMove.moveId != p.fast) { throw new Error(p.species + " 选不到快招 " + p.fast); }
      p.charged.forEach((moveId, k) => {
        if (!poke.chargedMoves[k] || poke.chargedMoves[k].moveId != moveId) {
          throw new Error(p.species + " 选不到大招 " + moveId);
        }
      });
      poke.setShields(p.shields);
      battle.setNewPokemon(poke, i, false);
      return poke;
    });
    return { battle, pokemon };
  };

  var __simplifyTimeline = function(timeline){
    // 只保留和结算有关的事件：招式、开盾、倒下（去掉 "tap" 之类的显示用事件）。
    return timeline
      .filter(e => e.type.startsWith("fast") || e.type.startsWith("charged") || e.type == "shield" || e.type == "faint")
      .map(e => ({ type: e.type, name: e.name, actor: e.actor, turn: e.turn, values: e.values }));
  };

  var __snapshot = function(turn, pokemon){
    return {
      turn,
      hp: pokemon.map(p => p.hp),
      energy: pokemon.map(p => p.energy),
      cooldown: pokemon.map(p => p.cooldown / 500),
      stages: pokemon.map(p => [p.statBuffs[0], p.statBuffs[1]]),
      shields: pokemon.map(p => p.shields),
    };
  };

  var __runBattle = function(spec){
    const { battle, pokemon } = __setupBattle(spec);

    // 1. AI 正常模拟
    const aiTimeline = __simplifyTimeline(battle.simulate());
    const aiRatings = battle.getBattleRatings();

    // 2. 转成剧本
    battle.setSandboxMode(true);
    const script = battle.getActions().map(a => ({
      actor: a.actor,
      turn: a.turn,
      move: pokemon[a.actor].chargedMoves[a.value].moveId,
      shielded: a.settings.shielded,
      apply_effect: a.settings.buffs,
    }));

    // 3. 按剧本重放，逐回合记录（循环条件与 Battle.simulate() 相同）
    battle.start();
    const snapshots = [];
    do {
      const turn = battle.getTurns();
      battle.step();
      snapshots.push(__snapshot(turn, pokemon));
    } while (pokemon[0].hp > 0 && pokemon[1].hp > 0 && battle.getDuration() <= 240000);

    const replayTimeline = __simplifyTimeline(battle.getTimeline());
    const ratings = [pokemon[0].getBattleRating(), pokemon[1].getBattleRating()];

    // 招式事件：名字换成招式 ID；被挡下的大招前面紧跟着守方的 shield 事件
    const moveIdByName = pokemon.map(p => {
      const map = {};
      map[p.fastMove.name] = p.fastMove.moveId;
      p.chargedMoves.forEach(m => { map[m.name] = m.moveId; });
      return map;
    });
    const events = [];
    replayTimeline.forEach((e, i) => {
      if (e.type == "faint") {
        events.push({ kind: "faint", turn: e.turn, actor: e.actor });
      } else if (e.type.startsWith("fast") || e.type.startsWith("charged")) {
        const previous = replayTimeline[i - 1];
        events.push({
          kind: "move",
          turn: e.turn,
          actor: e.actor,
          move: moveIdByName[e.actor][e.name],
          charged: e.type.startsWith("charged"),
          damage: e.values[0],
          shielded: !!(previous && previous.type == "shield" && previous.actor != e.actor),
        });
      }
    });

    return {
      pokemon: pokemon.map((p, i) => ({
        species: p.speciesId,
        level: p.level,
        ivs: [p.ivs.atk, p.ivs.def, p.ivs.hp],
        cp: p.cp,
        hp: p.stats.hp,
        fast: p.fastMove.moveId,
        charged: p.chargedMoves.map(m => m.moveId),
        shields: spec.pokemon[i].shields,
        mega_level: p.hasTag("mega") ? p.megaLevel : null,
      })),
      script,
      events,
      snapshots,
      result: { ratings, turns: snapshots.length, duration_ms: battle.getDuration() },
      replay_matches_ai: JSON.stringify(aiTimeline) == JSON.stringify(replayTimeline)
        && JSON.stringify(aiRatings) == JSON.stringify(ratings),
    };
  };
`;

function main() {
  const { pvpokeDir } = parseArgs(process.argv.slice(2));
  const { context, commit } = loadPvPoke(pvpokeDir, GAMEMASTER_PATH);
  evaluate(context, PVPOKE_HELPERS);

  const battles = [];
  for (const matchup of MATCHUPS) {
    const setups = [...SHIELD_SETUPS, ...(matchup.extraShields ?? [])];
    for (const shields of setups) {
      const spec = {
        cp: matchup.cp,
        pokemon: matchup.pokemon.map(([species, fast, charged], i) => ({ species, fast, charged, shields: shields[i] })),
      };
      const outcome = evaluate(context, `__runBattle(${JSON.stringify(spec)})`);
      if (!outcome.replay_matches_ai) {
        throw new Error(`沙盒重放与 AI 模拟不一致：${matchup.note} ${JSON.stringify(shields)}`);
      }
      delete outcome.replay_matches_ai;
      const names = matchup.pokemon.map(p => p[0]).join(" vs ");
      battles.push({ id: `${names} ${shields[0]}-${shields[1]}`, note: matchup.note, cp: matchup.cp, ...outcome });
    }
  }

  const output = {
    source: {
      description: "PvPoke 源码模拟的整场对战（AI 决策 → 沙盒剧本重放），由 tools/pvpoke_ref/export_battle_reference.js 生成",
      pvpoke_commit: commit,
      gamemaster: "data/gamemaster.json",
      generated_on: new Date().toISOString().slice(0, 10),
      license: "PvPoke 源码与数据为 MIT license",
    },
    battles,
  };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output) + "\n");
  const totalTurns = battles.reduce((sum, b) => sum + b.snapshots.length, 0);
  console.log(`写入 ${path.relative(REPO_ROOT, OUTPUT_PATH)}：${battles.length} 场，共 ${totalTurns} 个回合`);
}

main();
