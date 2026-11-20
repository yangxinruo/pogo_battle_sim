"""把简单规则策略和 PvPoke 的 AI 放在同样的对局里比较，生成 docs/simple_policy_vs_pvpoke.md。

对局和 PvPoke 的结果来自 tests/fixtures/pvpoke_battle_reference.json（52 场）。
引擎已经和 PvPoke 逐回合一致（3b），所以这里的差异全部来自"决策"：出什么招、什么时候出、开不开盾。

用法（在仓库根目录）：
    .venv/bin/python -m tools.compare_simple_policy
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.stats import IVs
from pogo_sim.team import Team
from pogo_sim.timeline import DecisionEvent, MoveEvent

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PATH = REPO_ROOT / "tests" / "fixtures" / "pvpoke_battle_reference.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "simple_policy_vs_pvpoke.md"

# 比较几种配置，看哪个假设对结果影响大。第一个是默认配置，逐场明细只列它。
VARIANTS: dict[str, SimplePolicyConfig] = {
    "默认：骗盾 + 出招时机 + 总是开盾": SimplePolicyConfig(),
    "不骗盾": SimplePolicyConfig(bait_shields=False),
    "不优化出招时机": SimplePolicyConfig(optimize_timing=False),
    "HP 会低于 50% 才开盾": SimplePolicyConfig(shielding="when_low"),
    "能放就放（最便宜的招）": SimplePolicyConfig(charged_move_choice="cheapest", bait_shields=False),
}


@dataclass(frozen=True)
class ChargedUse:
    turn: int
    actor: int
    move: str
    shielded: bool


def _run(gm: GameMaster, battle: dict, config: SimplePolicyConfig) -> BattleResult:
    sides = []
    for index, spec in enumerate(battle["pokemon"]):
        build = PokemonBuild(
            spec["species"], spec["level"], IVs(*spec["ivs"]), spec["fast"], tuple(spec["charged"]), spec["mega_level"]
        )
        sides.append(Team((make_combatant(gm, build, index),), shields=spec["shields"]))
    return Battle((sides[0], sides[1]), (SimplePolicy(config), SimplePolicy(config))).run()


def _winner(ratings: list[int] | tuple[int, int]) -> int | None:
    if ratings[0] > ratings[1]:
        return 0
    if ratings[1] > ratings[0]:
        return 1
    return None


def _pvpoke_charged(battle: dict) -> list[ChargedUse]:
    return [
        ChargedUse(e["turn"], e["actor"], e["move"], e["shielded"])
        for e in battle["events"]
        if e["kind"] == "move" and e["charged"]
    ]


def _our_charged(result: BattleResult) -> list[ChargedUse]:
    return [
        ChargedUse(e.turn, e.actor, e.move_id, e.shielded)
        for e in result.events
        if isinstance(e, MoveEvent) and e.is_charged
    ]


def _describe(use: ChargedUse, names: tuple[str, str]) -> str:
    shield = "，被挡" if use.shielded else ""
    return f"T{use.turn} {names[use.actor]} {use.move}{shield}"


def _reason_at(result: BattleResult, use: ChargedUse) -> str:
    for event in result.events:
        if isinstance(event, DecisionEvent) and event.turn == use.turn and event.actor == use.actor:
            return event.reason
    return ""


def _first_difference(battle: dict, result: BattleResult, names: tuple[str, str]) -> str:
    """第一处大招（或开盾）不同的地方，附上我们这一步的决策原因。"""
    theirs = _pvpoke_charged(battle)
    ours = _our_charged(result)
    for index, (a, b) in enumerate(zip(theirs, ours)):
        if a != b:
            return (
                f"第 {index + 1} 个大招：PvPoke {_describe(a, names)}；"
                f"我们 {_describe(b, names)}（{_reason_at(result, b)}）"
            )
    if len(theirs) > len(ours):
        return f"PvPoke 多放了一个：{_describe(theirs[len(ours)], names)}"
    if len(ours) > len(theirs):
        extra = ours[len(theirs)]
        return f"我们多放了一个：{_describe(extra, names)}（{_reason_at(result, extra)}）"
    return "大招序列完全相同"


def _names(gm: GameMaster, battle: dict) -> tuple[str, str]:
    a, b = (gm.get_species(p["species"]).name for p in battle["pokemon"])
    if a == b:
        return f"{a}(A)", f"{b}(B)"
    return a, b


def main() -> None:
    gm = load_gamemaster()
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    battles = reference["battles"]

    summary_rows = []
    detail_rows = []
    for variant_index, (variant_name, config) in enumerate(VARIANTS.items()):
        same_winner = 0
        same_charged = 0
        rating_gap = 0
        for battle in battles:
            result = _run(gm, battle, config)
            theirs = battle["result"]["ratings"]
            if _winner(theirs) == result.winner:
                same_winner += 1
            if _pvpoke_charged(battle) == _our_charged(result):
                same_charged += 1
            rating_gap += abs(theirs[0] - result.ratings[0])

            if variant_index == 0:
                names = _names(gm, battle)
                shields = f"{battle['pokemon'][0]['shields']}-{battle['pokemon'][1]['shields']}"
                winner_mark = "同" if _winner(theirs) == result.winner else "**不同**"
                detail_rows.append(
                    f"| {names[0]} vs {names[1]} | {shields} | {theirs[0]}:{theirs[1]} | "
                    f"{result.ratings[0]}:{result.ratings[1]} | {winner_mark} | "
                    f"{_first_difference(battle, result, names)} |"
                )
        count = len(battles)
        summary_rows.append(
            f"| {variant_name} | {same_winner}/{count} | {same_charged}/{count} | {rating_gap / count:.0f} |"
        )

    lines = [
        "# 简单规则策略 vs PvPoke AI",
        "",
        "本文件由 `tools/compare_simple_policy.py` 生成，不要手改；分析见 `docs/mechanics.md` 8.6。",
        f"对局：`tests/fixtures/pvpoke_battle_reference.json` 的 {len(battles)} 场"
        f"（PvPoke commit `{reference['source']['pvpoke_commit'][:7]}`）。",
        "引擎已与 PvPoke 逐回合一致，所以下面的差异全部来自决策。双方用同一种配置。",
        "",
        "## 各配置总览",
        "",
        "| 配置 | 胜负与 PvPoke 相同 | 大招序列完全相同 | 评分平均差（左方，满分 1000） |",
        "|---|---|---|---|",
        *summary_rows,
        "",
        f"## 逐场明细（{next(iter(VARIANTS))}）",
        "",
        "评分是 PvPoke 的对战评分（左方:右方）。\"第一处不同\"列出双方大招序列第一个不一样的地方，括号里是我们那一步的决策原因。",
        "",
        "| 对局 | 盾 | PvPoke | 我们 | 胜负 | 第一处不同 |",
        "|---|---|---|---|---|---|",
        *detail_rows,
        "",
    ]
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"写入 {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print("\n".join(summary_rows))


if __name__ == "__main__":
    main()
