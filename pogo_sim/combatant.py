"""对战中的一只宝可梦：固定的配置（PokemonBuild）和随对战变化的状态（Combatant）。"""

from dataclasses import dataclass, field, replace
from typing import Literal

from pogo_sim.damage import DamageSide, effective_attack
from pogo_sim.gamemaster import GameMaster, Move, Species, StatChange
from pogo_sim.rules import BattleRules
from pogo_sim.stats import BattleStats, IVs, calculate_battle_stats, calculate_cp

# Mega 没有指定 Mega 等级时的默认值：有 supermega 标签的是 4，其他是 3。
# 来源：PvPoke Pokemon.js 第 63、146 行。状态：参考 PvPoke。
DEFAULT_MEGA_LEVEL = 3
DEFAULT_SUPERMEGA_LEVEL = 4

# 脱壳忍者的 HP 固定为 10，与等级和 IV 无关。来源：Pokemon.js initialize（dex 292）。状态：参考 PvPoke。
SHEDINJA_DEX = 292
SHEDINJA_HP = 10


@dataclass(frozen=True)
class PokemonBuild:
    """一只宝可梦的配置：种类、等级、IV、招式。对战开始前就确定，对战中不变。"""

    species_id: str
    level: float
    ivs: IVs
    fast_move_id: str
    charged_move_ids: tuple[str, ...]  # 1 到 3 个；第三个只有 Mega 能带（见 make_combatant）
    mega_level: int | None = None  # 只对 Mega 有意义；不填则用默认值
    # 这个配置是怎么选出来的，每条一句（例如等级上限、IV 排名、为什么降等级），只用于日志。
    # 不参与相等比较：说明不同、数值相同的两个配置算同一个。见 season.season_build。
    notes: tuple[str, ...] = field(default=(), compare=False)


FaintSource = Literal["fast", "charged"]

# 没有 CP 上限的联盟（大师联盟）。PvPoke 用 10000 表示。
UNCAPPED_CP = 10000
UNCAPPED_LEVEL = 50.0


def league_build(
    gm: GameMaster,
    species_id: str,
    cp_limit: int,
    fast_move_id: str,
    charged_move_ids: tuple[str, ...],
    mega_level: int | None = None,
) -> PokemonBuild:
    """用 PvPoke 的联盟默认等级和 IV 建立配置。

    有 CP 上限的联盟（500 / 1500 / 2500）：gamemaster 的 defaultIVs；
    大师联盟（10000）：50 级、15/15/15。
    状态：参考 PvPoke（这是 PvPoke 的默认选择，不是游戏规则）；
    已与 PvPoke 对战参考数据里全部 20 个配置核对一致（tests/test_battle_pvpoke.py）。
    """
    species = gm.get_species(species_id)
    if cp_limit >= UNCAPPED_CP:
        level, ivs = UNCAPPED_LEVEL, IVs(15, 15, 15)
    elif cp_limit in species.default_spreads:
        spread = species.default_spreads[cp_limit]
        level, ivs = spread.level, spread.ivs
    else:
        raise ValueError(f"gamemaster 里没有 {species_id} 在 CP {cp_limit} 的默认配置")
    return PokemonBuild(species_id, level, ivs, fast_move_id, tuple(charged_move_ids), mega_level)


@dataclass
class Combatant:
    """对战中的一只宝可梦。

    前半部分字段是固定数据，后半部分是对战状态。状态只由 battle 模块修改；
    策略（policy）只读，不要在策略里改这里的值。
    """

    # ---- 固定数据 ----
    index: int  # 属于哪一方：0 或 1
    build: PokemonBuild
    species: Species
    stats: BattleStats  # stats.hp 是最大 HP
    cp: int
    fast_move: Move
    charged_moves: tuple[Move, ...]
    mega_level: int | None  # 非 Mega 为 None

    # ---- 对战状态 ----
    # 盾不在这里：盾是全队共用的，记在队伍上（team.Team.shields）。
    hp: int
    energy: int = 0
    cooldown: int = 0  # 还要等几个回合才能再行动；0 表示本回合可以决定行动
    atk_stage: int = 0
    def_stage: int = 0
    fainted_by: FaintSource | None = None  # 被快招还是大招打倒（影响同回合其他行动是否有效）

    # 概率性能力变化的计数器，键是招式 ID（只给大招建，PvPoke 也是这样）。见 battle._roll_effect。
    chance_meters: dict[str, float] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.species.name

    @property
    def is_shadow(self) -> bool:
        return self.species.is_shadow

    @property
    def is_fainted(self) -> bool:
        return self.hp <= 0

    def damage_side(self) -> DamageSide:
        """当前状态下计算伤害需要的数据。"""
        return DamageSide(
            types=self.species.types,
            stats=self.stats,
            is_shadow=self.is_shadow,
            atk_stage=self.atk_stage,
            def_stage=self.def_stage,
            mega_level=self.mega_level,
        )

    def cmp_attack(self, rules: BattleRules) -> float:
        """CMP（同回合放大招谁先手）比较用的攻击。"""
        if rules.cmp_uses_raw_attack:
            return self.stats.atk
        return effective_attack(self.damage_side(), rules)

    def apply_stat_change(self, change: StatChange, rules: BattleRules) -> None:
        """叠加能力等级变化，并限制在 ±max_stat_stage 之内。"""
        limit = rules.max_stat_stage
        self.atk_stage = max(-limit, min(limit, self.atk_stage + change.atk))
        self.def_stage = max(-limit, min(limit, self.def_stage + change.def_))


def initial_chance_meter(chance: float) -> float:
    """PvPoke 计数器的初始值：等于概率本身；50% 的招式例外，从 0 开始。

    效果：12.5% 的招第 7 次使用时触发（0.125 × 8 = 1）；50% 的招第 2 次触发。
    来源：Pokemon.js resetMoves（第 740–746 行）。状态：参考 PvPoke（PvPoke 的简化，不是游戏机制）。
    """
    return 0.0 if chance == 0.5 else chance


def resolve_mega_level(species: Species, mega_level: int | None) -> int | None:
    """实际使用的 Mega 等级：非 Mega 为 None；Mega 没指定时用默认值（supermega 是 4，其他是 3）。"""
    if not species.is_mega:
        if mega_level is not None:
            raise ValueError(f"{species.species_id} 不是 Mega，不能指定 Mega 等级")
        return None
    if mega_level is not None:
        return mega_level
    if "supermega" in species.tags:
        return DEFAULT_SUPERMEGA_LEVEL
    return DEFAULT_MEGA_LEVEL


def check_charged_moves(species: Species, charged_moves: tuple[Move, ...]) -> None:
    """大招数量：1 到 2 个；第三个只有带 extraChargedMoves 的 Mega 能带，而且只能从里面选。

    来源：用户确认（docs/mechanics.md 9.1 Q10）。gamemaster 里 64 只 Mega 中有 19 只有
    extraChargedMoves（都是 supermega）；可乐鸟也有 extraChargedMoves，但那是形态机制，不是第三个大招。
    """
    for move in charged_moves:
        if move.is_fast:
            raise ValueError(f"{move.move_id} 不是大招")
    if not 1 <= len(charged_moves) <= 3:
        raise ValueError(
            f"{species.species_id} 只能带 1 到 3 个大招，得到 {len(charged_moves)} 个"
        )
    if len(charged_moves) < 3:
        return
    if not (species.is_mega and species.extra_charged_move_ids):
        raise ValueError(
            f"{species.species_id} 不能带第三个大招：只有带 extraChargedMoves 的 Mega 可以"
        )
    third = charged_moves[2].move_id
    if third not in species.extra_charged_move_ids:
        allowed = "、".join(species.extra_charged_move_ids)
        raise ValueError(
            f"{species.species_id} 的第三个大招只能从 extraChargedMoves 里选（{allowed}），得到 {third}"
        )


def make_combatant(gm: GameMaster, build: PokemonBuild, index: int) -> Combatant:
    """按配置建立对战开始时的状态（满 HP、0 能量、0 能力等级）。index 是属于哪一方（0 或 1）。

    盾数不在这里给：盾属于队伍，建队伍时给（team.Team）。
    """
    species = gm.get_species(build.species_id)
    fast_move = gm.get_move(build.fast_move_id)
    charged_moves = tuple(gm.get_move(move_id) for move_id in build.charged_move_ids)

    if not fast_move.is_fast:
        raise ValueError(f"{fast_move.move_id} 不是快速技能")
    check_charged_moves(species, charged_moves)

    mega_level = resolve_mega_level(species, build.mega_level)

    stats = calculate_battle_stats(species.base_stats, build.ivs, build.level)
    if species.dex == SHEDINJA_DEX:
        stats = replace(stats, hp=SHEDINJA_HP)
    chance_meters = {
        move.move_id: initial_chance_meter(move.effect.chance)
        for move in charged_moves
        if move.effect is not None and move.effect.chance < 1
    }

    return Combatant(
        index=index,
        build=build,
        species=species,
        stats=stats,
        cp=calculate_cp(species.base_stats, build.ivs, build.level),
        fast_move=fast_move,
        charged_moves=charged_moves,
        mega_level=mega_level,
        hp=stats.hp,
        chance_meters=chance_meters,
    )
