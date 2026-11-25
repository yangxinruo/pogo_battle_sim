# Pokémon GO PvP 对战模拟器

一个透明、可调的 Pokémon GO PvP 模拟器。目标是让 3v3 的过程和策略假设都看得见，并支持加入未发布的宝可梦（如新 Mega）。

当前进度：1v1 引擎已完成（数值、伤害、回合结算），并与 PvPoke 源码逐回合核对过；有两种策略："按剧本出招"和一组可调的简单规则（与 PvPoke AI 的比较见 [docs/simple_policy_vs_pvpoke.md](docs/simple_policy_vs_pvpoke.md)）。正在做第 2 步（自定义宝可梦与 Mega 规则）：已能用覆盖文件加入未发布的宝可梦和招式，给 IV 组合排名，按赛季规则（含 Mega 等级上限）建立配置，并用它跑 1v1、输出带配置说明的时间线；配招和对手写在配置文件里，可以批量跑 0–2 盾对 0–2 盾的九宫格。第 2 步已完成。第 3 步（3v3）拆成的几个单元都已完成，拆分和各项决定见 [docs/mechanics.md](docs/mechanics.md) 第 13 节：3v3-a（引擎以队伍为单位，盾全队共用，1v1 是每队一只）、3v3-b（换人：主动换人、大招后 0 回合换人、倒下后换人，换人冷却，3v3 胜负判定）、3v3-c（换人结算与 PvPoke 源码逐回合核对）、3v3-d（对位评估；3v3 策略 `TeamPolicy`：倒下后换上对位评分最高的，当前对位不好就主动换人，不在必输的对位上开盾）、3v3-e（3v3 配置文件与报告，含队伍检查）、3v3-f1（PvPoke 排名快照；1v1 对环境前 N 的批量九宫格，Mega 和非 Mega 分开取）、3v3-f2（队伍对队伍：我方的队伍对手写的和从环境前 N 随机抽的很多队各打一场 3v3）和 3v3-g（对固定对手策略的应对：对手的 TeamPolicy 不变，逐步试探我方更好的打法）。第 4 步（网页界面）进行中：4a（本地服务器 + 打一场 3v3 的页面）已完成，接下来是战斗过程图、手动对战、能力值排序，需求见 [docs/mechanics.md](docs/mechanics.md) 第 14 节。机制规格见 [docs/mechanics.md](docs/mechanics.md)。

## 目录

- `pogo_sim/`：Python 包
  - `cpm.py`：等级与 CP 倍率（CPM）表
  - `stats.py`：IV、CP、HP、实际攻防
  - `iv_ranking.py`：联盟 CP 上限下的 IV 排名（按能力值乘积）
  - `season.py`：赛季规则（等级上限、Mega 等级上限、Mega 降等级、每队 Mega 数）、按规则建立配置的 `season_build`、队伍检查 `check_team`（同一种不能带两只、Mega 数）
  - `conversion.py`：正作六项能力值 → GO 种族值
  - `gamemaster.py`：读取 PvPoke gamemaster.json，并合并覆盖文件
  - `custom.py`：自定义覆盖文件（新宝可梦、新招式、修改已有条目）
  - `rules.py`：所有可配置的机制参数（`BattleRules`）
  - `typechart.py`：属性克制表
  - `damage.py`：伤害公式
  - `combatant.py`：对战中的一只宝可梦（配置 `PokemonBuild` 和对战状态 `Combatant`）
  - `team.py`：一方的队伍 `Team`（成员、在场的是哪只、全队共用的盾和换人冷却）
  - `policy.py`：策略接口（出什么招、开不开盾、换不换人、倒下后换谁）和剧本策略 `ScriptedPolicy`
  - `simple_policy.py`：简单规则策略 `SimplePolicy`（规则和参数见文件开头）
  - `evaluation.py`：对位评估（从当前状态打 1v1，按盾数组合加权，0–1000）
  - `team_policy.py`：3v3 策略 `TeamPolicy`（出招照简单规则策略；选人、主动换人、开盾看对位评分；规则和参数见文件开头）
  - `battle.py`：回合结算引擎（双方各一支队伍；1v1 是每队一只）
  - `timeline.py`：时间线事件、逐回合快照、文字日志
  - `report.py`：对战报告的文字部分（双方配置和配置说明、结果一行；1v1 和 3v3 都可以）
  - `moveset.py`：配招和招式池检查
  - `config.py`：配置文件的共用部分（一只宝可梦的写法、参数表的检查、报告里的一行说明）
  - `matchups.py`：1v1 对战配置文件（TOML）和 0–2 盾对 0–2 盾的九宫格；对手可以是环境前 N
  - `rankings.py`：读 PvPoke 的排名，取环境前 N（Mega 和非 Mega 分开取）
  - `team_battle.py`：3v3 配置文件（TOML）和报告
  - `team_matrix.py`：队伍对队伍：我方几队对手写的和随机抽的很多队各打一场 3v3，出总表和每一场的结果
  - `best_response.py`：对固定对手策略的应对：对手的策略不变，逐步试探我方更好的打法
  - `web_api.py`：网页界面的接口（收 dict、回 dict），只做转换
- `tests/`：pytest 测试；`tests/fixtures/` 是用 PvPoke 源码生成的参考数据
- `tools/pvpoke_ref/`：在 Node 里运行 PvPoke 源码、生成参考数据的脚本
- `tools/compare_simple_policy.py`：简单规则策略与 PvPoke AI 的比较（`.venv/bin/python -m tools.compare_simple_policy`）
- `tools/run_matchups.py`：按对战配置文件跑九宫格（`.venv/bin/python -m tools.run_matchups <配置文件>`，`--csv` 另存全部评分）
- `tools/run_team_battle.py`：按 3v3 配置文件打一场、出报告（`.venv/bin/python -m tools.run_team_battle <配置文件>`；`--best-response 队名` 搜索这一队更好的打法）
- `tools/run_team_matrix.py`：队伍对队伍（`.venv/bin/python -m tools.run_team_matrix <配置文件>`，`--csv` 另存全部对战，`--battle` 只打其中一场，再加 `--best-response` 搜索我方更好的打法）
- `tools/run_web.py`：本地网页界面的服务器（`.venv/bin/python -m tools.run_web`）
- `web/`：网页的文件（HTML / JS / CSS，不用构建）
- `experiments/`：对战配置文件，例如 Mega 基格尔德在大师联盟（`mega_zygarde_ml.toml`）、Mega 雪妖女对环境前 N（`gl_mega_froslass_top.toml`）、3v3 的例子（`gl_3v3_example.toml`）、队伍对队伍的例子（`gl_team_matrix_example.toml`）；结果在 `docs/experiments/`
- `data/`：PvPoke gamemaster.json 和排名（`rankings/`）的快照（来源见 `data/SOURCE.md`）
- `data/custom/`：自定义覆盖文件（TOML），格式见 docs/mechanics.md 第 10 节
- `docs/`：机制规格文档

## 网页界面

在浏览器里选队伍、打一场 3v3、看结果和逐回合时间线（第 4 步，4a；需求和分步见 [docs/mechanics.md](docs/mechanics.md) 第 14 节）：

```bash
.venv/bin/python -m tools.run_web
```

启动后自动打开 http://127.0.0.1:8000（只监听本机；`--port` 换端口，`--no-browser` 不开浏览器，Ctrl+C 停止）。页面只负责填表和显示，建配置、检查、对战都在 Python 引擎里（`pogo_sim/web_api.py`）；队伍的写法和 3v3 配置文件一样，浏览器会记住上次填的。

## 开发环境

所有命令都通过项目自己的 venv 运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

## 跑一场对战

用简单规则策略（等级和 IV 用 PvPoke 的联盟默认值）：

```python
from pogo_sim.battle import Battle
from pogo_sim.combatant import league_build, make_combatant
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.timeline import format_timeline

gm = load_gamemaster()
azumarill = make_combatant(gm, league_build(gm, "azumarill", 1500, "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0)  # 0：第 0 方
medicham = make_combatant(gm, league_build(gm, "medicham", 1500, "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1)
teams = (Team((azumarill,), shields=2), Team((medicham,), shields=2))  # 1v1：每队一只；盾属于队伍

no_bait = SimplePolicyConfig(bait_shields=False)  # 每个规则都可以单独调
result = Battle(teams, (SimplePolicy(), SimplePolicy(no_bait))).run()
print(result)
print(format_timeline(result.events, (azumarill.name, medicham.name), show_decisions=True))
```

按剧本出招（复现某一场的具体过程）：

```python
from pogo_sim.battle import Battle
from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.policy import ScriptedCharged, ScriptedPolicy
from pogo_sim.stats import IVs
from pogo_sim.team import Team
from pogo_sim.timeline import format_timeline

gm = load_gamemaster()
azumarill = make_combatant(gm, PokemonBuild("azumarill", 43, IVs(4, 15, 13), "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0)
medicham = make_combatant(gm, PokemonBuild("medicham", 49, IVs(7, 15, 14), "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1)

# 剧本（来自 PvPoke 这一对局 1 盾对 1 盾的实际过程）：
#   第 21 回合 Medicham 放 Psychic，Azumarill 开盾；第 26 回合 Azumarill 放 Ice Beam，Medicham 开盾；
#   第 37 回合 Azumarill 放 Play Rough；第 43 回合 Medicham 放 Psychic。
azumarill_policy = ScriptedPolicy(
    charged={26: ScriptedCharged(26, "ICE_BEAM"), 37: ScriptedCharged(37, "PLAY_ROUGH")},
    shields={21: True},
)
medicham_policy = ScriptedPolicy(
    charged={21: ScriptedCharged(21, "PSYCHIC"), 43: ScriptedCharged(43, "PSYCHIC")},
    shields={26: True},
)
teams = (Team((azumarill,), shields=1), Team((medicham,), shields=1))
result = Battle(teams, (azumarill_policy, medicham_policy)).run()
assert azumarill_policy.unused_charged() == [] and medicham_policy.unused_charged() == []
print(result)
print(format_timeline(result.events, (azumarill.name, medicham.name)))
```

## 3v3

每队最多 3 只（第一只是首发），盾是全队共用的。换人的规则见 [docs/mechanics.md](docs/mechanics.md) 13.5 节。

```python
from pogo_sim.battle import Battle
from pogo_sim.combatant import league_build, make_combatant
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.report import format_result
from pogo_sim.simple_policy import SimplePolicy
from pogo_sim.team import Team
from pogo_sim.timeline import format_timeline, team_names

gm = load_gamemaster()

def team(index, *members):
    return Team(tuple(make_combatant(gm, league_build(gm, s, 1500, f, c), index) for s, f, c in members), shields=2)

a = team(0, ("azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), ("medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC")),
         ("registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON")))
b = team(1, ("swampert", "MUD_SHOT", ("HYDRO_CANNON", "EARTHQUAKE")), ("altaria", "DRAGON_BREATH", ("SKY_ATTACK", "MOONBLAST")),
         ("trevenant", "SHADOW_CLAW", ("SEED_BOMB", "SHADOW_BALL")))
result = Battle((a, b), (SimplePolicy(), SimplePolicy())).run()
print(format_result(result, ("Team A", "Team B")))
print(format_timeline(result.events, team_names((a, b))))
```

输出（节选）：

```
Team B wins: rating 435 vs 564, Pokemon left 0 vs 1, shields left 0 vs 0, 130 turns
...
T  53  Swampert        CHARGED HYDRO_CANNON -> 36 dmg, Azumarill HP 1, energy 13
T  53  Azumarill       CHARGED ICE_BEAM -> 51 dmg, Swampert HP 0, energy 0
T  53  Swampert        FAINTS
T  54  Swampert        sends in Altaria
...
```

把 `SimplePolicy()` 换成 `TeamPolicy()`（`pogo_sim/team_policy.py`）就是 3v3 策略：倒下后换上对位评分最高的；当前对位不好、后备里有明显更好的就主动换人；不在必输的对位上开盾。原因里列出对位评分，例如 `switch: matchup vs Swampert 297 < 450, Medicham 539 >= 500 (Medicham 539)`。同样这两队都用 `TeamPolicy`：B 赢，评分 387 vs 612，126 回合，换人 7 次。规则和参数见 [docs/mechanics.md](docs/mechanics.md) 13.7。

按剧本换人（`ScriptedPolicy(switches={回合: 换上第几只}, replacements=...)`）可以复现某一场的具体过程。评分是本项目的口径：把 PvPoke 的 1v1 评分推广到全队（第 13.2 节 D1）。

### 用配置文件跑 3v3

两队写在一个 TOML 文件里（格式见 `pogo_sim/team_battle.py` 开头，例子 `experiments/gl_3v3_example.toml`），双方都用 `TeamPolicy`；策略参数和机制开关可以在文件里改，也可以只改某一队的：

```bash
.venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml --output docs/experiments/gl_3v3_example.md
```

建配置时检查队伍：每队 3 只、同一种宝可梦不能带两只（按图鉴编号，暗影、Mega、地区形态都算同一种）、Mega 不超过 1 只。报告（[docs/experiments/gl_3v3_example.md](docs/experiments/gl_3v3_example.md)）里有两队的配置和策略参数、结果、每只的情况（剩余 HP、伤害、放了哪些大招、挨大招时开没开盾）、开局对位评分、每次换人和开盾的原因，最后是带原因的完整时间线。例子没写 IV，用的是 IV 排名第 1，所以结果（B 赢，评分 221 vs 778，100 回合）和上面用 PvPoke 默认 IV 的那一场不同。

### 队伍对队伍

我方写一队或几队，对手是手写的几队，加上从 PvPoke 排名的环境前 N 随机抽的若干队，每一对打一场 3v3（格式见 `pogo_sim/team_matrix.py` 开头，例子 `experiments/gl_team_matrix_example.toml`）。队伍的写法和 3v3 配置一样，对手写成 `[[opponent_team]]`；抽样这样写：

```toml
[opponent_sample]
rankings = "mega"   # 从哪套排名抽
top = 30            # 非 Mega 从前 30 只里抽
mega_top = 10       # 每队 1 只 Mega，从 Mega 前 10 只里抽（0：不带 Mega）
count = 50          # 抽 50 队
seed = 1            # 随机种子：同一个种子每次抽出同样的队伍
```

每队同一种不重复（按图鉴编号），出场顺序也随机，均匀抽、不按名次加权。

```bash
.venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --output docs/experiments/gl_team_matrix_example.md
.venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --battle "Team A" "抽样 3"
```

报告（[docs/experiments/gl_team_matrix_example.md](docs/experiments/gl_team_matrix_example.md)）先是总表：我方每一队对手写的、抽样的、全部对手各赢平输几场、平均评分、平均剩余只数；然后我方每一队一张表，一场一行（对手成员、结果、评分、剩余只数和盾、回合数）；最后列出每一队对手和抽样的候选。`--battle` 只打其中一场，输出上面那种完整的 3v3 报告；`--csv` 把全部对战另存成一场一行的 CSV。例子里 Team A 对 51 队赢 13 场，把 Registeel 换成 Mega 雪妖女后赢 24 场。

### 对固定对手策略的应对

对手的策略不变（`TeamPolicy`），搜索我方更好的打法（`pogo_sim/best_response.py`，方法见 [docs/mechanics.md](docs/mechanics.md) 13.11）：

```bash
.venv/bin/python -m tools.run_team_battle experiments/gl_3v3_example.toml --best-response "Team A" --output docs/experiments/gl_3v3_best_response.md
```

```bash
.venv/bin/python -m tools.run_team_matrix experiments/gl_team_matrix_example.toml --battle "Team A" "抽样 3" --best-response
```

方法是"逐步试探"：先让双方照原策略打一场，然后沿着当前最好的一场，把我方每个决定点（出招、主动换人、0 回合换人、开盾、选人）的其余选项都试一遍，之后照各自的策略打完；先比胜负再比评分，严格更好就改。结果不比原策略差，但不保证全局最优；搜索完全知道对手策略会怎么应对，所以是针对这个策略的打法。

报告（[docs/experiments/gl_3v3_best_response.md](docs/experiments/gl_3v3_best_response.md)）里有原策略和搜索后的结果、改了哪些决定（每个决定点各选项打出来的结果），以及搜索后的这一场的完整过程。例子里 Team A 照原策略输（221），搜索改了 5 个决定后赢（593）：开局换上 Medicham 对 Swampert、第 11 回合不开盾、第 21 回合先放 ICE_PUNCH，最后两次 0 回合换人。

## 自定义宝可梦和招式

未发布的宝可梦、招式，或对已有条目的修正，写在 `data/custom/` 下的 TOML 文件里（字段名与 gamemaster.json 相同），加载时显式传入：

```python
from pogo_sim.gamemaster import load_gamemaster

gm = load_gamemaster(custom_files=["data/custom/mega_froslass.toml"])
print("\n".join(gm.custom_log))
# mega_froslass.toml：新招式 AVALANCHE_PLUS（name "Avalanche+"，type "ice"，power 75，...）
# mega_froslass.toml：新宝可梦 froslass_mega（Froslass (Mega)）：种族值 289/194/172（由正作 70/80/70/140/100/120 换算，...）
```

宝可梦可以只给正作六项能力值（`mainSeriesStats`），加载时自动换算成 GO 种族值（含 0.91 / Mega 0.97 削弱）。格式和检查规则见 [docs/mechanics.md](docs/mechanics.md) 第 10 节，示例见 `data/custom/mega_froslass.toml`。

## IV 排名

```python
from pogo_sim.iv_ranking import find_rank, rank_species_ivs
from pogo_sim.stats import IVs

ranking = rank_species_ivs(gm.get_species("froslass_mega"), 1500)  # 可选 level_cap、iv_floor、level_floor
print(ranking[0].describe())                            # IV 4/15/15，14.5 级，CP 1498，第 1 名（100.00%）
print(find_rank(ranking, IVs(15, 15, 15)).describe())  # IV 15/15/15，13.5 级，CP 1448，第 3696 名（92.53%）
```

做法和默认的 IV 下限见 [docs/mechanics.md](docs/mechanics.md) 第 11 节。

## 按赛季规则建立配置

```python
from pogo_sim.season import MEGA_PLUS_2, season_build

# 默认 PvPoke 兼容规则；不指定 IV 和等级时用 IV 排名第 1、合法的最高等级
build = season_build(gm, "froslass_mega", 1500, "POWDER_SNOW", ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"])
print("\n".join(build.notes))
# 赛季规则：PvPoke 兼容；超级联盟
# Mega 等级 4（默认）
# Mega 等级上限 52（适用条件：只限 Mega 等级 ≥ 4，大师联盟除外）
# IV 4/15/15：超级联盟 IV 排名第 1（能力值乘积最大；IV 下限 0，共 4096 个组合）
# 等级 14.5：52 级时 CP 4187 超过 1500，自动降到 CP 不超过上限的最高等级（CP 1498）

# 其他赛季规则、挚友、指定 IV / 等级 / Mega 等级
build = season_build(gm, "froslass_mega", 10000, "POWDER_SNOW", ["AVALANCHE"], season=MEGA_PLUS_2, best_buddy=True)
```

预设和各项规则见 [docs/mechanics.md](docs/mechanics.md) 第 7 节。

## 对战配置文件：换配招、对手不用改代码

把要比较的配招和对手写进一个 TOML 文件，每一对打 0–2 盾对 0–2 盾的九宫格：

```toml
league = 10000
season = "pvpoke"                                  # 或 mega_cap_52 / mega_cap_55 / mega_plus_2
custom_files = ["data/custom/mega_zygarde.toml"]   # 自定义宝可梦、招式，以及赛季的招式调整

[[subject]]
label = "Bite + Bulldoze"
species = "zygarde_mega"
fast = "BITE"
charged = ["CRUNCH", "BULLDOZE", "NIHIL_LIGHT"]

[[opponent]]
label = "Mega Mewtwo Y (Avalanche)"
species = "mewtwo_mega_y"
fast = "PSYCHO_CUT"
charged = ["PSYSTRIKE", "AVALANCHE", "FUTURE_SIGHT_PLUS"]
outside_movepool = true                            # GO 里超梦不会 Avalanche：明确写出这是假设
```

```bash
.venv/bin/python -m tools.run_matchups experiments/mega_zygarde_ml.toml
```

完整格式（IV、等级、挚友、策略参数等）见 `pogo_sim/matchups.py` 开头，例子见 [experiments/mega_zygarde_ml.toml](experiments/mega_zygarde_ml.toml)，结果见 [docs/experiments/mega_zygarde_ml.md](docs/experiments/mega_zygarde_ml.md)。评分的含义见 [docs/mechanics.md](docs/mechanics.md) 6.5 节。

### 对环境前 N

对手也可以直接取 PvPoke 排名里的前 N 只（排名快照在 `data/rankings/`），配招用 PvPoke 的推荐。有 Mega 的规则下 Mega 和非 Mega 分开取：

```toml
[[opponent_pool]]
name = "Mega 前 10"
rankings = "mega"        # PvPoke 的排名："all"（普通联盟，不含 Mega）/ "mega"（Mega 版）
kind = "mega"            # "mega" / "non_mega"
top = 10
# ivs = "pvpoke_default" 默认是 IV 排名第 1（和不写 IV 的配置一样）；改成 PvPoke 默认 IV 方便对照 PvPoke

[[opponent_pool]]
name = "非 Mega 前 50"
rankings = "mega"
kind = "non_mega"
top = 50
```

```bash
.venv/bin/python -m tools.run_matchups experiments/gl_mega_froslass_top.toml --output docs/experiments/gl_mega_froslass_top.md
.venv/bin/python -m tools.run_matchups experiments/gl_mega_froslass_top.toml --timeline "Mega Froslass (Powder Snow)" "Sableye (Mega)" 1 1
```

报告（[docs/experiments/gl_mega_froslass_top.md](docs/experiments/gl_mega_froslass_top.md)）里每组环境前 N 一节：对手的名次、CP、等级、IV、配招；每个测试对象赢了几只（双方 0、1、2 盾）、九种盾数一共赢了几格、平均评分；再按对手一行列出九宫格，赢的加粗。`--csv` 把全部评分另存成一场一行的 CSV。

## 未发布 Mega 的 1v1（完整流程）

覆盖文件 → 按赛季规则建配置 → 简单规则策略对战 → 报告：

```python
from pogo_sim.battle import Battle
from pogo_sim.combatant import make_combatant
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.report import format_result, format_setup
from pogo_sim.season import season_build
from pogo_sim.simple_policy import SimplePolicy
from pogo_sim.team import Team
from pogo_sim.timeline import format_timeline

gm = load_gamemaster(custom_files=["data/custom/mega_froslass.toml"])
froslass = make_combatant(gm, season_build(gm, "froslass_mega", 1500, "POWDER_SNOW", ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]), 0)
azumarill = make_combatant(gm, season_build(gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"]), 1)
teams = (Team((froslass,), shields=2), Team((azumarill,), shields=2))
names = (froslass.name, azumarill.name)

print(format_setup(teams))  # 要在对战开始前调用：盾数会在对战中变化
result = Battle(teams, (SimplePolicy(), SimplePolicy())).run()
print(format_result(result, names))
print(format_timeline(result.events, names, show_decisions=True))
```

输出（节选）：

```
[0] Froslass (Mega)  CP 1498  level 14.5  IV 4/15/15  Mega level 4  shields 2
    HP 95  atk 149.05  def 106.32
    fast POWDER_SNOW  charged AVALANCHE, SHADOW_BALL, AVALANCHE_PLUS
    build notes:
      赛季规则：PvPoke 兼容；超级联盟
      Mega 等级 4（默认）
      Mega 等级上限 52（适用条件：只限 Mega 等级 ≥ 4，大师联盟除外）
      IV 4/15/15：超级联盟 IV 排名第 1（能力值乘积最大；IV 下限 0，共 4096 个组合）
      等级 14.5：52 级时 CP 4187 超过 1500，自动降到 CP 不超过上限的最高等级（CP 1498）

[1] Azumarill  CP 1499  level 45.5  IV 0/15/15  shields 2
    ...
Froslass (Mega) wins: rating 578 vs 421, HP left 15 vs 0, 49 turns
T   1  Froslass (Mega) decides fast POWDER_SNOW  (energy 0 < 35 needed for AVALANCHE_PLUS)
...
T  15  Froslass (Mega) decides charged AVALANCHE_PLUS  (bait: opponent has 2 shield(s), throw AVALANCHE_PLUS (35) instead of SHADOW_BALL)
T  15  Froslass (Mega) CHARGED AVALANCHE_PLUS -> 1 dmg (shielded), Azumarill HP 167, energy 21  [shield: always shield (2 left)]
...
T  49  Froslass (Mega) CHARGED AVALANCHE_PLUS -> 52 dmg, Azumarill HP 0, energy 5
T  49  Azumarill       BUBBLE cancelled (knocked out by a charged move this turn)
T  49  Azumarill       FAINTS
```

Avalanche+ 的数值是假设的（见 `data/custom/mega_froslass.toml`），这个结果只说明流程能跑通，不代表 Mega 雪妖女的真实强度。

## PvPoke 参考数据

`tests/fixtures/` 里的参考数据由 PvPoke 源码计算，已入库，所以跑 pytest 不需要 Node。
只有要重新生成时才需要：

1. 准备 PvPoke 源码，固定在与 `data/` 快照相同的 commit（只取 `src/js/`，约 2 MB）：

   ```bash
   git init <目录> && cd <目录>
   git remote add origin https://github.com/pvpoke/pvpoke.git
   git sparse-checkout set --no-cone '/src/js/' '/LICENSE*' '/README*'
   git fetch --depth 1 --filter=blob:none origin d02018eb6bfc4a041cca69d7bc9de0d5179a8365
   git checkout FETCH_HEAD
   ```

2. 在本仓库根目录运行（需要 Node）：

   ```bash
   node tools/pvpoke_ref/export_damage_reference.js --pvpoke <目录>
   node tools/pvpoke_ref/export_battle_reference.js --pvpoke <目录>
   node tools/pvpoke_ref/export_iv_reference.js --pvpoke <目录>
   node tools/pvpoke_ref/export_switch_reference.js --pvpoke <目录>
   ```

PvPoke 源码不入本仓库。

## 数据来源

宝可梦和技能数据、排名来自 [PvPoke](https://github.com/pvpoke/pvpoke)（MIT license），详见 `data/SOURCE.md`。
