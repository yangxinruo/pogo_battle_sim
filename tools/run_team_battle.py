"""按 3v3 配置文件打一场，输出 Markdown 报告（配置格式见 pogo_sim/team_battle.py）。

用法（在仓库根目录）：
    .venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml
    .venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml --output docs/experiments/gl_3v3_example.md
    .venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml --no-timeline   # 报告里不附时间线
    # 对方的策略不变，搜索 Team A 更好的打法（逐步试探，pogo_sim/best_response.py）：
    .venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml --best-response "Team A"
"""

import argparse
import sys
from pathlib import Path

from pogo_sim.best_response import format_best_response_report, search_best_response
from pogo_sim.config import ConfigError
from pogo_sim.team_battle import (
    format_team_battle_report,
    load_team_battle_config,
    prepare_team_battle,
    run_team_battle,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("config", type=Path, help="3v3 配置文件（TOML）")
    parser.add_argument("--output", type=Path, help="把报告写进这个 Markdown 文件（默认只打印）")
    parser.add_argument("--no-timeline", action="store_true", help="报告里不附完整时间线")
    parser.add_argument(
        "--best-response", metavar="TEAM", help="对方的策略不变，搜索这一队（写队名）更好的打法，输出搜索的报告"
    )
    args = parser.parse_args()

    try:
        battle = prepare_team_battle(load_team_battle_config(args.config))
    except ConfigError as e:
        sys.exit(f"配置有误：{e}")

    if args.best_response is not None:
        names = [team.setup.name for team in battle.teams]
        if args.best_response not in names:
            sys.exit(f"没有叫 {args.best_response!r} 的队伍（有：{', '.join(names)}）")
        response = search_best_response(battle, names.index(args.best_response))
        report = format_best_response_report(
            battle, response, source=str(args.config), include_timeline=not args.no_timeline
        )
    else:
        result = run_team_battle(battle)
        report = format_team_battle_report(
            battle, result, source=str(args.config), include_timeline=not args.no_timeline
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"写入 {args.output}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
