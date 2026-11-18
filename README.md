# Pokémon GO PvP 对战模拟器

一个透明、可调的 Pokémon GO PvP 模拟器。目标是让 3v3 的过程和策略假设都看得见，并支持加入未发布的宝可梦（如新 Mega）。

当前进度：数据层、数值层（CP / 能力值 / 正作数值换算）和伤害层（属性克制、伤害公式）。回合结算尚未实现，机制规格见 [docs/mechanics.md](docs/mechanics.md)。

## 目录

- `pogo_sim/`：Python 包
  - `cpm.py`：等级与 CP 倍率（CPM）表
  - `stats.py`：IV、CP、HP、实际攻防
  - `conversion.py`：正作六项能力值 → GO 种族值
  - `gamemaster.py`：读取 PvPoke gamemaster.json
  - `rules.py`：所有可配置的机制参数（`BattleRules`）
  - `typechart.py`：属性克制表
  - `damage.py`：伤害公式
- `tests/`：pytest 测试；`tests/fixtures/` 是用 PvPoke 源码生成的参考数据
- `tools/pvpoke_ref/`：在 Node 里运行 PvPoke 源码、生成参考数据的脚本
- `data/`：PvPoke gamemaster.json 快照（来源见 `data/SOURCE.md`）
- `docs/`：机制规格文档

## 开发环境

所有命令都通过项目自己的 venv 运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

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
   ```

PvPoke 源码不入本仓库。

## 数据来源

宝可梦和技能数据来自 [PvPoke](https://github.com/pvpoke/pvpoke)（MIT license），详见 `data/SOURCE.md`。
