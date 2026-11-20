Mega 基格尔德在大师联盟：几套配招对原始盖欧卡、Mega 超梦Y（三套配招）、酋雷姆（白）、洛奇亚。

- 配置文件：`experiments/mega_zygarde_ml.toml`
- 联盟：大师联盟；赛季规则：PvPoke 兼容
- 策略：双方都是简单规则策略，参数 SimplePolicyConfig(charged_move_choice='best_dpe', optimize_timing=True, bait_shields=True, shielding='always', shield_hp_fraction=0.5)
- 评分：PvPoke 的对战评分，从测试对象一方看。500 × 对手损失的 HP 比例 + 500 × 自己剩余的 HP 比例，向下取整；大于 500 算赢
- 覆盖文件：mega_zygarde.toml：新招式 NIHIL_LIGHT（name "Nihil Light"，type "dragon"，power 130，energy 80，energyGain 0，turns 1，isMegaMove true）
- 覆盖文件：mega_zygarde.toml：新宝可梦 zygarde_mega（Zygarde (Mega)）：种族值 403/181/415（由正作 216/70/91/216/85/100 换算，Mega 规则：只套公式 416/187/428，40 级满 IV CP 8052 ≥ 6000，乘 0.97）

测试对象：

- Dragon Tail + Bulldoze：Zygarde (Mega)，CP 8568，50 级，IV 15/15/15，DRAGON_TAIL / CRUNCH, BULLDOZE, NIHIL_LIGHT
- Bite + Bulldoze：Zygarde (Mega)，CP 8568，50 级，IV 15/15/15，BITE / CRUNCH, BULLDOZE, NIHIL_LIGHT
- Dragon Tail + Earthquake：Zygarde (Mega)，CP 8568，50 级，IV 15/15/15，DRAGON_TAIL / CRUNCH, EARTHQUAKE, NIHIL_LIGHT

对手：

- Primal Kyogre：Kyogre (Primal)，CP 6672，50 级，IV 15/15/15，WATERFALL / AVALANCHE, THUNDER
- Mega Mewtwo Y (Thunderbolt)：Mewtwo (Mega Y)，CP 7267，50 级，IV 15/15/15，PSYCHO_CUT / PSYSTRIKE, THUNDERBOLT, FUTURE_SIGHT_PLUS
- Mega Mewtwo Y (Ice Beam)：Mewtwo (Mega Y)，CP 7267，50 级，IV 15/15/15，PSYCHO_CUT / PSYSTRIKE, ICE_BEAM, FUTURE_SIGHT_PLUS
- Mega Mewtwo Y (Avalanche)*：Mewtwo (Mega Y)，CP 7267，50 级，IV 15/15/15，PSYCHO_CUT / PSYSTRIKE, AVALANCHE, FUTURE_SIGHT_PLUS（招式池外：AVALANCHE）
- Kyurem White：Kyurem (White)，CP 5206，50 级，IV 15/15/15，DRAGON_BREATH / FUSION_FLARE, ICE_BURN
- Lugia：Lugia，CP 4186，50 级，IV 15/15/15，DRAGON_TAIL / AEROBLAST, EARTH_POWER

\* 带了招式池外的招式（假设）。

## 总表

每格是 0–2 盾对 0–2 盾九场里赢了几场，以及九场的平均评分。

| 测试对象 \ 对手 | Primal Kyogre | Mega Mewtwo Y (Thunderbolt) | Mega Mewtwo Y (Ice Beam) | Mega Mewtwo Y (Avalanche)* | Kyurem White | Lugia |
|---|---|---|---|---|---|---|
| Dragon Tail + Bulldoze | 4/9 胜，平均 514 | 6/9 胜，平均 581 | 3/9 胜，平均 441 | 3/9 胜，平均 419 | 7/9 胜，平均 680 | 9/9 胜，平均 794 |
| Bite + Bulldoze | 3/9 胜，平均 436 | 6/9 胜，平均 605 | 4/9 胜，平均 510 | 3/9 胜，平均 412 | 4/9 胜，平均 476 | 9/9 胜，平均 803 |
| Dragon Tail + Earthquake | 4/9 胜，平均 505 | 6/9 胜，平均 581 | 3/9 胜，平均 441 | 3/9 胜，平均 419 | 6/9 胜，平均 635 | 9/9 胜，平均 794 |

## 九宫格

| Dragon Tail + Bulldoze 对 Primal Kyogre | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 379 | 143 | 143 |
| 自己 1 盾 | 857 | 494 | 258 |
| 自己 2 盾 | 857 | 785 | 714 |

| Dragon Tail + Bulldoze 对 Mega Mewtwo Y (Thunderbolt) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 513 | 225 | 225 |
| 自己 1 盾 | 911 | 668 | 289 |
| 自己 2 盾 | 911 | 880 | 609 |

| Dragon Tail + Bulldoze 对 Mega Mewtwo Y (Ice Beam) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 127 | 127 | 127 |
| 自己 1 盾 | 921 | 257 | 257 |
| 自己 2 盾 | 921 | 880 | 352 |

| Dragon Tail + Bulldoze 对 Mega Mewtwo Y (Avalanche) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 95 | 95 | 95 |
| 自己 1 盾 | 921 | 223 | 223 |
| 自己 2 盾 | 921 | 880 | 321 |

| Dragon Tail + Bulldoze 对 Kyurem White | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 854 | 277 | 277 |
| 自己 1 盾 | 854 | 765 | 736 |
| 自己 2 盾 | 854 | 765 | 735 |

| Dragon Tail + Bulldoze 对 Lugia | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 903 | 652 | 624 |
| 自己 1 盾 | 903 | 846 | 637 |
| 自己 2 盾 | 903 | 846 | 831 |

| Bite + Bulldoze 对 Primal Kyogre | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 315 | 79 | 79 |
| 自己 1 盾 | 857 | 379 | 143 |
| 自己 2 盾 | 857 | 761 | 458 |

| Bite + Bulldoze 对 Mega Mewtwo Y (Thunderbolt) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 513 | 218 | 218 |
| 自己 1 盾 | 911 | 891 | 276 |
| 自己 2 盾 | 911 | 891 | 619 |

| Bite + Bulldoze 对 Mega Mewtwo Y (Ice Beam) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 137 | 137 | 137 |
| 自己 1 盾 | 911 | 891 | 237 |
| 自己 2 盾 | 911 | 891 | 338 |

| Bite + Bulldoze 对 Mega Mewtwo Y (Avalanche) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 98 | 98 | 98 |
| 自己 1 盾 | 911 | 198 | 198 |
| 自己 2 盾 | 911 | 890 | 306 |

| Bite + Bulldoze 对 Kyurem White | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 405 | 105 | 105 |
| 自己 1 盾 | 814 | 490 | 190 |
| 自己 2 盾 | 814 | 725 | 638 |

| Bite + Bulldoze 对 Lugia | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 916 | 666 | 624 |
| 自己 1 盾 | 916 | 860 | 637 |
| 自己 2 盾 | 916 | 860 | 831 |

| Dragon Tail + Earthquake 对 Primal Kyogre | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 315 | 143 | 143 |
| 自己 1 盾 | 880 | 430 | 258 |
| 自己 2 盾 | 880 | 785 | 714 |

| Dragon Tail + Earthquake 对 Mega Mewtwo Y (Thunderbolt) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 513 | 225 | 225 |
| 自己 1 盾 | 911 | 668 | 289 |
| 自己 2 盾 | 911 | 880 | 609 |

| Dragon Tail + Earthquake 对 Mega Mewtwo Y (Ice Beam) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 127 | 127 | 127 |
| 自己 1 盾 | 921 | 257 | 257 |
| 自己 2 盾 | 921 | 880 | 352 |

| Dragon Tail + Earthquake 对 Mega Mewtwo Y (Avalanche) | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 95 | 95 | 95 |
| 自己 1 盾 | 921 | 223 | 223 |
| 自己 2 盾 | 921 | 880 | 321 |

| Dragon Tail + Earthquake 对 Kyurem White | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 497 | 277 | 277 |
| 自己 1 盾 | 833 | 765 | 736 |
| 自己 2 盾 | 833 | 765 | 735 |

| Dragon Tail + Earthquake 对 Lugia | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |
|---|---|---|---|
| 自己 0 盾 | 903 | 652 | 624 |
| 自己 1 盾 | 903 | 846 | 637 |
| 自己 2 盾 | 903 | 846 | 831 |
