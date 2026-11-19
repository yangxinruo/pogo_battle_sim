# 简单规则策略 vs PvPoke AI

本文件由 `tools/compare_simple_policy.py` 生成，不要手改；分析见 `docs/mechanics.md` 8.6。
对局：`tests/fixtures/pvpoke_battle_reference.json` 的 52 场（PvPoke commit `d02018e`）。
引擎已与 PvPoke 逐回合一致，所以下面的差异全部来自决策。双方用同一种配置。

## 各配置总览

| 配置 | 胜负与 PvPoke 相同 | 大招序列完全相同 | 评分平均差（左方，满分 1000） |
|---|---|---|---|
| 默认：骗盾 + 出招时机 + 总是开盾 | 49/52 | 16/52 | 38 |
| 不骗盾 | 48/52 | 18/52 | 46 |
| 不优化出招时机 | 51/52 | 13/52 | 25 |
| HP 会低于 50% 才开盾 | 49/52 | 13/52 | 45 |
| 能放就放（最便宜的招） | 47/52 | 5/52 | 72 |

## 逐场明细（默认：骗盾 + 出招时机 + 总是开盾）

评分是 PvPoke 的对战评分（左方:右方）。"第一处不同"列出双方大招序列第一个不一样的地方，括号里是我们那一步的决策原因。

| 对局 | 盾 | PvPoke | 我们 | 胜负 | 第一处不同 |
|---|---|---|---|---|---|
| Azumarill vs Medicham | 0-0 | 657:342 | 709:290 | 同 | 第 3 个大招：PvPoke T36 Medicham ICE_PUNCH；我们 T37 Azumarill ICE_BEAM（ICE_BEAM deals 40 >= opponent HP 10, no shields） |
| Azumarill vs Medicham | 1-1 | 675:324 | 675:324 | 同 | 第 1 个大招：PvPoke T21 Medicham PSYCHIC，被挡；我们 T21 Medicham ICE_PUNCH，被挡（bait: opponent has 1 shield(s), throw ICE_PUNCH (40) instead of PSYCHIC） |
| Azumarill vs Medicham | 2-2 | 743:256 | 620:379 | 同 | 第 1 个大招：PvPoke T21 Medicham PSYCHIC，被挡；我们 T21 Medicham ICE_PUNCH，被挡（bait: opponent has 2 shield(s), throw ICE_PUNCH (40) instead of PSYCHIC） |
| Azumarill vs Medicham | 2-0 | 827:172 | 827:172 | 同 | 第 1 个大招：PvPoke T21 Medicham PSYCHIC，被挡；我们 T21 Medicham ICE_PUNCH，被挡（bait: opponent has 2 shield(s), throw ICE_PUNCH (40) instead of PSYCHIC） |
| Azumarill vs Medicham | 0-2 | 502:497 | 502:497 | 同 | 大招序列完全相同 |
| Medicham vs Registeel | 0-0 | 659:340 | 659:340 | 同 | 大招序列完全相同 |
| Medicham vs Registeel | 1-1 | 737:262 | 741:258 | 同 | 第 1 个大招：PvPoke T13 Medicham POWER_UP_PUNCH；我们 T13 Medicham POWER_UP_PUNCH，被挡（POWER_UP_PUNCH ready (15 dmg, target by best_dpe)） |
| Medicham vs Registeel | 2-2 | 872:127 | 872:127 | 同 | 第 2 个大招：PvPoke T18 Registeel ZAP_CANNON，被挡；我们 T18 Registeel FOCUS_BLAST，被挡（bait: opponent has 2 shield(s), throw FOCUS_BLAST (75) instead of ZAP_CANNON） |
| Registeel vs Altaria | 0-0 | 724:275 | 724:275 | 同 | 第 1 个大招：PvPoke T14 Altaria MOONBLAST；我们 T14 Altaria SKY_ATTACK（SKY_ATTACK ready (20 dmg, target by best_dpe)） |
| Registeel vs Altaria | 1-1 | 658:341 | 666:333 | 同 | 第 1 个大招：PvPoke T14 Altaria MOONBLAST，被挡；我们 T14 Altaria SKY_ATTACK，被挡（SKY_ATTACK ready (20 dmg, target by best_dpe)） |
| Registeel vs Altaria | 2-2 | 546:453 | 604:395 | 同 | 第 1 个大招：PvPoke T14 Altaria MOONBLAST，被挡；我们 T14 Altaria SKY_ATTACK，被挡（SKY_ATTACK ready (20 dmg, target by best_dpe)） |
| Swampert vs Walrein | 0-0 | 425:574 | 425:574 | 同 | 大招序列完全相同 |
| Swampert vs Walrein | 1-1 | 457:542 | 487:512 | 同 | 第 3 个大招：PvPoke T27 Swampert EARTHQUAKE；我们 T23 Walrein ICICLE_SPEAR（ICICLE_SPEAR ready (57 dmg, target by best_dpe)） |
| Swampert vs Walrein | 2-2 | 298:701 | 298:701 | 同 | 大招序列完全相同 |
| Machamp (Shadow) vs Registeel | 0-0 | 244:755 | 244:755 | 同 | 大招序列完全相同 |
| Machamp (Shadow) vs Registeel | 1-1 | 879:120 | 814:185 | 同 | 第 1 个大招：PvPoke T18 Registeel ZAP_CANNON，被挡；我们 T16 Registeel FOCUS_BLAST，被挡（FOCUS_BLAST ready (114 dmg, target by best_dpe)） |
| Machamp (Shadow) vs Registeel | 2-2 | 879:120 | 814:185 | 同 | 第 1 个大招：PvPoke T18 Registeel ZAP_CANNON，被挡；我们 T16 Registeel FOCUS_BLAST，被挡（FOCUS_BLAST ready (114 dmg, target by best_dpe)） |
| Obstagoon vs Medicham | 0-0 | 138:861 | 198:801 | 同 | 第 1 个大招：PvPoke T15 Obstagoon OBSTRUCT；我们 T13 Obstagoon NIGHT_SLASH（NIGHT_SLASH ready (32 dmg, target by best_dpe)） |
| Obstagoon vs Medicham | 1-1 | 152:847 | 109:890 | 同 | 第 1 个大招：PvPoke T15 Obstagoon OBSTRUCT；我们 T13 Obstagoon NIGHT_SLASH，被挡（NIGHT_SLASH ready (32 dmg, target by best_dpe)） |
| Obstagoon vs Medicham | 2-2 | 152:847 | 109:890 | 同 | 第 1 个大招：PvPoke T15 Obstagoon OBSTRUCT；我们 T13 Obstagoon NIGHT_SLASH，被挡（NIGHT_SLASH ready (32 dmg, target by best_dpe)） |
| Obstagoon vs Medicham | 2-0 | 152:847 | 219:780 | 同 | 第 1 个大招：PvPoke T15 Obstagoon OBSTRUCT；我们 T13 Obstagoon NIGHT_SLASH（NIGHT_SLASH ready (32 dmg, target by best_dpe)） |
| Obstagoon vs Medicham | 0-2 | 138:861 | 88:911 | 同 | 第 1 个大招：PvPoke T15 Obstagoon OBSTRUCT；我们 T13 Obstagoon NIGHT_SLASH，被挡（NIGHT_SLASH ready (32 dmg, target by best_dpe)） |
| Galvantula vs Azumarill | 0-0 | 549:450 | 799:200 | 同 | 第 1 个大招：PvPoke T17 Galvantula DISCHARGE；我们 T21 Galvantula DISCHARGE（DISCHARGE ready (71 dmg, target by best_dpe)） |
| Galvantula vs Azumarill | 1-1 | 471:528 | 737:262 | **不同** | 第 1 个大招：PvPoke T17 Galvantula DISCHARGE，被挡；我们 T21 Galvantula DISCHARGE，被挡（DISCHARGE ready (71 dmg, target by best_dpe)） |
| Galvantula vs Azumarill | 2-2 | 704:295 | 680:319 | 同 | 第 1 个大招：PvPoke T17 Galvantula LUNGE，被挡；我们 T21 Galvantula DISCHARGE，被挡（DISCHARGE ready (71 dmg, target by best_dpe)） |
| Mamoswine vs Altaria | 0-0 | 869:130 | 869:130 | 同 | 大招序列完全相同 |
| Mamoswine vs Altaria | 1-1 | 735:264 | 481:518 | **不同** | 第 1 个大招：PvPoke T13 Mamoswine ANCIENT_POWER，被挡；我们 T13 Mamoswine AVALANCHE，被挡（AVALANCHE ready (162 dmg, target by best_dpe)） |
| Mamoswine vs Altaria | 2-2 | 724:275 | 721:278 | 同 | 第 1 个大招：PvPoke T14 Altaria MOONBLAST，被挡；我们 T13 Mamoswine AVALANCHE，被挡（AVALANCHE ready (162 dmg, target by best_dpe)） |
| Azumarill(A) vs Azumarill(B) | 0-0 | 500:500 | 500:500 | 同 | 大招序列完全相同 |
| Azumarill(A) vs Azumarill(B) | 1-1 | 500:500 | 500:500 | 同 | 第 1 个大招：PvPoke T19 Azumarill(A) PLAY_ROUGH，被挡；我们 T19 Azumarill(A) ICE_BEAM，被挡（bait: opponent has 1 shield(s), throw ICE_BEAM (55) instead of PLAY_ROUGH） |
| Azumarill(A) vs Azumarill(B) | 2-2 | 500:500 | 500:500 | 同 | 第 1 个大招：PvPoke T19 Azumarill(A) PLAY_ROUGH，被挡；我们 T19 Azumarill(A) ICE_BEAM，被挡（bait: opponent has 2 shield(s), throw ICE_BEAM (55) instead of PLAY_ROUGH） |
| Trevenant vs Swampert | 0-0 | 961:38 | 961:38 | 同 | 大招序列完全相同 |
| Trevenant vs Swampert | 1-1 | 751:248 | 751:248 | 同 | 大招序列完全相同 |
| Trevenant vs Swampert | 2-2 | 709:290 | 709:290 | 同 | 大招序列完全相同 |
| Lickitung vs Umbreon | 0-0 | 403:596 | 400:599 | 同 | 第 5 个大招：PvPoke T40 Umbreon LAST_RESORT；我们 T37 Umbreon FOUL_PLAY（FOUL_PLAY ready (36 dmg, target by best_dpe)） |
| Lickitung vs Umbreon | 1-1 | 352:647 | 339:660 | 同 | 第 7 个大招：PvPoke T55 Lickitung POWER_WHIP；我们 T52 Lickitung BODY_SLAM（BODY_SLAM ready (28 dmg, target by best_dpe)） |
| Lickitung vs Umbreon | 2-2 | 384:615 | 371:628 | 同 | 第 9 个大招：PvPoke T70 Lickitung POWER_WHIP；我们 T67 Lickitung BODY_SLAM（BODY_SLAM ready (28 dmg, target by best_dpe)） |
| Skarmory vs Medicham | 0-0 | 685:314 | 685:314 | 同 | 大招序列完全相同 |
| Skarmory vs Medicham | 1-1 | 516:483 | 537:462 | 同 | 第 1 个大招：PvPoke T15 Medicham ICE_PUNCH；我们 T15 Medicham ICE_PUNCH，被挡（ICE_PUNCH ready (26 dmg, target by best_dpe)） |
| Skarmory vs Medicham | 2-2 | 418:581 | 421:578 | 同 | 第 2 个大招：PvPoke T31 Medicham ICE_PUNCH，被挡；我们 T26 Skarmory SKY_ATTACK，被挡（bait: opponent has 2 shield(s), throw SKY_ATTACK (50) instead of BRAVE_BIRD） |
| Dewgong vs Swampert | 0-0 | 363:636 | 363:636 | 同 | 大招序列完全相同 |
| Dewgong vs Swampert | 1-1 | 566:433 | 444:555 | **不同** | 第 1 个大招：PvPoke T16 Dewgong ICY_WIND，被挡；我们 T16 Dewgong DRILL_RUN，被挡（DRILL_RUN ready (43 dmg, target by best_dpe)） |
| Dewgong vs Swampert | 2-2 | 668:331 | 541:458 | 同 | 第 1 个大招：PvPoke T16 Dewgong ICY_WIND，被挡；我们 T16 Dewgong DRILL_RUN，被挡（DRILL_RUN ready (43 dmg, target by best_dpe)） |
| Typhlosion vs Registeel | 0-0 | 935:64 | 935:64 | 同 | 大招序列完全相同 |
| Typhlosion vs Registeel | 1-1 | 888:111 | 888:111 | 同 | 第 2 个大招：PvPoke T22 Registeel ZAP_CANNON，被挡；我们 T22 Registeel FOCUS_BLAST，被挡（FOCUS_BLAST ready (86 dmg, target by best_dpe)） |
| Typhlosion vs Registeel | 2-2 | 863:136 | 863:136 | 同 | 第 2 个大招：PvPoke T22 Registeel ZAP_CANNON，被挡；我们 T22 Registeel FOCUS_BLAST，被挡（FOCUS_BLAST ready (86 dmg, target by best_dpe)） |
| Giratina (Altered) vs Registeel | 0-0 | 595:404 | 595:404 | 同 | 大招序列完全相同 |
| Giratina (Altered) vs Registeel | 1-1 | 647:352 | 654:345 | 同 | 第 2 个大招：PvPoke T18 Registeel ZAP_CANNON，被挡；我们 T18 Registeel FOCUS_BLAST，被挡（bait: opponent has 1 shield(s), throw FOCUS_BLAST (75) instead of ZAP_CANNON） |
| Giratina (Altered) vs Registeel | 2-2 | 617:382 | 617:382 | 同 | 第 2 个大招：PvPoke T18 Registeel ZAP_CANNON，被挡；我们 T18 Registeel FOCUS_BLAST，被挡（bait: opponent has 2 shield(s), throw FOCUS_BLAST (75) instead of ZAP_CANNON） |
| Mewtwo (Mega X) vs Dialga | 0-0 | 512:487 | 512:487 | 同 | 大招序列完全相同 |
| Mewtwo (Mega X) vs Dialga | 1-1 | 593:406 | 791:208 | 同 | 第 3 个大招：PvPoke T31 Dialga IRON_HEAD；我们 T32 Mewtwo (Mega X) FOCUS_BLAST（FOCUS_BLAST deals 343 >= opponent HP 127, no shields） |
| Mewtwo (Mega X) vs Dialga | 2-2 | 715:284 | 715:284 | 同 | 大招序列完全相同 |
