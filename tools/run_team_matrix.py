"""队伍对队伍：我方的队伍对手写的和随机抽的很多队各打一场 3v3，输出 Markdown 报告（配置格式见 pogo_sim/team_matrix.py）。

用法（在仓库根目录）：
    .venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml
    .venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --output docs/experiments/gl_team_matrix_example.md
    .venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --csv team_matrix.csv
    # 只打其中一场，输出完整的 3v3 报告（换人和开盾的原因、时间线），同 tools/run_team_battle.py：
    .venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --battle "Team A" "抽样 3"
"""

import argparse
import sys
from pathlib import Path

from pogo_sim.config import ConfigError
from pogo_sim.team_battle import format_team_battle_report, run_team_battle
from pogo_sim.team_matrix import (
    find_team,
    format_csv,
    format_report,
    load_team_matrix_config,
    pairing,
    prepare_team_matrix,
    run_team_matrix,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("config", type=Path, help="队伍对队伍的配置文件（TOML）")
    parser.add_argument("--output", type=Path, help="把报告写进这个 Markdown 文件（默认只打印）")
    parser.add_argument("--csv", type=Path, help="另外把全部对战写成 CSV，一场一行")
    parser.add_argument(
        "--battle", nargs=2, metavar=("OURS", "OPPONENT"), help="只打我方 OURS 对对手 OPPONENT 这一场，输出完整报告"
    )
    parser.add_argument("--no-timeline", action="store_true", help="和 --battle 一起用：报告里不附完整时间线")
    args = parser.parse_args()

    try:
        matrix = prepare_team_matrix(load_team_matrix_config(args.config))
        if args.battle:
            team = find_team(matrix.teams, args.battle[0], "我方")
            opponent = find_team(matrix.opponents, args.battle[1], "对手")
    except ConfigError as e:
        sys.exit(f"配置有误：{e}")

    if args.battle:
        battle = pairing(matrix, team, opponent)
        report = format_team_battle_report(
            battle, run_team_battle(battle), source=str(args.config), include_timeline=not args.no_timeline
        )
    else:
        results = run_team_matrix(matrix)
        report = format_report(matrix, results, source=str(args.config))
        if args.csv:
            args.csv.write_text(format_csv(matrix, results), encoding="utf-8")
            print(f"写入 {args.csv}")

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"写入 {args.output}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
