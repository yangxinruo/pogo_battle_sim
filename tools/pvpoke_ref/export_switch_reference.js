// 用 PvPoke 源码生成 3v3-c（换人结算）的参考数据：按剧本打的队伍对战，逐回合记录双方全队的状态。
//
// PvPoke 没有确定性的 3v3 模拟：换人只出现在实时运行的训练模式里（docs/mechanics.md 13.1）。这里的做法：
//   - 结算用 PvPoke 自己的 Battle.step()（模拟模式 + 沙盒剧本）。换人行动的优先级（+20，大招后的空回合 −40）、
//     有效性检查（冷却为 0 且换人计时为 0，或自己已倒下）、换人本身（processAction 的 switch 部分：
//     开始计时、能力等级清零、倒下后换人时对手冷却设 500）都是 PvPoke 的代码。
//   - 训练模式才有的几件事，照抄训练模式的代码写成"胶水"（见下面 __runScenario 里标了【胶水】的地方）：
//     1. 队伍：用 PvPoke 的 Player 对象（全队的盾、换人计时）。换上来时同步全队的盾——训练模式的
//        setNewPokemon 是这样做的，模拟模式不做。
//     2. 倒下：在场的倒下、双方都还有宝可梦时，清空排队中的行动、在场的冷却归零，下一回合倒下的一方换人
//        （照抄 step() 末尾 mode == "emulate" 的分支）。
//     3. 计时：训练模式是实时的，大招期间、选人期间换人计时照走；模拟模式的 step() 每回合只扣 500 毫秒。
//        所以每回合开头再扣掉"上一回合的对战时间 − 500"，换人回合之前再扣掉选人的等待
//        （本项目的 Q14 规则：大招按 PvPoke 的对战时间计，选人等待由剧本给定）。
//   - 剧本里的换人：沙盒模式的 getTurnAction 只认大招剧本（它用 chargedMoves.length > value 过滤），
//     所以换人由下面包装过的 getTurnAction 返回，优先级的算法与 getTurnAction 相同（+20）。
//   - 记录：包装 useMove、processAction，记下每一招打的是哪一只、每次换人从哪只换到哪只（模拟模式的
//     时间线不记换人，也不知道挨打的是队伍里的第几只）。
//
// 这样对照的是"给定剧本和换人计时，换人怎么结算"。计时规则本身（大招算几秒、选人等多久）是用户定的（Q14），
// 不是拿来和 PvPoke 对照的。
//
// 用法（在本仓库根目录运行）：
//   node tools/pvpoke_ref/export_switch_reference.js --pvpoke <PvPoke 仓库目录>
// 输出：tests/fixtures/pvpoke_switch_reference.json

"use strict";

const fs = require("fs");
const path = require("path");
const { loadPvPoke, evaluate } = require("./pvpoke_env.js");

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const GAMEMASTER_PATH = path.join(REPO_ROOT, "data", "gamemaster.json");
const OUTPUT_PATH = path.join(REPO_ROOT, "tests", "fixtures", "pvpoke_switch_reference.json");

// 常用的几只（等级和 IV 用 PvPoke 该联盟的默认值）。快招回合数写在旁边。
const REGISTEEL = { species: "registeel", fast: "LOCK_ON", charged: ["FOCUS_BLAST", "ZAP_CANNON"] }; // 1 回合
const AZUMARILL = { species: "azumarill", fast: "BUBBLE", charged: ["ICE_BEAM", "PLAY_ROUGH"] }; // 3 回合
const MEDICHAM = { species: "medicham", fast: "COUNTER", charged: ["ICE_PUNCH", "POWER_UP_PUNCH"] }; // 2 回合
const SWAMPERT = { species: "swampert", fast: "MUD_SHOT", charged: ["HYDRO_CANNON", "EARTHQUAKE"] }; // 2 回合
const GALVANTULA = { species: "galvantula", fast: "VOLT_SWITCH", charged: ["LUNGE", "DISCHARGE"] }; // 4 回合
const ALTARIA = { species: "altaria", fast: "DRAGON_BREATH", charged: ["SKY_ATTACK", "MOONBLAST"] }; // 1 回合
const TREVENANT = { species: "trevenant", fast: "SHADOW_CLAW", charged: ["SEED_BOMB", "SHADOW_BALL"] }; // 2 回合
const WALREIN = { species: "walrein", fast: "POWDER_SNOW", charged: ["ICICLE_SPEAR", "EARTHQUAKE"] }; // 2 回合

// 对局清单。
//   teams[i].members：按出场顺序，第一只是首发。hp、energy 是开局时的 HP 和能量（不写就是满 HP、0 能量）。
//   teams[i].switch_timer_ms：开局时的换人计时（真实对战开局都是 0；这里只为缩短场景）。
//   charged：{actor, turn, move, shielded（守方开不开盾）, apply_effect（概率效果是否触发）}
//   switches：{actor, turn, to}——这一回合换上第 to 只（主动换人；大招后的空回合、对手选人的回合是 0 回合换人）
//   replacements：{actor, turn, to, wait_ms}——倒下后的换人回合换上第 to 只，选人时等 wait_ms。
//                 没写的话换上队伍里排在最前、没倒下的那只，不等待（与 ScriptedPolicy 的默认相同）。
//   max_turns：最多打几回合（不写就打到一方全队倒下或时间到）。
//   known_difference：已知和 PvPoke 不同的场景（原因写在 note 里），测试单独检查差异本身。
const SCENARIOS = [
  {
    id: "active_switch",
    note: "主动换人：换上来的承受对方同回合完成的快招；换下去的能力等级清零，换回来时 HP、能量不变",
    switch_cooldown_ms: 10000, // 缩短换人冷却，才能在短场景里换回来
    teams: [
      { shields: 1, members: [{ ...REGISTEEL }, { ...AZUMARILL }] },
      { shields: 1, members: [{ ...MEDICHAM, energy: 35 }, { ...SWAMPERT }] },
    ],
    charged: [{ actor: 1, turn: 3, move: "POWER_UP_PUNCH", shielded: false, apply_effect: false }],
    switches: [
      { actor: 0, turn: 2, to: 1 },
      { actor: 1, turn: 5, to: 1 },
      { actor: 1, turn: 28, to: 0 },
    ],
    max_turns: 40,
  },
  {
    id: "switch_into_charged_team_shields",
    note: "在对方放大招的回合换人：大招打在换上来的那只身上，开盾用全队的盾；盾用完后剧本要开也开不了",
    teams: [
      { shields: 2, members: [{ ...REGISTEEL }, { ...AZUMARILL, energy: 55 }, { ...MEDICHAM }] },
      { shields: 1, members: [{ ...SWAMPERT, energy: 100 }, { ...TREVENANT, energy: 50 }] },
    ],
    charged: [
      { actor: 1, turn: 1, move: "HYDRO_CANNON", shielded: true, apply_effect: false },
      { actor: 1, turn: 3, move: "HYDRO_CANNON", shielded: true, apply_effect: false },
      { actor: 0, turn: 5, move: "ICE_BEAM", shielded: true, apply_effect: false },
      { actor: 1, turn: 8, move: "SHADOW_BALL", shielded: true, apply_effect: false },
    ],
    switches: [
      { actor: 0, turn: 1, to: 1 },
      { actor: 1, turn: 7, to: 1 },
    ],
    max_turns: 20,
  },
  {
    id: "zero_turn_switch_both_sides",
    note: "大招后的空回合双方都 0 回合换人；漂浮的快招先结算，打在换下去的那只身上",
    teams: [
      { shields: 0, members: [{ ...GALVANTULA }, { ...AZUMARILL }] },
      { shields: 0, members: [{ ...REGISTEEL, energy: 75 }, { ...ALTARIA }] },
    ],
    charged: [{ actor: 1, turn: 2, move: "FOCUS_BLAST", shielded: false, apply_effect: false }],
    switches: [
      { actor: 0, turn: 3, to: 1 },
      { actor: 1, turn: 3, to: 1 },
    ],
    max_turns: 12,
  },
  {
    id: "floating_fast_knocks_out_before_zero_turn_switch",
    note: "大招后的空回合要 0 回合换人，换下去的那只先被漂浮快招打倒：按倒下后换人处理（不开始计时，对手冷却设 1），没有额外的换人回合",
    teams: [
      { shields: 0, members: [{ ...GALVANTULA }, { ...AZUMARILL }] },
      { shields: 0, members: [{ ...REGISTEEL, hp: 8, energy: 75 }, { ...ALTARIA }] },
    ],
    charged: [{ actor: 1, turn: 2, move: "FOCUS_BLAST", shielded: false, apply_effect: false }],
    switches: [{ actor: 1, turn: 3, to: 1 }],
    max_turns: 12,
  },
  // 下面几场存活的一方都放在第 0 方：PvPoke 里第 1 方存活时同回合的换人会被判无效（结算顺序的副作用，
  // 见最后一场 survivor_switch_side_1 和 docs/mechanics.md 13.6）。
  {
    id: "replacement_wait_and_survivor_switch",
    note: "被快招打倒：排队中的快招清空；换人回合倒下的一方换上第 3 只并等 4 秒，存活的一方同时换人（Q21）",
    teams: [
      { shields: 0, members: [{ ...SWAMPERT }, { ...WALREIN }] },
      { shields: 0, members: [{ ...AZUMARILL, hp: 2 }, { ...MEDICHAM }, { ...REGISTEEL }] },
    ],
    switches: [{ actor: 0, turn: 3, to: 1 }],
    replacements: [{ actor: 1, turn: 3, to: 2, wait_ms: 4000 }],
    max_turns: 12,
  },
  {
    id: "survivor_switch_timer_runs_out_during_wait",
    note: "存活的一方换人计时还剩 1 秒，对手选人等了 4 秒：等待期间计时走完，换人回合可以换（Q21）",
    teams: [
      { shields: 0, switch_timer_ms: 2000, members: [{ ...SWAMPERT }, { ...WALREIN }] },
      { shields: 0, members: [{ ...AZUMARILL, hp: 2 }, { ...MEDICHAM }, { ...REGISTEEL }] },
    ],
    switches: [{ actor: 0, turn: 3, to: 1 }],
    replacements: [{ actor: 1, turn: 3, to: 1, wait_ms: 4000 }],
    max_turns: 8,
  },
  {
    id: "survivor_in_cooldown_cannot_switch",
    note: "存活的一方还在换人冷却中：对手选人的回合不能换（Q21）",
    teams: [
      { shields: 0, switch_timer_ms: 20000, members: [{ ...SWAMPERT }, { ...WALREIN }] },
      { shields: 0, members: [{ ...AZUMARILL, hp: 2 }, { ...MEDICHAM }, { ...REGISTEEL }] },
    ],
    switches: [{ actor: 0, turn: 3, to: 1 }],
    replacements: [{ actor: 1, turn: 3, to: 1, wait_ms: 4000 }],
    max_turns: 8,
  },
  {
    id: "charged_knockout_replacement_and_zero_turn_switch",
    note: "被大招打倒（同回合自己的快招作废）：下一回合既是换人回合也是大招后的空回合，存活的一方 0 回合换人",
    teams: [
      { shields: 0, members: [{ ...SWAMPERT, energy: 40 }, { ...TREVENANT }] },
      { shields: 0, members: [{ ...REGISTEEL, hp: 20 }, { ...AZUMARILL }] },
    ],
    charged: [{ actor: 0, turn: 1, move: "HYDRO_CANNON", shielded: false, apply_effect: false }],
    switches: [{ actor: 0, turn: 2, to: 1 }],
    max_turns: 15,
  },
  {
    id: "double_knockout",
    note: "双方同回合倒下：下一回合双方都换人，再下一回合同时行动；打到一方全队倒下",
    teams: [
      { shields: 0, members: [{ ...ALTARIA, hp: 1 }, { ...AZUMARILL, hp: 30 }] },
      { shields: 0, members: [{ ...REGISTEEL, hp: 1 }, { ...MEDICHAM, hp: 30 }] },
    ],
  },
  {
    id: "full_3v3_simple_policy",
    note: "README 里简单规则策略打的那场完整 3v3：把双方的决定抄成剧本（大招、开盾、倒下后换谁）",
    teams: [
      { shields: 2, members: [
        { ...AZUMARILL },
        { species: "medicham", fast: "COUNTER", charged: ["ICE_PUNCH", "PSYCHIC"] },
        { ...REGISTEEL },
      ] },
      { shields: 2, members: [{ ...SWAMPERT }, { ...ALTARIA }, { ...TREVENANT }] },
    ],
    charged: [
      { actor: 1, turn: 21, move: "HYDRO_CANNON", shielded: true, apply_effect: false },
      { actor: 0, turn: 26, move: "ICE_BEAM", shielded: true, apply_effect: false },
      { actor: 1, turn: 30, move: "HYDRO_CANNON", shielded: true, apply_effect: false },
      { actor: 1, turn: 40, move: "EARTHQUAKE", shielded: false, apply_effect: false },
      { actor: 0, turn: 45, move: "ICE_BEAM", shielded: true, apply_effect: false },
      { actor: 1, turn: 53, move: "HYDRO_CANNON", shielded: false, apply_effect: false },
      { actor: 0, turn: 53, move: "ICE_BEAM", shielded: false, apply_effect: false },
      { actor: 1, turn: 70, move: "SKY_ATTACK", shielded: false, apply_effect: false },
      { actor: 0, turn: 72, move: "ICE_PUNCH", shielded: false, apply_effect: false },
      { actor: 1, turn: 84, move: "SKY_ATTACK", shielded: false, apply_effect: false },
      { actor: 1, turn: 99, move: "SKY_ATTACK", shielded: false, apply_effect: false },
      { actor: 0, turn: 102, move: "FOCUS_BLAST", shielded: false, apply_effect: false },
      { actor: 1, turn: 118, move: "SHADOW_BALL", shielded: false, apply_effect: false },
      { actor: 0, turn: 121, move: "ZAP_CANNON", shielded: false, apply_effect: false },
    ],
    replacements: [
      { actor: 1, turn: 54, to: 1, wait_ms: 0 },
      { actor: 0, turn: 56, to: 1, wait_ms: 0 },
      { actor: 0, turn: 85, to: 2, wait_ms: 0 },
      { actor: 1, turn: 103, to: 2, wait_ms: 0 },
    ],
  },
  {
    id: "survivor_switch_side_1",
    known_difference: true,
    note: "已知差异：存活的一方是第 1 方。PvPoke 先结算第 0 方的倒下换人，把第 1 方在场那只的冷却设成 500，"
      + "于是第 1 方的换人被判无效；我们的引擎照用户的规则（Q21），存活的一方不论哪一方都可以换",
    teams: [
      { shields: 0, members: [{ ...AZUMARILL, hp: 2 }, { ...MEDICHAM }, { ...REGISTEEL }] },
      { shields: 0, members: [{ ...SWAMPERT }, { ...WALREIN }] },
    ],
    switches: [{ actor: 1, turn: 3, to: 1 }],
    max_turns: 4,
  },
];

const DEFAULT_SWITCH_COOLDOWN_MS = 45000;

function parseArgs(argv) {
  const index = argv.indexOf("--pvpoke");
  if (index === -1 || !argv[index + 1]) {
    throw new Error("请用 --pvpoke <PvPoke 仓库目录> 指定 PvPoke 源码位置");
  }
  return { pvpokeDir: path.resolve(argv[index + 1]) };
}

// 在 PvPoke 环境里跑一场。输入输出都是普通 JSON 对象。
const PVPOKE_HELPERS = `
  var __makePokemon = function(battle, spec, side){
    const poke = new Pokemon(spec.species, side, battle);
    poke.initialize(battle.getCP());
    poke.selectMove("fast", spec.fast);
    spec.charged.forEach((moveId, k) => poke.selectMove("charged", moveId, k));
    if (poke.fastMove.moveId != spec.fast) { throw new Error(spec.species + " 选不到快招 " + spec.fast); }
    spec.charged.forEach((moveId, k) => {
      if (!poke.chargedMoves[k] || poke.chargedMoves[k].moveId != moveId) {
        throw new Error(spec.species + " 选不到大招 " + moveId);
      }
    });
    if (poke.formChange) { throw new Error(spec.species + " 会变换形态，引擎暂不支持"); }
    poke.fullReset();
    if (spec.hp !== undefined) { poke.setStartHp(spec.hp); }
    if (spec.energy !== undefined) { poke.setStartEnergy(spec.energy); }
    poke.reset();
    return poke;
  };

  var __runScenario = function(spec){
    const battle = new Battle();
    battle.setCP(spec.cp);

    // 【胶水 1】队伍：Player 对象管全队的盾和换人计时。
    const players = spec.teams.map((teamSpec, side) => {
      const player = new Player(side, false, battle);
      player.ai = { evaluateMatchup: function(){} }; // 换人计时走完时 PvPoke 会叫 AI 重新评估，这里不需要
      player.setTeam(teamSpec.members.map(m => __makePokemon(battle, m, side)));
      return player;
    });
    battle.setPlayers(players); // 会把盾重置成 2、换人计时重置成 0，所以下面再设
    players.forEach((player, side) => {
      const teamSpec = spec.teams[side];
      player.shields = teamSpec.shields;
      player.setSwitchTime(spec.switch_cooldown_ms);
      // 开局的换人计时：PvPoke 在每个 step() 开头扣 500 毫秒（包括第 1 回合），我们的引擎在下一回合开头扣
      // 上一回合的时间。换过人以后两边的值相同，只有"开局就有换人计时"时差 500，这里补上。
      player.switchTimer = teamSpec.switch_timer_ms > 0 ? teamSpec.switch_timer_ms + 500 : 0;
      player.getTeam().forEach(p => p.setShields(teamSpec.shields));
      battle.setNewPokemon(player.getTeam()[0], side, false);
    });

    const pokemon = () => battle.getPokemon();
    const slotOf = (poke) => players[poke.index].getTeam().indexOf(poke);

    // 剧本：大招交给沙盒模式本身（getTurnAction 按回合找 actions）
    battle.setSandboxMode(true);
    battle.setActions(spec.charged.map(c => {
      return new TimelineAction("charged", c.actor, c.turn, null, {
        shielded: c.shielded, buffs: c.apply_effect, charge: 1, priority: 0, __move: c.move,
      });
    }));
    // 大招在出招那只的招式里是第几个，要等知道是哪一只出招时才能定，所以在 getTurnAction 里填
    const chargedScript = spec.charged;

    // 剧本里的换人（包括倒下后的换人）。返回换上第几只，没有就是 undefined。
    let replacementTurn = null;
    let pendingWait = 0;
    const scriptedSwitch = (side, turn) => {
      const planned = spec.switches.find(s => s.actor == side && s.turn == turn);
      if (planned) { return planned.to; }
      if (turn === replacementTurn && pokemon()[side].hp <= 0) {
        const replacement = spec.replacements.find(r => r.actor == side && r.turn == turn);
        if (replacement) { return replacement.to; }
        return players[side].getTeam().findIndex(p => p.hp > 0); // 排在最前、没倒下的
      }
      return undefined;
    };

    const originalGetTurnAction = battle.getTurnAction;
    battle.getTurnAction = function(poke, opponent){
      const turn = battle.getTurns();
      if (poke.cooldown == 0 && !poke.hasActed) {
        const to = scriptedSwitch(poke.index, turn);
        if (to !== undefined) {
          // 与 getTurnAction 相同：先取宝可梦的优先级，换人再 +20
          poke.hasActed = true;
          return new TimelineAction("switch", poke.index, turn, to, { priority: poke.priority + 20 });
        }
      }
      // 把剧本里这一回合的大招换成"出招那只的第几个大招"
      battle.getActions().forEach(a => {
        if (a.type == "charged" && a.actor == poke.index && a.turn == turn) {
          const index = poke.chargedMoves.findIndex(m => m.moveId == a.settings.__move);
          if (index == -1) { throw new Error("第 " + turn + " 回合 " + poke.speciesId + " 没有 " + a.settings.__move); }
          a.value = index;
        }
      });
      return originalGetTurnAction(poke, opponent);
    };

    // 记录：每一招打的是哪一只、伤害、开没开盾
    const moves = [];
    const originalUseMove = battle.useMove;
    battle.useMove = function(attacker, defender, move, ...rest){
      const shieldsBefore = players[defender.index].getShields();
      const result = originalUseMove(attacker, defender, move, ...rest);
      const timeline = battle.getTimeline();
      const event = [...timeline].reverse().find(e => e.type.startsWith("fast") || e.type.startsWith("charged"));
      moves.push({
        turn: battle.getTurns(),
        actor: attacker.index,
        actor_slot: slotOf(attacker),
        target_slot: slotOf(defender),
        move: move.moveId,
        charged: move.category == "charged",
        damage: event.values[0],
        shielded: players[defender.index].getShields() < shieldsBefore,
      });
      return result;
    };

    // 记录：换人（从第几只换到第几只、换完后的换人计时）；没生效的换人也记下来
    const switches = [];
    const rejected = [];
    const originalProcessAction = battle.processAction;
    battle.processAction = function(action, poke, opponent){
      if (action.type != "switch") { return originalProcessAction(action, poke, opponent); }
      const side = poke.index;
      const from = slotOf(pokemon()[side]);
      const valid = action.valid && !action.processed;
      const result = originalProcessAction(action, poke, opponent);
      if (valid) {
        switches.push({
          turn: battle.getTurns(), actor: side, from, to: action.value,
          switch_timer_ms: players[side].getSwitchTimer(),
        });
      } else {
        rejected.push({ turn: battle.getTurns(), actor: side, to: action.value });
      }
      return result;
    };

    battle.start();
    const initial = players.map(p => p.getTeam().map(m => ({ hp: m.hp, energy: m.energy })));

    const snapshots = [];
    const faints = [];
    const fainted = new Set();
    let lastTurnMs = 0;
    let totalWaitMs = 0;
    const remaining = () => players.map(p => p.getRemainingPokemon());

    do {
      const turn = battle.getTurns();

      // 【胶水 3】计时：模拟模式的 step() 只扣 500，这里补上大招回合多出来的时间和选人的等待。
      const extra = Math.max(0, lastTurnMs - 500) + pendingWait;
      players.forEach(p => { p.switchTimer = Math.max(0, p.switchTimer - extra); });
      totalWaitMs += pendingWait;
      pendingWait = 0;

      // 【胶水 1】全队的盾：换上来的那只用全队剩下的盾（训练模式 setNewPokemon 的做法）。
      players.forEach(p => p.getTeam().forEach(member => member.setShields(p.getShields())));
      pokemon().forEach(p => { p.shields = players[p.index].getShields(); });

      const durationBefore = battle.getDuration();
      battle.step();
      lastTurnMs = battle.getDuration() - durationBefore;

      // 倒下的（每只记一次；0 回合换人前被漂浮快招打倒、已经换下去的也算）
      players.forEach((p, side) => p.getTeam().forEach((member, slot) => {
        if (member.hp <= 0 && !fainted.has(side + ":" + slot)) {
          fainted.add(side + ":" + slot);
          faints.push({ turn, actor: side, slot });
        }
      }));

      // 【胶水 2】倒下：照抄 step() 末尾 mode == "emulate" 的分支。
      replacementTurn = null;
      const faintedSides = [0, 1].filter(side => pokemon()[side].hp <= 0);
      if (faintedSides.length > 0 && remaining().every(n => n > 0)) {
        pokemon().forEach(p => { p.cooldown = 0; });   // "Reset cooldowns for active Pokemon"
        battle.getQueuedActions().length = 0;         // "If a Pokemon has fainted, clear the action queue"
        replacementTurn = battle.getTurns();          // 下一回合倒下的一方换人
        pendingWait = Math.max(0, ...faintedSides.map(side => {
          const replacement = spec.replacements.find(r => r.actor == side && r.turn == replacementTurn);
          return replacement ? replacement.wait_ms : 0;
        }));
      }

      snapshots.push({
        turn,
        sides: players.map((p, side) => {
          const active = pokemon()[side];
          return {
            active: slotOf(active),
            hp: p.getTeam().map(m => m.hp),
            energy: p.getTeam().map(m => m.energy),
            cooldown: active.cooldown / 500,
            stages: [active.statBuffs[0], active.statBuffs[1]],
            shields: p.getShields(),
            switch_timer_ms: p.getSwitchTimer(),
          };
        }),
      });
    } while (remaining().every(n => n > 0)
             && battle.getDuration() + totalWaitMs <= 240000
             && (spec.max_turns === undefined || snapshots.length < spec.max_turns));

    return {
      teams: spec.teams.map((teamSpec, side) => ({
        shields: teamSpec.shields,
        switch_timer_ms: teamSpec.switch_timer_ms,
        members: players[side].getTeam().map((p, slot) => ({
          species: p.speciesId,
          level: p.level,
          ivs: [p.ivs.atk, p.ivs.def, p.ivs.hp],
          cp: p.cp,
          hp: p.stats.hp,
          fast: p.fastMove.moveId,
          charged: p.chargedMoves.map(m => m.moveId),
          start_hp: initial[side][slot].hp,
          start_energy: initial[side][slot].energy,
        })),
      })),
      snapshots,
      events: { moves, switches, faints, rejected },
      result: {
        turns: snapshots.length,
        remaining: remaining(),
        elapsed_ms: battle.getDuration() + totalWaitMs,
      },
    };
  };
`;

function main() {
  const { pvpokeDir } = parseArgs(process.argv.slice(2));
  const { context, commit } = loadPvPoke(pvpokeDir, GAMEMASTER_PATH);
  context.console = { ...console, log: () => {} }; // Player.startSwitchTimer 每次换人都会打印，关掉
  evaluate(context, PVPOKE_HELPERS);

  const scenarios = SCENARIOS.map(scenario => {
    const spec = {
      cp: scenario.cp ?? 1500,
      switch_cooldown_ms: scenario.switch_cooldown_ms ?? DEFAULT_SWITCH_COOLDOWN_MS,
      teams: scenario.teams.map(t => ({ shields: t.shields, switch_timer_ms: t.switch_timer_ms ?? 0, members: t.members })),
      charged: scenario.charged ?? [],
      switches: scenario.switches ?? [],
      replacements: scenario.replacements ?? [],
      max_turns: scenario.max_turns,
    };
    const outcome = evaluate(context, `__runScenario(${JSON.stringify(spec)})`);
    return {
      id: scenario.id,
      note: scenario.note,
      known_difference: scenario.known_difference ?? false,
      cp: spec.cp,
      switch_cooldown_ms: spec.switch_cooldown_ms,
      max_turns: spec.max_turns ?? null,
      script: { charged: spec.charged, switches: spec.switches, replacements: spec.replacements },
      ...outcome,
    };
  });

  const output = {
    source: {
      description: "PvPoke 源码按剧本结算的队伍对战（含换人），由 tools/pvpoke_ref/export_switch_reference.js 生成",
      pvpoke_commit: commit,
      gamemaster: "data/gamemaster.json",
      generated_on: new Date().toISOString().slice(0, 10),
      license: "PvPoke 源码与数据为 MIT license",
    },
    scenarios,
  };

  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output) + "\n");
  const totalTurns = scenarios.reduce((sum, s) => sum + s.snapshots.length, 0);
  console.log(`写入 ${path.relative(REPO_ROOT, OUTPUT_PATH)}：${scenarios.length} 场，共 ${totalTurns} 个回合`);
}

main();
