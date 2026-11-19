# Pokémon GO PvP 对战模拟器

一个透明、可调的 Pokémon GO PvP 模拟器。目标是让 3v3 的过程和策略假设都看得见，并支持加入未发布的宝可梦（如新 Mega）。

当前进度：1v1 引擎已完成（数值、伤害、回合结算），并与 PvPoke 源码逐回合核对过；有两种策略："按剧本出招"和一组可调的简单规则（与 PvPoke AI 的比较见 [docs/simple_policy_vs_pvpoke.md](docs/simple_policy_vs_pvpoke.md)）。正在做第 2 步（自定义宝可梦与 Mega 规则）：已能用覆盖文件加入未发布的宝可梦和招式，并给 IV 组合排名。机制规格见 [docs/mechanics.md](docs/mechanics.md)。

## 目录

- `pogo_sim/`：Python 包
  - `cpm.py`：等级与 CP 倍率（CPM）表
  - `stats.py`：IV、CP、HP、实际攻防
  - `iv_ranking.py`：联盟 CP 上限下的 IV 排名（按能力值乘积）
  - `conversion.py`：正作六项能力值 → GO 种族值
  - `gamemaster.py`：读取 PvPoke gamemaster.json，并合并覆盖文件
  - `custom.py`：自定义覆盖文件（新宝可梦、新招式、修改已有条目）
  - `rules.py`：所有可配置的机制参数（`BattleRules`）
  - `typechart.py`：属性克制表
  - `damage.py`：伤害公式
  - `combatant.py`：对战中的一只宝可梦（配置 `PokemonBuild` 和对战状态 `Combatant`）
  - `policy.py`：策略接口（出什么招、开不开盾）和剧本策略 `ScriptedPolicy`
  - `simple_policy.py`：简单规则策略 `SimplePolicy`（规则和参数见文件开头）
  - `battle.py`：1v1 回合结算引擎
  - `timeline.py`：时间线事件、逐回合快照、文字日志
- `tests/`：pytest 测试；`tests/fixtures/` 是用 PvPoke 源码生成的参考数据
- `tools/pvpoke_ref/`：在 Node 里运行 PvPoke 源码、生成参考数据的脚本
- `tools/compare_simple_policy.py`：简单规则策略与 PvPoke AI 的比较（`.venv/bin/python -m tools.compare_simple_policy`）
- `data/`：PvPoke gamemaster.json 快照（来源见 `data/SOURCE.md`）
- `data/custom/`：自定义覆盖文件（TOML），格式见 docs/mechanics.md 第 10 节
- `docs/`：机制规格文档

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
from pogo_sim.timeline import format_timeline

gm = load_gamemaster()
azumarill = make_combatant(gm, league_build(gm, "azumarill", 1500, "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0, shields=2)
medicham = make_combatant(gm, league_build(gm, "medicham", 1500, "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1, shields=2)

no_bait = SimplePolicyConfig(bait_shields=False)  # 每个规则都可以单独调
result = Battle((azumarill, medicham), (SimplePolicy(), SimplePolicy(no_bait))).run()
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
from pogo_sim.timeline import format_timeline

gm = load_gamemaster()
azumarill = make_combatant(gm, PokemonBuild("azumarill", 43, IVs(4, 15, 13), "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0, shields=1)
medicham = make_combatant(gm, PokemonBuild("medicham", 49, IVs(7, 15, 14), "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1, shields=1)

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
result = Battle((azumarill, medicham), (azumarill_policy, medicham_policy)).run()
assert azumarill_policy.unused_charged() == [] and medicham_policy.unused_charged() == []
print(result)
print(format_timeline(result.events, (azumarill.name, medicham.name)))
```

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
   ```

PvPoke 源码不入本仓库。

## 数据来源

宝可梦和技能数据来自 [PvPoke](https://github.com/pvpoke/pvpoke)（MIT license），详见 `data/SOURCE.md`。
