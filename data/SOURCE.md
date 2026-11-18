# 数据来源

## gamemaster.json

- 来源：PvPoke（https://github.com/pvpoke/pvpoke），文件 `src/data/gamemaster.json`
- 下载日期：2026-11-17
- 对应 PvPoke commit：`d02018eb6bfc4a041cca69d7bc9de0d5179a8365`
  （master 分支，提交时间 2026-11-17T13:57:45Z，提交说明 "Magnet Bomb Magnezone"）
- 下载地址：
  https://raw.githubusercontent.com/pvpoke/pvpoke/d02018eb6bfc4a041cca69d7bc9de0d5179a8365/src/data/gamemaster.json
- 文件内部时间戳（`timestamp` 字段）：2026-11-17 14:44:05
- SHA-256：`eb741d416a1070131932166b1a65c4217623e6c9f274b5504e6a92598075ca2f`
- 内容：1753 条宝可梦、357 条技能

文件按原样保存，不做任何修改。自定义宝可梦和技能放在单独的覆盖文件里。

## License

PvPoke 以 MIT license 发布（Copyright (c) 2019 pvpoke）。本项目只读取它的数据文件，
并在 `docs/mechanics.md` 中参考它的源码来整理机制；没有复制它的代码。

MIT license 全文见：https://github.com/pvpoke/pvpoke/blob/master/LICENSE

## 更新快照的方法

1. 查 PvPoke master 的最新 commit hash。
2. 用带 commit hash 的 raw 地址下载（不要用 `master`，保证可复现）。
3. 更新本文件里的日期、commit、时间戳、SHA-256 和条目数。
4. 跑一遍 `.venv/bin/python -m pytest`，数值对比测试如有变化要逐个查原因。
