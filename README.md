# Pokémon GO PvP 对战模拟器

一个透明、可调的 Pokémon GO PvP 模拟器。目标是让 3v3 的过程和策略假设都看得见，并支持加入未发布的宝可梦（如新 Mega）。

当前进度：数据层和数值层（CP / 能力值 / 正作数值换算）。战斗引擎尚未实现，机制规格见 [docs/mechanics.md](docs/mechanics.md)。

## 目录

- `pogo_sim/`：Python 包
  - `cpm.py`：等级与 CP 倍率（CPM）表
  - `stats.py`：IV、CP、HP、实际攻防
  - `conversion.py`：正作六项能力值 → GO 种族值
  - `gamemaster.py`：读取 PvPoke gamemaster.json
- `tests/`：pytest 测试
- `data/`：PvPoke gamemaster.json 快照（来源见 `data/SOURCE.md`）
- `docs/`：机制规格文档

## 开发环境

所有命令都通过项目自己的 venv 运行：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

## 数据来源

宝可梦和技能数据来自 [PvPoke](https://github.com/pvpoke/pvpoke)（MIT license），详见 `data/SOURCE.md`。
