队伍对队伍例子：Team A 和换上 Mega 雪妖女的 Team A，在 Mega 超级联盟对手写的 Team B 和随机抽的 50 队。

- 配置文件：`experiments/gl_team_matrix_example.toml`
- 联盟：超级联盟；赛季规则：PvPoke 兼容
- 机制规则：与 PvPoke 一致（默认）
- 覆盖文件：mega_froslass.toml：新招式 AVALANCHE_PLUS（name "Avalanche+"，type "ice"，power 75，energy 35，energyGain 0，turns 1，isMegaMove true）
- 覆盖文件：mega_froslass.toml：新宝可梦 froslass_mega（Froslass (Mega)）：种族值 289/194/172（由正作 70/80/70/140/100/120 换算，Mega 规则：只套公式 289/194/172，40 级满 IV CP 3753 < 6000，不削弱）
- 对战：我方 2 队，每一队对 51 队对手（手写 1 队、随机抽 50 队）各打一场 3v3，我方是第 0 方。对战是确定的，同一个配置每次结果相同
- 策略：每一队都是 3v3 策略 TeamPolicy（规则和默认参数见 docs/mechanics.md 13.7），和默认不同的参数写在各队下面
- 评分：本项目的口径（docs/mechanics.md 13.2 D1），从我方看。500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整；双方加起来 1000
- 想看某一场的完整过程（换人和开盾的原因、时间线）：`tools/run_team_matrix.py` 加 `--battle 我方队伍 对手队伍`

## 我方队伍

**Team A**（2 盾）

- 首发 Azumarill：Azumarill，CP 1499，45.5 级，IV 0/15/15，BUBBLE / ICE_BEAM, PLAY_ROUGH
- 后备 Medicham：Medicham，CP 1499，50 级，IV 5/15/15，COUNTER / ICE_PUNCH, PSYCHIC
- 后备 Registeel：Registeel，CP 1499，23.5 级，IV 2/13/14，LOCK_ON / FOCUS_BLAST, ZAP_CANNON
- 策略：TeamPolicy，默认参数

**Team A (Mega Froslass)**（2 盾）

- 首发 Azumarill：Azumarill，CP 1499，45.5 级，IV 0/15/15，BUBBLE / ICE_BEAM, PLAY_ROUGH
- 后备 Medicham：Medicham，CP 1499，50 级，IV 5/15/15，COUNTER / ICE_PUNCH, PSYCHIC
- 后备 Froslass (Mega)：Froslass (Mega)，CP 1498，14.5 级，IV 4/15/15，POWDER_SNOW / AVALANCHE, SHADOW_BALL, AVALANCHE_PLUS
- 策略：TeamPolicy，默认参数

## 总表

赢、平、输从我方看；平均评分是我方评分的平均。

| 我方队伍 | 对手 | 场数 | 赢 | 平 | 输 | 平均评分 | 平均剩余只数（我方 / 对方） |
|---|---|---|---|---|---|---|---|
| Team A | 手写 | 1 | 0 | 0 | 1 | 221 | 0.00 / 3.00 |
| Team A | 抽样 | 50 | 13 | 0 | 37 | 456 | 0.40 / 1.02 |
| Team A | 全部 | 51 | 13 | 0 | 38 | 452 | 0.39 / 1.06 |
| Team A (Mega Froslass) | 手写 | 1 | 1 | 0 | 0 | 566 | 1.00 / 0.00 |
| Team A (Mega Froslass) | 抽样 | 50 | 23 | 0 | 27 | 509 | 0.76 / 0.80 |
| Team A (Mega Froslass) | 全部 | 51 | 24 | 0 | 27 | 510 | 0.76 / 0.78 |

## Team A 的每一场

评分、剩余只数、剩余盾都是"我方 对 对手"；我方赢的加粗。

| 对手队伍 | 对手（按出场顺序） | 结果 | 评分 | 剩余只数 | 剩余盾 | 回合 |
|---|---|---|---|---|---|---|
| Team B | Swampert、Altaria、Trevenant | 输 | 221 对 778 | 0 对 3 | 0 对 0 | 100 |
| 抽样 1 | Corsola (Galarian) #11、Rillaboom #26、Malamar (Mega) #32 | 输 | 406 对 593 | 0 对 1 | 0 对 0 | 126 |
| 抽样 2 | Audino (Mega) #177、Azumarill #22、Quagsire (Shadow) #13 | 输 | 461 对 538 | 0 对 1 | 0 对 0 | 152 |
| 抽样 3 | Raichu (Mega X) #183、Araquanid #18、Altaria (Shadow) #8 | 输 | 449 对 550 | 0 对 1 | 0 对 0 | 124 |
| 抽样 4 | Cramorant #10、Altaria (Mega) #273、Corviknight (Shadow) #14 | **赢** | 526 对 473 | 1 对 0 | 0 对 0 | 126 |
| 抽样 5 | Fearow #23、Florges #7、Malamar (Mega) #32 | 输 | 481 对 518 | 0 对 1 | 0 对 0 | 114 |
| 抽样 6 | Ninetales #15、Greninja (Mega) #226、Mantine #28 | **赢** | 523 对 476 | 1 对 0 | 0 对 0 | 127 |
| 抽样 7 | Tinkaton #6、Audino (Mega) #177、Altaria (Shadow) #8 | **赢** | 602 对 397 | 2 对 0 | 0 对 0 | 142 |
| 抽样 8 | Altaria (Shadow) #8、Stunfisk #29、Greninja (Mega) #226 | **赢** | 715 对 284 | 2 对 0 | 0 对 0 | 91 |
| 抽样 9 | Quagsire #12、Corviknight #9、Altaria (Mega) #273 | 输 | 329 对 670 | 0 对 2 | 0 对 0 | 137 |
| 抽样 10 | Charizard (Mega X) #283、Marowak #25、Melmetal #2 | 输 | 448 对 551 | 0 对 1 | 0 对 0 | 112 |
| 抽样 11 | Corviknight (Shadow) #14、Florges #7、Audino (Mega) #177 | 输 | 388 对 611 | 0 对 2 | 0 对 0 | 133 |
| 抽样 12 | Quagsire (Shadow) #13、Altaria (Mega) #273、Vigoroth #30 | 输 | 441 对 558 | 0 对 1 | 0 对 0 | 123 |
| 抽样 13 | Mawile (Mega) #201、Mantine #28、Jellicent #31 | 输 | 385 对 614 | 0 对 2 | 0 对 0 | 135 |
| 抽样 14 | Greninja (Mega) #226、Ninetales #15、Araquanid #18 | **赢** | 600 对 399 | 2 对 0 | 0 对 0 | 127 |
| 抽样 15 | Charizard (Mega X) #283、Azumarill #22、Araquanid #18 | 输 | 469 对 530 | 0 对 1 | 0 对 0 | 149 |
| 抽样 16 | Charizard (Mega X) #283、Stunfisk #29、Jellicent #31 | **赢** | 602 对 397 | 1 对 0 | 0 对 0 | 127 |
| 抽样 17 | Raichu (Mega X) #183、Umbreon #21、Quagsire (Shadow) #13 | 输 | 270 对 729 | 0 对 2 | 0 对 0 | 80 |
| 抽样 18 | Houndoom (Mega) #216、Altaria #3、Quagsire #12 | 输 | 464 对 535 | 0 对 1 | 0 对 0 | 137 |
| 抽样 19 | Audino (Mega) #177、Jellicent #31、Marowak #25 | 输 | 379 对 620 | 0 对 2 | 0 对 0 | 133 |
| 抽样 20 | Greninja (Mega) #226、Araquanid #18、Cramorant #10 | **赢** | 503 对 496 | 1 对 0 | 0 对 0 | 132 |
| 抽样 21 | Araquanid #18、Charizard (Mega X) #283、Ninetales #15 | 输 | 363 对 636 | 0 对 2 | 0 对 0 | 124 |
| 抽样 22 | Hydreigon (Shadow) #16、Charizard (Mega X) #283、Ninetales (Shadow) #4 | 输 | 488 对 511 | 0 对 1 | 0 对 0 | 93 |
| 抽样 23 | Houndoom (Mega) #216、Jellicent #31、Cramorant #10 | 输 | 439 对 560 | 0 对 1 | 0 对 0 | 115 |
| 抽样 24 | Altaria (Mega) #273、Hydreigon (Shadow) #16、Ninetales #15 | 输 | 349 对 650 | 0 对 1 | 0 对 0 | 120 |
| 抽样 25 | Altaria (Mega) #273、Rillaboom #26、Corviknight (Shadow) #14 | 输 | 484 对 515 | 0 对 1 | 0 对 0 | 125 |
| 抽样 26 | Dunsparce #24、Corviknight (Shadow) #14、Malamar (Mega) #32 | 输 | 390 对 609 | 0 对 2 | 0 对 0 | 127 |
| 抽样 27 | Dunsparce #24、Altaria (Mega) #273、Mantine #28 | **赢** | 545 对 454 | 1 对 0 | 0 对 0 | 123 |
| 抽样 28 | Ninetales (Shadow) #4、Altaria (Mega) #273、Quagsire (Shadow) #13 | 输 | 490 对 509 | 0 对 1 | 0 对 0 | 120 |
| 抽样 29 | Stunfisk #29、Mawile (Mega) #201、Corviknight (Shadow) #14 | 输 | 359 对 640 | 0 对 2 | 0 对 0 | 122 |
| 抽样 30 | Greninja (Mega) #226、Fearow #23、Sableye (Shadow) #17 | 输 | 349 对 650 | 0 对 2 | 0 对 0 | 98 |
| 抽样 31 | Altaria (Mega) #273、Quagsire (Shadow) #13、Clodsire #20 | 输 | 381 对 618 | 0 对 2 | 0 对 0 | 123 |
| 抽样 32 | Azumarill #22、Altaria #3、Audino (Mega) #177 | 输 | 442 对 557 | 0 对 1 | 0 对 0 | 173 |
| 抽样 33 | Stunfisk #29、Houndoom (Mega) #216、Altaria (Shadow) #8 | 输 | 483 对 516 | 0 对 1 | 0 对 0 | 119 |
| 抽样 34 | Raichu (Mega X) #183、Rillaboom #26、Mantine #28 | 输 | 468 对 531 | 0 对 1 | 0 对 0 | 123 |
| 抽样 35 | Fearow #23、Dragonite (Mega) #206、Clodsire #20 | 输 | 338 对 661 | 0 对 1 | 0 对 0 | 114 |
| 抽样 36 | Hydreigon (Shadow) #16、Quagsire #12、Altaria (Mega) #273 | **赢** | 561 对 438 | 1 对 0 | 0 对 0 | 115 |
| 抽样 37 | Dunsparce #24、Sableye (Mega) #1、Quagsire (Shadow) #13 | **赢** | 612 对 387 | 2 对 0 | 0 对 0 | 123 |
| 抽样 38 | Rillaboom #26、Corsola (Galarian) #11、Altaria (Mega) #273 | 输 | 235 对 764 | 0 对 2 | 0 对 0 | 114 |
| 抽样 39 | Dunsparce #24、Dragonite (Mega) #206、Jellicent #31 | **赢** | 679 对 320 | 2 对 0 | 0 对 0 | 109 |
| 抽样 40 | Greninja (Mega) #226、Quagsire (Shadow) #13、Ninetales (Shadow) #4 | **赢** | 648 对 351 | 2 对 0 | 0 对 0 | 97 |
| 抽样 41 | Raichu (Mega X) #183、Cramorant #10、Fearow #23 | 输 | 389 对 610 | 0 对 2 | 0 对 0 | 103 |
| 抽样 42 | Altaria (Shadow) #8、Mantine #28、Dragonite (Mega) #206 | 输 | 438 对 561 | 0 对 1 | 0 对 0 | 150 |
| 抽样 43 | Dragonite (Mega) #206、Araquanid #18、Altaria (Shadow) #8 | 输 | 459 对 540 | 0 对 1 | 0 对 0 | 132 |
| 抽样 44 | Altaria #3、Audino (Mega) #177、Hydreigon (Shadow) #16 | **赢** | 572 对 427 | 2 对 0 | 0 对 0 | 135 |
| 抽样 45 | Clodsire #20、Ninetales (Shadow) #4、Raichu (Mega X) #183 | 输 | 416 对 583 | 0 对 1 | 0 对 0 | 128 |
| 抽样 46 | Jellicent #31、Mimikyu #5、Dragonite (Mega) #206 | 输 | 322 对 677 | 0 对 2 | 0 对 0 | 119 |
| 抽样 47 | Quagsire (Shadow) #13、Raichu (Mega X) #183、Tinkaton #6 | 输 | 371 对 628 | 0 对 1 | 0 对 0 | 122 |
| 抽样 48 | Tinkaton #6、Raichu (Mega X) #183、Quagsire #12 | 输 | 481 对 518 | 0 对 1 | 0 对 0 | 127 |
| 抽样 49 | Altaria #3、Charizard (Mega X) #283、Marowak #25 | 输 | 440 对 559 | 0 对 1 | 0 对 0 | 116 |
| 抽样 50 | Sableye (Mega) #1、Mimikyu #5、Florges #7 | 输 | 381 对 618 | 0 对 2 | 0 对 0 | 134 |

## Team A (Mega Froslass) 的每一场

评分、剩余只数、剩余盾都是"我方 对 对手"；我方赢的加粗。

| 对手队伍 | 对手（按出场顺序） | 结果 | 评分 | 剩余只数 | 剩余盾 | 回合 |
|---|---|---|---|---|---|---|
| Team B | Swampert、Altaria、Trevenant | **赢** | 566 对 433 | 1 对 0 | 0 对 0 | 108 |
| 抽样 1 | Corsola (Galarian) #11、Rillaboom #26、Malamar (Mega) #32 | 输 | 414 对 585 | 0 对 1 | 0 对 0 | 99 |
| 抽样 2 | Audino (Mega) #177、Azumarill #22、Quagsire (Shadow) #13 | 输 | 419 对 580 | 0 对 2 | 0 对 0 | 123 |
| 抽样 3 | Raichu (Mega X) #183、Araquanid #18、Altaria (Shadow) #8 | 输 | 250 对 750 | 0 对 2 | 0 对 0 | 98 |
| 抽样 4 | Cramorant #10、Altaria (Mega) #273、Corviknight (Shadow) #14 | 输 | 472 对 527 | 0 对 1 | 0 对 0 | 99 |
| 抽样 5 | Fearow #23、Florges #7、Malamar (Mega) #32 | **赢** | 732 对 267 | 2 对 0 | 0 对 0 | 80 |
| 抽样 6 | Ninetales #15、Greninja (Mega) #226、Mantine #28 | 输 | 449 对 550 | 0 对 2 | 0 对 0 | 107 |
| 抽样 7 | Tinkaton #6、Audino (Mega) #177、Altaria (Shadow) #8 | **赢** | 565 对 434 | 2 对 0 | 0 对 0 | 121 |
| 抽样 8 | Altaria (Shadow) #8、Stunfisk #29、Greninja (Mega) #226 | **赢** | 645 对 354 | 1 对 0 | 0 对 0 | 100 |
| 抽样 9 | Quagsire #12、Corviknight #9、Altaria (Mega) #273 | 输 | 435 对 564 | 0 对 1 | 0 对 0 | 120 |
| 抽样 10 | Charizard (Mega X) #283、Marowak #25、Melmetal #2 | **赢** | 549 对 450 | 1 对 0 | 0 对 0 | 100 |
| 抽样 11 | Corviknight (Shadow) #14、Florges #7、Audino (Mega) #177 | 输 | 443 对 556 | 0 对 1 | 0 对 0 | 112 |
| 抽样 12 | Quagsire (Shadow) #13、Altaria (Mega) #273、Vigoroth #30 | **赢** | 567 对 432 | 1 对 0 | 0 对 0 | 105 |
| 抽样 13 | Mawile (Mega) #201、Mantine #28、Jellicent #31 | 输 | 477 对 522 | 0 对 1 | 0 对 0 | 136 |
| 抽样 14 | Greninja (Mega) #226、Ninetales #15、Araquanid #18 | **赢** | 600 对 399 | 1 对 0 | 0 对 0 | 118 |
| 抽样 15 | Charizard (Mega X) #283、Azumarill #22、Araquanid #18 | 输 | 325 对 674 | 0 对 2 | 0 对 0 | 126 |
| 抽样 16 | Charizard (Mega X) #283、Stunfisk #29、Jellicent #31 | **赢** | 738 对 261 | 3 对 0 | 2 对 0 | 73 |
| 抽样 17 | Raichu (Mega X) #183、Umbreon #21、Quagsire (Shadow) #13 | 输 | 291 对 708 | 0 对 2 | 0 对 1 | 67 |
| 抽样 18 | Houndoom (Mega) #216、Altaria #3、Quagsire #12 | **赢** | 549 对 450 | 1 对 0 | 0 对 0 | 107 |
| 抽样 19 | Audino (Mega) #177、Jellicent #31、Marowak #25 | 输 | 472 对 527 | 0 对 1 | 0 对 0 | 113 |
| 抽样 20 | Greninja (Mega) #226、Araquanid #18、Cramorant #10 | 输 | 369 对 630 | 0 对 2 | 0 对 0 | 103 |
| 抽样 21 | Araquanid #18、Charizard (Mega X) #283、Ninetales #15 | 输 | 299 对 700 | 0 对 2 | 0 对 0 | 116 |
| 抽样 22 | Hydreigon (Shadow) #16、Charizard (Mega X) #283、Ninetales (Shadow) #4 | **赢** | 596 对 403 | 1 对 0 | 0 对 0 | 84 |
| 抽样 23 | Houndoom (Mega) #216、Jellicent #31、Cramorant #10 | 输 | 421 对 578 | 0 对 2 | 0 对 0 | 112 |
| 抽样 24 | Altaria (Mega) #273、Hydreigon (Shadow) #16、Ninetales #15 | 输 | 480 对 519 | 0 对 1 | 0 对 0 | 99 |
| 抽样 25 | Altaria (Mega) #273、Rillaboom #26、Corviknight (Shadow) #14 | 输 | 394 对 605 | 0 对 1 | 0 对 0 | 98 |
| 抽样 26 | Dunsparce #24、Corviknight (Shadow) #14、Malamar (Mega) #32 | **赢** | 677 对 322 | 2 对 0 | 0 对 0 | 87 |
| 抽样 27 | Dunsparce #24、Altaria (Mega) #273、Mantine #28 | 输 | 432 对 567 | 0 对 1 | 0 对 0 | 125 |
| 抽样 28 | Ninetales (Shadow) #4、Altaria (Mega) #273、Quagsire (Shadow) #13 | **赢** | 577 对 422 | 2 对 0 | 0 对 0 | 91 |
| 抽样 29 | Stunfisk #29、Mawile (Mega) #201、Corviknight (Shadow) #14 | **赢** | 613 对 386 | 1 对 0 | 0 对 0 | 97 |
| 抽样 30 | Greninja (Mega) #226、Fearow #23、Sableye (Shadow) #17 | 输 | 375 对 624 | 0 对 2 | 0 对 0 | 89 |
| 抽样 31 | Altaria (Mega) #273、Quagsire (Shadow) #13、Clodsire #20 | 输 | 372 对 627 | 0 对 2 | 0 对 0 | 101 |
| 抽样 32 | Azumarill #22、Altaria #3、Audino (Mega) #177 | **赢** | 556 对 443 | 1 对 0 | 0 对 0 | 151 |
| 抽样 33 | Stunfisk #29、Houndoom (Mega) #216、Altaria (Shadow) #8 | 输 | 402 对 597 | 0 对 2 | 0 对 0 | 88 |
| 抽样 34 | Raichu (Mega X) #183、Rillaboom #26、Mantine #28 | **赢** | 729 对 270 | 2 对 0 | 0 对 0 | 70 |
| 抽样 35 | Fearow #23、Dragonite (Mega) #206、Clodsire #20 | **赢** | 522 对 477 | 1 对 0 | 0 对 0 | 105 |
| 抽样 36 | Hydreigon (Shadow) #16、Quagsire #12、Altaria (Mega) #273 | **赢** | 695 对 304 | 2 对 0 | 0 对 0 | 82 |
| 抽样 37 | Dunsparce #24、Sableye (Mega) #1、Quagsire (Shadow) #13 | 输 | 462 对 537 | 0 对 1 | 0 对 0 | 118 |
| 抽样 38 | Rillaboom #26、Corsola (Galarian) #11、Altaria (Mega) #273 | 输 | 490 对 509 | 0 对 1 | 0 对 0 | 120 |
| 抽样 39 | Dunsparce #24、Dragonite (Mega) #206、Jellicent #31 | **赢** | 665 对 334 | 2 对 0 | 0 对 0 | 98 |
| 抽样 40 | Greninja (Mega) #226、Quagsire (Shadow) #13、Ninetales (Shadow) #4 | **赢** | 677 对 322 | 2 对 0 | 0 对 0 | 96 |
| 抽样 41 | Raichu (Mega X) #183、Cramorant #10、Fearow #23 | 输 | 490 对 509 | 0 对 1 | 0 对 0 | 95 |
| 抽样 42 | Altaria (Shadow) #8、Mantine #28、Dragonite (Mega) #206 | **赢** | 571 对 428 | 2 对 0 | 0 对 0 | 113 |
| 抽样 43 | Dragonite (Mega) #206、Araquanid #18、Altaria (Shadow) #8 | **赢** | 675 对 324 | 2 对 0 | 0 对 0 | 108 |
| 抽样 44 | Altaria #3、Audino (Mega) #177、Hydreigon (Shadow) #16 | **赢** | 703 对 296 | 2 对 0 | 0 对 0 | 89 |
| 抽样 45 | Clodsire #20、Ninetales (Shadow) #4、Raichu (Mega X) #183 | 输 | 323 对 676 | 0 对 2 | 0 对 0 | 106 |
| 抽样 46 | Jellicent #31、Mimikyu #5、Dragonite (Mega) #206 | **赢** | 665 对 334 | 2 对 0 | 1 对 0 | 86 |
| 抽样 47 | Quagsire (Shadow) #13、Raichu (Mega X) #183、Tinkaton #6 | 输 | 356 对 643 | 0 对 1 | 0 对 0 | 116 |
| 抽样 48 | Tinkaton #6、Raichu (Mega X) #183、Quagsire #12 | 输 | 443 对 556 | 0 对 1 | 0 对 0 | 109 |
| 抽样 49 | Altaria #3、Charizard (Mega X) #283、Marowak #25 | **赢** | 749 对 250 | 2 对 0 | 0 对 0 | 90 |
| 抽样 50 | Sableye (Mega) #1、Mimikyu #5、Florges #7 | 输 | 264 对 735 | 0 对 2 | 0 对 0 | 102 |

## 对手队伍

### 手写的（1 队）

**Team B**（2 盾）

- 首发 Swampert：Swampert，CP 1498，19 级，IV 0/14/14，MUD_SHOT / HYDRO_CANNON, EARTHQUAKE
- 后备 Altaria：Altaria，CP 1497，29 级，IV 0/14/15，DRAGON_BREATH / SKY_ATTACK, MOONBLAST
- 后备 Trevenant：Trevenant，CP 1497，22 级，IV 0/15/15，SHADOW_CLAW / SEED_BOMB, SHADOW_BALL
- 策略：TeamPolicy，默认参数

### 随机抽的（50 队）

从 PvPoke 的 mega 排名（Mega 版，Mega 和非 Mega 一起排，超级联盟）随机抽 50 队，随机种子 1：每队 1 只 Mega（Mega 前 10 只里抽）和 2 只非 Mega（非 Mega 前 30 只里抽）；同一种不重复，出场顺序随机，均匀抽、不按名次加权；IV 排名第 1，等级按赛季规则（和配置文件不写 IV 时一样）。
每队 2 盾；策略：TeamPolicy，默认参数。

#后面是 PvPoke 排名文件里的名次（这套排名里的所有宝可梦一起排）。

| 队伍 | 首发 | 后备 | 后备 |
|---|---|---|---|
| 抽样 1 | Corsola (Galarian) #11 | Rillaboom #26 | Malamar (Mega) #32 |
| 抽样 2 | Audino (Mega) #177 | Azumarill #22 | Quagsire (Shadow) #13 |
| 抽样 3 | Raichu (Mega X) #183 | Araquanid #18 | Altaria (Shadow) #8 |
| 抽样 4 | Cramorant #10 | Altaria (Mega) #273 | Corviknight (Shadow) #14 |
| 抽样 5 | Fearow #23 | Florges #7 | Malamar (Mega) #32 |
| 抽样 6 | Ninetales #15 | Greninja (Mega) #226 | Mantine #28 |
| 抽样 7 | Tinkaton #6 | Audino (Mega) #177 | Altaria (Shadow) #8 |
| 抽样 8 | Altaria (Shadow) #8 | Stunfisk #29 | Greninja (Mega) #226 |
| 抽样 9 | Quagsire #12 | Corviknight #9 | Altaria (Mega) #273 |
| 抽样 10 | Charizard (Mega X) #283 | Marowak #25 | Melmetal #2 |
| 抽样 11 | Corviknight (Shadow) #14 | Florges #7 | Audino (Mega) #177 |
| 抽样 12 | Quagsire (Shadow) #13 | Altaria (Mega) #273 | Vigoroth #30 |
| 抽样 13 | Mawile (Mega) #201 | Mantine #28 | Jellicent #31 |
| 抽样 14 | Greninja (Mega) #226 | Ninetales #15 | Araquanid #18 |
| 抽样 15 | Charizard (Mega X) #283 | Azumarill #22 | Araquanid #18 |
| 抽样 16 | Charizard (Mega X) #283 | Stunfisk #29 | Jellicent #31 |
| 抽样 17 | Raichu (Mega X) #183 | Umbreon #21 | Quagsire (Shadow) #13 |
| 抽样 18 | Houndoom (Mega) #216 | Altaria #3 | Quagsire #12 |
| 抽样 19 | Audino (Mega) #177 | Jellicent #31 | Marowak #25 |
| 抽样 20 | Greninja (Mega) #226 | Araquanid #18 | Cramorant #10 |
| 抽样 21 | Araquanid #18 | Charizard (Mega X) #283 | Ninetales #15 |
| 抽样 22 | Hydreigon (Shadow) #16 | Charizard (Mega X) #283 | Ninetales (Shadow) #4 |
| 抽样 23 | Houndoom (Mega) #216 | Jellicent #31 | Cramorant #10 |
| 抽样 24 | Altaria (Mega) #273 | Hydreigon (Shadow) #16 | Ninetales #15 |
| 抽样 25 | Altaria (Mega) #273 | Rillaboom #26 | Corviknight (Shadow) #14 |
| 抽样 26 | Dunsparce #24 | Corviknight (Shadow) #14 | Malamar (Mega) #32 |
| 抽样 27 | Dunsparce #24 | Altaria (Mega) #273 | Mantine #28 |
| 抽样 28 | Ninetales (Shadow) #4 | Altaria (Mega) #273 | Quagsire (Shadow) #13 |
| 抽样 29 | Stunfisk #29 | Mawile (Mega) #201 | Corviknight (Shadow) #14 |
| 抽样 30 | Greninja (Mega) #226 | Fearow #23 | Sableye (Shadow) #17 |
| 抽样 31 | Altaria (Mega) #273 | Quagsire (Shadow) #13 | Clodsire #20 |
| 抽样 32 | Azumarill #22 | Altaria #3 | Audino (Mega) #177 |
| 抽样 33 | Stunfisk #29 | Houndoom (Mega) #216 | Altaria (Shadow) #8 |
| 抽样 34 | Raichu (Mega X) #183 | Rillaboom #26 | Mantine #28 |
| 抽样 35 | Fearow #23 | Dragonite (Mega) #206 | Clodsire #20 |
| 抽样 36 | Hydreigon (Shadow) #16 | Quagsire #12 | Altaria (Mega) #273 |
| 抽样 37 | Dunsparce #24 | Sableye (Mega) #1 | Quagsire (Shadow) #13 |
| 抽样 38 | Rillaboom #26 | Corsola (Galarian) #11 | Altaria (Mega) #273 |
| 抽样 39 | Dunsparce #24 | Dragonite (Mega) #206 | Jellicent #31 |
| 抽样 40 | Greninja (Mega) #226 | Quagsire (Shadow) #13 | Ninetales (Shadow) #4 |
| 抽样 41 | Raichu (Mega X) #183 | Cramorant #10 | Fearow #23 |
| 抽样 42 | Altaria (Shadow) #8 | Mantine #28 | Dragonite (Mega) #206 |
| 抽样 43 | Dragonite (Mega) #206 | Araquanid #18 | Altaria (Shadow) #8 |
| 抽样 44 | Altaria #3 | Audino (Mega) #177 | Hydreigon (Shadow) #16 |
| 抽样 45 | Clodsire #20 | Ninetales (Shadow) #4 | Raichu (Mega X) #183 |
| 抽样 46 | Jellicent #31 | Mimikyu #5 | Dragonite (Mega) #206 |
| 抽样 47 | Quagsire (Shadow) #13 | Raichu (Mega X) #183 | Tinkaton #6 |
| 抽样 48 | Tinkaton #6 | Raichu (Mega X) #183 | Quagsire #12 |
| 抽样 49 | Altaria #3 | Charizard (Mega X) #283 | Marowak #25 |
| 抽样 50 | Sableye (Mega) #1 | Mimikyu #5 | Florges #7 |

#### 候选：非 Mega 前 30

推荐配招来自 PvPoke；CP、等级、IV 按上面的 IV 规则和赛季规则。

| 名次 | 宝可梦 | PvPoke 分 | CP | 等级 | IV | 配招 |
|---|---|---|---|---|---|---|
| 2 | Melmetal | 93.8 | 1499 | 15.5 | 1/15/14 | THUNDER_SHOCK / DOUBLE_IRON_BASH, DYNAMIC_PUNCH |
| 3 | Altaria | 92.8 | 1497 | 29 | 0/14/15 | DRAGON_BREATH / MOONBLAST, FLAMETHROWER |
| 4 | Ninetales (Shadow) | 92.7 | 1495 | 25 | 0/15/15 | EMBER / WEATHER_BALL_FIRE, ENERGY_BALL |
| 5 | Mimikyu | 92 | 1500 | 25.5 | 1/14/15 | SHADOW_CLAW / SHADOW_SNEAK, PLAY_ROUGH |
| 6 | Tinkaton | 92 | 1497 | 25.5 | 1/14/14 | FAIRY_WIND / GIGATON_HAMMER, BULLDOZE |
| 7 | Florges | 91.7 | 1500 | 17.5 | 0/14/13 | FAIRY_WIND / CHILLING_WATER, MOONBLAST |
| 8 | Altaria (Shadow) | 91.5 | 1497 | 29 | 0/14/15 | DRAGON_BREATH / MOONBLAST, FLAMETHROWER |
| 9 | Corviknight | 91.4 | 1500 | 23.5 | 0/13/14 | SAND_ATTACK / AIR_CUTTER, IRON_HEAD |
| 10 | Cramorant | 91.4 | 1500 | 27 | 0/14/11 | PECK / SURF, FLY |
| 11 | Corsola (Galarian) | 91.1 | 1498 | 50 | 0/15/15 | ASTONISH / NIGHT_SHADE, POWER_GEM |
| 12 | Quagsire | 91.1 | 1499 | 29 | 0/15/14 | MUD_SHOT / AQUA_TAIL, STONE_EDGE |
| 13 | Quagsire (Shadow) | 91.1 | 1499 | 29 | 0/15/14 | MUD_SHOT / AQUA_TAIL, STONE_EDGE |
| 14 | Corviknight (Shadow) | 91 | 1500 | 23.5 | 0/13/14 | SAND_ATTACK / AIR_CUTTER, IRON_HEAD |
| 15 | Ninetales | 90.8 | 1495 | 25 | 0/15/15 | EMBER / WEATHER_BALL_FIRE, ENERGY_BALL |
| 16 | Hydreigon (Shadow) | 90.7 | 1499 | 15.5 | 0/15/10 | DRAGON_BREATH / BRUTAL_SWING, FLY |
| 17 | Sableye (Shadow) | 90.6 | 1499 | 49.5 | 0/15/15 | SHADOW_CLAW / FOUL_PLAY, DRAIN_PUNCH |
| 18 | Araquanid | 90.5 | 1500 | 35 | 0/10/15 | INFESTATION / WATER_PULSE, MIRROR_COAT |
| 19 | Thievul | 90.5 | 1499 | 27 | 0/15/11 | SUCKER_PUNCH / NIGHT_SLASH, ICY_WIND |
| 20 | Clodsire | 90.4 | 1499 | 30.5 | 0/14/13 | POISON_STING / EARTHQUAKE, STONE_EDGE |
| 21 | Umbreon | 90.3 | 1500 | 27.5 | 0/15/15 | SNARL / DARK_PULSE, LAST_RESORT |
| 22 | Azumarill | 90.2 | 1499 | 45.5 | 0/15/15 | BUBBLE / ICE_BEAM, PLAY_ROUGH |
| 23 | Fearow | 90.2 | 1498 | 28.5 | 0/15/14 | PECK / DRILL_PECK, DRILL_RUN |
| 24 | Dunsparce | 90.1 | 1500 | 40 | 0/14/12 | ROLLOUT / DRILL_RUN, ROCK_SLIDE |
| 25 | Marowak | 90.1 | 1500 | 33.5 | 0/14/14 | MUD_SLAP / BONE_CLUB, ROCK_SLIDE |
| 26 | Rillaboom | 90.1 | 1500 | 17 | 0/12/13 | SCRATCH / DRUM_BEATING, EARTH_POWER |
| 27 | Carbink | 90 | 1498 | 49.5 | 5/15/15 | ROCK_THROW / ROCK_SLIDE, MOONBLAST |
| 28 | Mantine | 90 | 1500 | 27.5 | 0/15/14 | WING_ATTACK / TWISTER, WATER_PULSE |
| 29 | Stunfisk | 90 | 1498 | 27 | 0/12/15 | THUNDER_SHOCK / MUD_BOMB, DISCHARGE |
| 30 | Vigoroth | 90 | 1499 | 29 | 1/15/15 | SCRATCH / BODY_SLAM, BULLDOZE |
| 31 | Jellicent | 89.9 | 1498 | 24.5 | 1/14/14 | HEX / SURF, SHADOW_BALL |

#### 候选：Mega 前 10

推荐配招来自 PvPoke；CP、等级、IV 按上面的 IV 规则和赛季规则。

| 名次 | 宝可梦 | PvPoke 分 | CP | 等级 | IV | 配招 |
|---|---|---|---|---|---|---|
| 1 | Sableye (Mega) | 94 | 1499 | 30 | 0/15/12 | SHADOW_CLAW / FOUL_PLAY, DAZZLING_GLEAM, NIGHT_SHADE_PLUS |
| 32 | Malamar (Mega) | 89.9 | 1497 | 18 | 0/15/12 | PSYWAVE / FOUL_PLAY, SUPER_POWER, PSYBEAM_PLUS |
| 177 | Audino (Mega) | 83 | 1499 | 23 | 0/14/14 | CHARGE_BEAM / BODY_SLAM, DISARMING_VOICE |
| 183 | Raichu (Mega X) | 82.9 | 1500 | 16 | 0/15/10 | VOLT_SWITCH / BRICK_BREAK, TRAILBLAZE, VOLT_TACKLE_PLUS |
| 201 | Mawile (Mega) | 82.4 | 1498 | 24 | 0/14/13 | FAIRY_WIND / VICE_GRIP, IRON_HEAD |
| 206 | Dragonite (Mega) | 82.3 | 1500 | 11.5 | 0/13/14 | DRAGON_BREATH / SUPER_POWER, THUNDER_PUNCH, OUTRAGE_PLUS |
| 216 | Houndoom (Mega) | 82.1 | 1498 | 14.5 | 0/12/14 | INCINERATE / FLAMETHROWER, TRAILBLAZE, DARK_PULSE_PLUS |
| 226 | Greninja (Mega) | 81.7 | 1498 | 14.5 | 1/15/15 | WATER_SHURIKEN / HYDRO_CANNON, BRUTAL_SWING, SURF_PLUS |
| 273 | Altaria (Mega) | 80.4 | 1500 | 18 | 0/8/15 | DRAGON_BREATH / MOONBLAST, FLAMETHROWER |
| 283 | Charizard (Mega X) | 80.1 | 1499 | 14.5 | 0/11/15 | DRAGON_BREATH / BLAST_BURN, AIR_CUTTER |
