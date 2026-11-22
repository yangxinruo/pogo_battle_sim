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

## rankings/（PvPoke 的排名）

- 来源：PvPoke，目录 `src/data/rankings/<cup>/overall/rankings-<CP 上限>.json`，在 `data/rankings/` 下保持同样的目录结构
- 下载日期：2026-11-21
- 对应 PvPoke commit：和 gamemaster.json 相同，`d02018eb6bfc4a041cca69d7bc9de0d5179a8365`。
  六个文件最后一次重新生成都在这个 commit。
- 下载地址：
  https://raw.githubusercontent.com/pvpoke/pvpoke/d02018eb6bfc4a041cca69d7bc9de0d5179a8365/src/data/rankings/all/overall/rankings-1500.json
  （其余文件把 `all` 换成 `mega`、`1500` 换成 `2500` / `10000`）
- 两套排名（cup）：
  - `all`：普通的超级 / 高级 / 大师联盟，不含 Mega（gamemaster 的 cup 定义排除了 `mega` 标签）；
  - `mega`：Mega 版（Mega Great / Ultra / Master League），Mega 和非 Mega 一起排。

| 文件 | 条目数 | SHA-256 |
|---|---|---|
| `all/overall/rankings-1500.json` | 1156 | `273b6292161309814b5a700ce79ea698b0e0a5916b4baca4b059fe5dc62bc404` |
| `all/overall/rankings-2500.json` | 853 | `5b7808a05f8a12334050bd2995637d66ecfc9033cdb6a9a3f2f165518bae4076` |
| `all/overall/rankings-10000.json` | 410 | `213ffb33c17df3590b660d0c5f0571d23b5d0c72d9e85228f67c9f33572f9f3b` |
| `mega/overall/rankings-1500.json` | 1219 | `c5fc5c3cc4ac93f1c66d2e5405f7ddce6c36f830b66590fe50cbee452aa6590e` |
| `mega/overall/rankings-2500.json` | 916 | `29709fd4ada5acde2033aba107f456f124792e53997b8f230123b377b60aec04` |
| `mega/overall/rankings-10000.json` | 473 | `d88abd612aa998599c7ee01aaea4ed5e46b45a708b3171aacf910da9cbe64d2a` |

文件按原样保存。本项目只用每一条的名次（在文件里的顺序）、`speciesId`、推荐配招 `moveset` 和综合分 `score`
（`pogo_sim/rankings.py`），不用里面的对战结果；IV 和等级由本项目按配置决定。

## License

PvPoke 以 MIT license 发布（Copyright (c) 2019 pvpoke）。本项目只读取它的数据文件，
并在 `docs/mechanics.md` 中参考它的源码来整理机制；没有复制它的代码。

MIT license 全文见：https://github.com/pvpoke/pvpoke/blob/master/LICENSE

## 更新快照的方法

1. 查 PvPoke master 的最新 commit hash。
2. 用带 commit hash 的 raw 地址下载（不要用 `master`，保证可复现）。
3. 排名文件用同一个 commit 下载，和 gamemaster 保持一致（排名里的招式和种类要在 gamemaster 里找得到）。
4. 更新本文件里的日期、commit、时间戳、SHA-256 和条目数（`tests/test_rankings.py` 会核对排名文件的 SHA-256）。
5. 跑一遍 `.venv/bin/python -m pytest`，数值对比测试如有变化要逐个查原因。
