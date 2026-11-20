"""按对战配置文件跑 0–2 盾对 0–2 盾的九宫格（配置格式见 pogo_sim/matchups.py）。

用法（在仓库根目录）：
    .venv/bin/python -m tools.run_matchups experiments/mega_zygarde_ml.toml
    .venv/bin/python -m tools.run_matchups experiments/mega_zygarde_ml.toml --output docs/experiments/mega_zygarde_ml.md

看某一场的时间线（测试对象、对手用报告里的名字，后面是双方的盾数）：
    .venv/bin/python -m tools.run_matchups experiments/mega_zygarde_ml.toml \\
        --timeline "Dragon Tail" "Mewtwo (Mega Y) Avalanche" 1 1
"""

import argparse
import sys
from pathlib import Path

from pogo_sim.matchups import (
    MatchupConfigError,
    fight,
    find_participant,
    format_report,
    load_matchup_config,
    make_sides,
    prepare_matchups,
    run_all,
)
from pogo_sim.report import format_result, format_setup
from pogo_sim.timeline import format_timeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("config", type=Path, help="对战配置文件（TOML）")
    parser.add_argument("--output", type=Path, help="把报告写进这个 Markdown 文件（默认只打印）")
    parser.add_argument(
        "--timeline",
        nargs=4,
        metavar=("SUBJECT", "OPPONENT", "SUBJECT_SHIELDS", "OPPONENT_SHIELDS"),
        help="只打一场并打印时间线，不跑九宫格",
    )
    args = parser.parse_args()

    try:
        matchups = prepare_matchups(load_matchup_config(args.config))
    except MatchupConfigError as e:
        sys.exit(f"配置有误：{e}")

    if args.timeline:
        subject_label, opponent_label, mine, theirs = args.timeline
        try:
            subject = find_participant(matchups.subjects, subject_label)
            opponent = find_participant(matchups.opponents, opponent_label)
        except KeyError as e:
            sys.exit(e.args[0])
        sides = make_sides(matchups, subject, opponent, int(mine), int(theirs))
        setup = format_setup(sides)  # 要在对战开始前取：盾数会变
        result = fight(matchups, sides)
        names = (sides[0].active_member.name, sides[1].active_member.name)
        print(setup)
        print(format_result(result, names))
        print(format_timeline(result.events, names, show_decisions=True))
        return

    report = format_report(matchups, run_all(matchups), source=str(args.config))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"写入 {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
