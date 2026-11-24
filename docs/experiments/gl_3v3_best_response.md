3v3 例子：Azumarill / Medicham / Registeel 对 Swampert / Altaria / Trevenant，超级联盟，双方都用默认的 3v3 策略。

- 配置文件：`experiments/gl_3v3_example.toml`
- 联盟：超级联盟；赛季规则：PvPoke 兼容
- 机制规则：与 PvPoke 一致（默认）
- 策略：Team B（第 1 方）固定用 3v3 策略 TeamPolicy；Team A（第 0 方）的打法是对它逐步试探搜索出来的（docs/mechanics.md 13.11）
- 评分：本项目的口径（docs/mechanics.md 13.2 D1），500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整。双方加起来 1000

## 队伍

**Team A**（第 0 方，2 盾）

- 首发 Azumarill：Azumarill，CP 1499，45.5 级，IV 0/15/15，BUBBLE / ICE_BEAM, PLAY_ROUGH
- 后备 Medicham：Medicham，CP 1499，50 级，IV 5/15/15，COUNTER / ICE_PUNCH, PSYCHIC
- 后备 Registeel：Registeel，CP 1499，23.5 级，IV 2/13/14，LOCK_ON / FOCUS_BLAST, ZAP_CANNON
- 策略：逐步试探搜索出来的打法；原策略（起点）是 TeamPolicy，默认参数

**Team B**（第 1 方，2 盾）

- 首发 Swampert：Swampert，CP 1498，19 级，IV 0/14/14，MUD_SHOT / HYDRO_CANNON, EARTHQUAKE
- 后备 Altaria：Altaria，CP 1497，29 级，IV 0/14/15，DRAGON_BREATH / SKY_ATTACK, MOONBLAST
- 后备 Trevenant：Trevenant，CP 1497，22 级，IV 0/15/15，SHADOW_CLAW / SEED_BOMB, SHADOW_BALL
- 策略：TeamPolicy，默认参数

队伍检查通过：每队 3 只；没有同一种宝可梦（按图鉴编号）；Mega 不超过 1 只。

## 搜索结果

方法：先让双方都照原策略打一场；然后沿着当前最好的一场，按顺序把 Team A 每个决定点的其余选项都试一遍（之前的决定照当前最好的一场，之后双方照各自的策略打完），严格更好就改。比较时先看胜负，再看评分。结果不比原策略差，但不保证全局最优；搜索完全知道 Team B 的策略会怎么应对，所以是针对这个策略的打法。

- 原策略：Team B 赢。评分 221 对 778；剩余 0 只对 3 只；剩余盾 0 对 0；100 回合，对战时间 145 秒（大招每次按 10 秒算）。
- 搜索后：Team A 赢。评分 593 对 406；剩余 2 只对 0 只；剩余盾 0 对 0；116 回合，对战时间 192 秒（大招每次按 10 秒算）。
- Team A 一共做了 77 个决定，其中 32 个有不止一个选项、都试过；改了 5 个。一共打了 50 场，用时 0.4 秒。

## 改了哪些决定

按搜索的顺序。"改之前 → 改之后"是当时最好的一场和改了以后的结果（从 Team A 看：胜负和评分）；"各选项"是这个决定点每个选项打出来的结果（之前的决定照当时最好的一场，之后照各自的策略）。后面的改动是在前面改过的基础上试的。

| 回合 | 决定 | 原策略 | 改成 | 改之前 → 改之后 | 各选项打出来的结果 |
|---|---|---|---|---|---|
| 1 | 出招 | fast BUBBLE | switch to Medicham | 输 221 → 输 465 | fast BUBBLE: 输 221; switch to Medicham: 输 465; switch to Registeel: 输 237 |
| 11 | 开盾 | shield | no shield | 输 465 → 赢 521 | shield: 输 465; no shield: 赢 521 |
| 21 | 出招 | fast COUNTER | charged ICE_PUNCH | 赢 521 → 赢 577 | fast COUNTER: 赢 521; charged ICE_PUNCH: 赢 577 |
| 62 | 0 回合换人 | stay | switch to Registeel | 赢 577 → 赢 588 | stay: 赢 577; switch to Registeel: 赢 588 |
| 99 | 0 回合换人 | stay | switch to Azumarill | 赢 588 → 赢 593 | stay: 赢 588; switch to Azumarill: 赢 593 |

## 搜索后的这一场

以下各节都是搜索后的这一场。时间线里，改过的决定的原因写成 best response: …（policy would …）。

## 每只的情况

挨大招：被大招打中时开盾挡下的次数 / 队伍还有盾但没开的次数。被盾挡下的大招算 1 点伤害。

| 队伍 | 宝可梦 | 剩余 HP | 剩余能量 | 造成伤害 | 受到伤害 | 快招 | 大招 | 挨大招：开盾 / 没开 | 倒下 |
|---|---|---|---|---|---|---|---|---|---|
| Team A | Azumarill | 104 / 196 | 0 | 209 | 92 | 10 | ICE_BEAM ×2 | 0 / 0 | — |
| Team A | Medicham | 0 / 142 | 28 | 128 | 164 | 18 | ICE_PUNCH ×2 | 2 / 1 | 第 43 回合 |
| Team A | Registeel | 4 / 132 | 0 | 125 | 128 | 31 | FOCUS_BLAST ×1, ZAP_CANNON ×1 | 0 / 0 | — |
| Team B | Swampert | 0 / 139 | 29 | 173 | 140 | 21 | HYDRO_CANNON ×4 | 2 / 0 | 第 50 回合 |
| Team B | Altaria | 0 / 141 | 20 | 94 | 180 | 30 | SKY_ATTACK ×2 | 0 / 0 | 第 116 回合 |
| Team B | Trevenant | 0 / 133 | 6 | 117 | 142 | 12 | SHADOW_BALL ×1, SEED_BOMB ×1 | 0 / 0 | 第 79 回合 |

## 开局对位评分

TeamPolicy 选人、换人看的就是这种评分：行上那只对列上那只打 1v1，双方满 HP、0 能量，盾数从 0 到两队开局的盾数，按 [4, 4, 1] 加权平均（docs/mechanics.md 13.7）。500 是平手。
从 Team A 一方看；Team B 一方约等于 1000 减它。

| Team A \ Team B | Swampert | Altaria | Trevenant |
|---|---|---|---|
| Azumarill | 452 | 680 | 421 |
| Medicham | 493 | 379 | 198 |
| Registeel | 269 | 689 | 334 |

## 换人

| 回合 | 队伍 | 换人 | 类型 | 原因 |
|---|---|---|---|---|
| 1 | Team A | Azumarill → Medicham | 主动换人 | best response: switch to Medicham (policy would fast BUBBLE: stay: matchup vs Swampert 452 >= 450; energy 0 < 55 needed for ICE_BEAM) |
| 44 | Team A | Medicham → Azumarill | 倒下后换人 | best matchup vs Swampert: Azumarill 977, Registeel 791 |
| 51 | Team B | Swampert → Trevenant | 倒下后换人 | best matchup vs Azumarill: Trevenant 489, Altaria 196 |
| 62 | Team A | Azumarill → Registeel | 0 回合换人 | best response: switch to Registeel (policy would stay: stay: matchup vs Trevenant 510 >= 450) |
| 80 | Team B | Trevenant → Altaria | 倒下后换人 | best matchup vs Registeel: Altaria 716 |
| 99 | Team A | Registeel → Azumarill | 0 回合换人 | best response: switch to Azumarill (policy would stay: stay: HP 3% <= 25%) |

## 大招和开盾

| 回合 | 出招 | 大招 | 挨打 | 结果 | 开不开盾的原因 |
|---|---|---|---|---|---|
| 11 | Swampert | HYDRO_CANNON | Medicham | 54 伤害，剩 HP 73 | best response: no shield (policy would shield: always shield (2 left); with a shield, matchup vs Swampert 598) |
| 21 | Swampert | HYDRO_CANNON | Medicham | 开盾挡下 | always shield (2 left); with a shield, matchup vs Swampert 556 |
| 21 | Medicham | ICE_PUNCH | Swampert | 开盾挡下 | always shield (2 left); with a shield, matchup vs Medicham 542 |
| 33 | Swampert | HYDRO_CANNON | Medicham | 开盾挡下 | always shield (1 left); with a shield, matchup vs Swampert 540 |
| 37 | Medicham | ICE_PUNCH | Swampert | 开盾挡下 | always shield (1 left); with a shield, matchup vs Medicham 514 |
| 43 | Swampert | HYDRO_CANNON | Medicham | 54 伤害，剩 HP 0 | 没有盾 |
| 61 | Azumarill | ICE_BEAM | Trevenant | 81 伤害，剩 HP 40 | 没有盾 |
| 67 | Trevenant | SHADOW_BALL | Registeel | 46 伤害，剩 HP 78 | 没有盾 |
| 79 | Trevenant | SEED_BOMB | Registeel | 18 伤害，剩 HP 40 | 没有盾 |
| 79 | Registeel | FOCUS_BLAST | Trevenant | 34 伤害，剩 HP 0 | 没有盾 |
| 94 | Altaria | SKY_ATTACK | Registeel | 20 伤害，剩 HP 7 | 没有盾 |
| 98 | Registeel | ZAP_CANNON | Altaria | 60 伤害，剩 HP 65 | 没有盾 |
| 111 | Altaria | SKY_ATTACK | Azumarill | 44 伤害，剩 HP 107 | 没有盾 |
| 116 | Azumarill | ICE_BEAM | Altaria | 89 伤害，剩 HP 0 | 没有盾 |

## 时间线

每回合的决定（decides …，括号里是原因）和结算。T 后面是回合数。

```text
T   1  Azumarill       decides switch -> Medicham  (best response: switch to Medicham (policy would fast BUBBLE: stay: matchup vs Swampert 452 >= 450; energy 0 < 55 needed for ICE_BEAM))
T   1  Swampert        decides fast MUD_SHOT  (stay: matchup vs Azumarill 547 >= 450; energy 0 < 40 needed for HYDRO_CANNON)
T   1  Azumarill       switches to Medicham  (switch timer 45s)
T   2  Medicham        decides fast COUNTER  (energy 0 < 40 needed for ICE_PUNCH)
T   2  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 139, energy 9
T   3  Swampert        decides fast MUD_SHOT  (stay: matchup vs Medicham 522 >= 450; energy 9 < 40 needed for HYDRO_CANNON)
T   3  Medicham        fast COUNTER -> 7 dmg, Swampert HP 132, energy 6
T   4  Medicham        decides fast COUNTER  (energy 6 < 40 needed for ICE_PUNCH)
T   4  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 136, energy 18
T   5  Swampert        decides fast MUD_SHOT  (energy 18 < 40 needed for HYDRO_CANNON)
T   5  Medicham        fast COUNTER -> 7 dmg, Swampert HP 125, energy 12
T   6  Medicham        decides fast COUNTER  (energy 12 < 40 needed for ICE_PUNCH)
T   6  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 133, energy 27
T   7  Swampert        decides fast MUD_SHOT  (energy 27 < 40 needed for HYDRO_CANNON)
T   7  Medicham        fast COUNTER -> 7 dmg, Swampert HP 118, energy 18
T   8  Medicham        decides fast COUNTER  (energy 18 < 40 needed for ICE_PUNCH)
T   8  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 130, energy 36
T   9  Swampert        decides fast MUD_SHOT  (energy 36 < 40 needed for HYDRO_CANNON)
T   9  Medicham        fast COUNTER -> 7 dmg, Swampert HP 111, energy 24
T  10  Medicham        decides fast COUNTER  (energy 24 < 40 needed for ICE_PUNCH)
T  10  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 127, energy 45
T  11  Swampert        decides charged HYDRO_CANNON  (HYDRO_CANNON ready (54 dmg, target by best_dpe))
T  11  Swampert        CHARGED HYDRO_CANNON -> 54 dmg, Medicham HP 73, energy 5  [shield: best response: no shield (policy would shield: always shield (2 left); with a shield, matchup vs Swampert 598)]
T  11  Medicham        fast COUNTER -> 7 dmg, Swampert HP 104, energy 30
T  12  Swampert        decides not to switch  (stay: matchup vs Medicham 532 >= 450)
T  13  Medicham        decides fast COUNTER  (energy 30 < 40 needed for ICE_PUNCH)
T  13  Swampert        decides fast MUD_SHOT  (energy 5 < 40 needed for HYDRO_CANNON)
T  14  Medicham        fast COUNTER -> 7 dmg, Swampert HP 97, energy 36
T  14  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 70, energy 14
T  15  Medicham        decides fast COUNTER  (energy 36 < 40 needed for ICE_PUNCH)
T  15  Swampert        decides fast MUD_SHOT  (energy 14 < 40 needed for HYDRO_CANNON)
T  16  Medicham        fast COUNTER -> 7 dmg, Swampert HP 90, energy 42
T  16  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 67, energy 23
T  17  Medicham        decides fast COUNTER  (saving for PSYCHIC (42/55 energy, target by best_dpe))
T  17  Swampert        decides fast MUD_SHOT  (energy 23 < 40 needed for HYDRO_CANNON)
T  18  Medicham        fast COUNTER -> 7 dmg, Swampert HP 83, energy 48
T  18  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 64, energy 32
T  19  Medicham        decides fast COUNTER  (saving for PSYCHIC (48/55 energy, target by best_dpe))
T  19  Swampert        decides fast MUD_SHOT  (energy 32 < 40 needed for HYDRO_CANNON)
T  20  Medicham        fast COUNTER -> 7 dmg, Swampert HP 76, energy 54
T  20  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 61, energy 41
T  21  Medicham        decides charged ICE_PUNCH  (best response: charged ICE_PUNCH (policy would fast COUNTER: saving for PSYCHIC (54/55 energy, target by best_dpe)))
T  21  Swampert        decides charged HYDRO_CANNON  (HYDRO_CANNON ready (54 dmg, target by best_dpe))
T  21  Swampert        CHARGED HYDRO_CANNON -> 1 dmg (shielded), Medicham HP 60, energy 1  [shield: always shield (2 left); with a shield, matchup vs Swampert 556]
T  21  Medicham        CHARGED ICE_PUNCH -> 1 dmg (shielded), Swampert HP 75, energy 14  [shield: always shield (2 left); with a shield, matchup vs Medicham 542]
T  22  Swampert        decides not to switch  (stay: matchup vs Medicham 542 >= 450)
T  23  Medicham        decides fast COUNTER  (energy 14 < 40 needed for ICE_PUNCH)
T  23  Swampert        decides fast MUD_SHOT  (energy 1 < 40 needed for HYDRO_CANNON)
T  24  Medicham        fast COUNTER -> 7 dmg, Swampert HP 68, energy 20
T  24  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 57, energy 10
T  25  Medicham        decides fast COUNTER  (energy 20 < 40 needed for ICE_PUNCH)
T  25  Swampert        decides fast MUD_SHOT  (energy 10 < 40 needed for HYDRO_CANNON)
T  26  Medicham        fast COUNTER -> 7 dmg, Swampert HP 61, energy 26
T  26  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 54, energy 19
T  27  Medicham        decides fast COUNTER  (energy 26 < 40 needed for ICE_PUNCH)
T  27  Swampert        decides fast MUD_SHOT  (energy 19 < 40 needed for HYDRO_CANNON)
T  28  Medicham        fast COUNTER -> 7 dmg, Swampert HP 54, energy 32
T  28  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 51, energy 28
T  29  Medicham        decides fast COUNTER  (energy 32 < 40 needed for ICE_PUNCH)
T  29  Swampert        decides fast MUD_SHOT  (energy 28 < 40 needed for HYDRO_CANNON)
T  30  Medicham        fast COUNTER -> 7 dmg, Swampert HP 47, energy 38
T  30  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 48, energy 37
T  31  Medicham        decides fast COUNTER  (energy 38 < 40 needed for ICE_PUNCH)
T  31  Swampert        decides fast MUD_SHOT  (energy 37 < 40 needed for HYDRO_CANNON)
T  32  Medicham        fast COUNTER -> 7 dmg, Swampert HP 40, energy 44
T  32  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 45, energy 46
T  33  Medicham        decides fast COUNTER  (stay: matchup vs Swampert 456 >= 450; saving for PSYCHIC (44/55 energy, target by best_dpe))
T  33  Swampert        decides charged HYDRO_CANNON  (HYDRO_CANNON ready (54 dmg, target by best_dpe))
T  33  Swampert        CHARGED HYDRO_CANNON -> 1 dmg (shielded), Medicham HP 44, energy 6  [shield: always shield (1 left); with a shield, matchup vs Swampert 540]
T  34  Medicham        decides not to switch  (stay: matchup vs Swampert 540 >= 450)
T  34  Swampert        decides not to switch  (stay: matchup vs Medicham 460 >= 450)
T  34  Medicham        fast COUNTER -> 7 dmg, Swampert HP 33, energy 50
T  35  Medicham        decides fast COUNTER  (saving for PSYCHIC (50/55 energy, target by best_dpe))
T  35  Swampert        decides fast MUD_SHOT  (energy 6 < 40 needed for HYDRO_CANNON)
T  36  Medicham        fast COUNTER -> 7 dmg, Swampert HP 26, energy 56
T  36  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 41, energy 15
T  37  Medicham        decides charged ICE_PUNCH  (bait: opponent has 1 shield(s), throw ICE_PUNCH (40) instead of PSYCHIC)
T  37  Swampert        decides fast MUD_SHOT  (energy 15 < 40 needed for HYDRO_CANNON)
T  37  Medicham        CHARGED ICE_PUNCH -> 1 dmg (shielded), Swampert HP 25, energy 16  [shield: always shield (1 left); with a shield, matchup vs Medicham 514]
T  38  Medicham        decides not to switch  (stay: matchup vs Swampert 485 >= 450)
T  38  Swampert        decides not to switch  (stay: HP 18% <= 25%)
T  38  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 38, energy 24
T  39  Medicham        decides fast COUNTER  (energy 16 < 40 needed for ICE_PUNCH)
T  39  Swampert        decides fast MUD_SHOT  (energy 24 < 40 needed for HYDRO_CANNON)
T  40  Medicham        fast COUNTER -> 7 dmg, Swampert HP 18, energy 22
T  40  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 35, energy 33
T  41  Medicham        decides fast COUNTER  (energy 22 < 40 needed for ICE_PUNCH)
T  41  Swampert        decides fast MUD_SHOT  (energy 33 < 40 needed for HYDRO_CANNON)
T  42  Medicham        fast COUNTER -> 7 dmg, Swampert HP 11, energy 28
T  42  Swampert        fast MUD_SHOT -> 3 dmg, Medicham HP 32, energy 42
T  43  Medicham        decides fast COUNTER  (energy 28 < 40 needed for ICE_PUNCH)
T  43  Swampert        decides charged HYDRO_CANNON  (HYDRO_CANNON deals 54 >= opponent HP 32, no shields)
T  43  Swampert        CHARGED HYDRO_CANNON -> 54 dmg, Medicham HP 0, energy 2
T  43  Medicham        FAINTS
T  43  Medicham        COUNTER cancelled (cleared after a faint)
T  44  Medicham        decides replacement -> Azumarill  (best matchup vs Swampert: Azumarill 977, Registeel 791)
T  44  Swampert        decides not to switch  (stay: HP 8% <= 25%)
T  44  Medicham        sends in Azumarill
T  45  Azumarill       decides fast BUBBLE  (stay: matchup vs Swampert 977 >= 450; energy 0 < 55 needed for ICE_BEAM)
T  45  Swampert        decides fast MUD_SHOT  (stay: HP 8% <= 25%; energy 2 < 40 needed for HYDRO_CANNON)
T  46  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 193, energy 11
T  47  Swampert        decides fast MUD_SHOT  (energy 11 < 40 needed for HYDRO_CANNON)
T  47  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 5, energy 11
T  48  Azumarill       decides fast BUBBLE  (energy 11 < 55 needed for ICE_BEAM)
T  48  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 190, energy 20
T  49  Swampert        decides fast MUD_SHOT  (energy 20 < 40 needed for HYDRO_CANNON)
T  50  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 0, energy 22
T  50  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 187, energy 29
T  50  Swampert        FAINTS
T  51  Azumarill       decides not to switch  (stay: matchup vs Swampert 977 >= 450 (evaluated on turn 45))
T  51  Swampert        decides replacement -> Trevenant  (best matchup vs Azumarill: Trevenant 489, Altaria 196)
T  51  Swampert        sends in Trevenant
T  52  Azumarill       decides fast BUBBLE  (stay: matchup vs Trevenant 510 >= 450; energy 22 < 55 needed for ICE_BEAM)
T  52  Trevenant       decides fast SHADOW_CLAW  (stay: matchup vs Azumarill 489 >= 450; energy 0 < 40 needed for SEED_BOMB)
T  53  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 182, energy 8
T  54  Trevenant       decides fast SHADOW_CLAW  (energy 8 < 40 needed for SEED_BOMB)
T  54  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 129, energy 33
T  55  Azumarill       decides fast BUBBLE  (energy 33 < 55 needed for ICE_BEAM)
T  55  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 177, energy 16
T  56  Trevenant       decides fast SHADOW_CLAW  (energy 16 < 40 needed for SEED_BOMB)
T  57  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 125, energy 44
T  57  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 172, energy 24
T  58  Azumarill       decides fast BUBBLE  (energy 44 < 55 needed for ICE_BEAM)
T  58  Trevenant       decides fast SHADOW_CLAW  (energy 24 < 40 needed for SEED_BOMB)
T  59  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 167, energy 32
T  60  Trevenant       decides fast SHADOW_CLAW  (energy 32 < 40 needed for SEED_BOMB)
T  60  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 121, energy 55
T  61  Azumarill       decides charged ICE_BEAM  (ICE_BEAM ready (81 dmg, target by best_dpe))
T  61  Azumarill       CHARGED ICE_BEAM -> 81 dmg, Trevenant HP 40, energy 0
T  61  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 162, energy 40
T  62  Azumarill       decides zero_turn_switch -> Registeel  (best response: switch to Registeel (policy would stay: stay: matchup vs Trevenant 510 >= 450))
T  62  Trevenant       decides not to switch  (stay: matchup vs Azumarill 489 >= 450)
T  62  Azumarill       switches (0 turns) to Registeel  (switch timer 45s)
T  63  Registeel       decides fast LOCK_ON  (energy 0 < 75 needed for FOCUS_BLAST)
T  63  Trevenant       decides fast SHADOW_CLAW  (stay: matchup vs Registeel 348 < 450, no bench option >= 500 (Altaria 268); saving for SHADOW_BALL (40/50 energy, target by best_dpe))
T  63  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 39, energy 5
T  64  Registeel       decides fast LOCK_ON  (energy 5 < 75 needed for FOCUS_BLAST)
T  64  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 128, energy 48
T  64  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 38, energy 10
T  65  Registeel       decides fast LOCK_ON  (energy 10 < 75 needed for FOCUS_BLAST)
T  65  Trevenant       decides fast SHADOW_CLAW  (saving for SHADOW_BALL (48/50 energy, target by best_dpe))
T  65  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 37, energy 15
T  66  Registeel       decides fast LOCK_ON  (energy 15 < 75 needed for FOCUS_BLAST)
T  66  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 124, energy 56
T  66  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 36, energy 20
T  67  Registeel       decides fast LOCK_ON  (energy 20 < 75 needed for FOCUS_BLAST)
T  67  Trevenant       decides charged SHADOW_BALL  (SHADOW_BALL ready (46 dmg, target by best_dpe))
T  67  Trevenant       CHARGED SHADOW_BALL -> 46 dmg, Registeel HP 78, energy 6
T  67  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 35, energy 25
T  68  Trevenant       decides not to switch  (stay: matchup vs Registeel 348 < 450, no bench option >= 500 (Altaria 454))
T  69  Registeel       decides fast LOCK_ON  (energy 25 < 75 needed for FOCUS_BLAST)
T  69  Trevenant       decides fast SHADOW_CLAW  (energy 6 < 40 needed for SEED_BOMB)
T  69  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 34, energy 30
T  70  Registeel       decides fast LOCK_ON  (energy 30 < 75 needed for FOCUS_BLAST)
T  70  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 74, energy 14
T  70  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 33, energy 35
T  71  Registeel       decides fast LOCK_ON  (energy 35 < 75 needed for FOCUS_BLAST)
T  71  Trevenant       decides fast SHADOW_CLAW  (energy 14 < 40 needed for SEED_BOMB)
T  71  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 32, energy 40
T  72  Registeel       decides fast LOCK_ON  (energy 40 < 75 needed for FOCUS_BLAST)
T  72  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 70, energy 22
T  72  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 31, energy 45
T  73  Registeel       decides fast LOCK_ON  (energy 45 < 75 needed for FOCUS_BLAST)
T  73  Trevenant       decides fast SHADOW_CLAW  (energy 22 < 40 needed for SEED_BOMB)
T  73  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 30, energy 50
T  74  Registeel       decides fast LOCK_ON  (energy 50 < 75 needed for FOCUS_BLAST)
T  74  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 66, energy 30
T  74  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 29, energy 55
T  75  Registeel       decides fast LOCK_ON  (energy 55 < 75 needed for FOCUS_BLAST)
T  75  Trevenant       decides fast SHADOW_CLAW  (energy 30 < 40 needed for SEED_BOMB)
T  75  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 28, energy 60
T  76  Registeel       decides fast LOCK_ON  (energy 60 < 75 needed for FOCUS_BLAST)
T  76  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 62, energy 38
T  76  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 27, energy 65
T  77  Registeel       decides fast LOCK_ON  (energy 65 < 75 needed for FOCUS_BLAST)
T  77  Trevenant       decides fast SHADOW_CLAW  (energy 38 < 40 needed for SEED_BOMB)
T  77  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 26, energy 70
T  78  Registeel       decides fast LOCK_ON  (energy 70 < 75 needed for FOCUS_BLAST)
T  78  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 58, energy 46
T  78  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 25, energy 75
T  79  Registeel       decides charged FOCUS_BLAST  (FOCUS_BLAST deals 34 >= opponent HP 25, no shields)
T  79  Trevenant       decides charged SEED_BOMB  (about to faint (opponent can use FOCUS_BLAST for 34 >= my HP 25, I have no shields): use highest-damage available move)
T  79  Trevenant       CHARGED SEED_BOMB -> 18 dmg, Registeel HP 40, energy 6
T  79  Registeel       CHARGED FOCUS_BLAST -> 34 dmg, Trevenant HP 0, energy 0
T  79  Trevenant       FAINTS
T  80  Trevenant       decides replacement -> Altaria  (best matchup vs Registeel: Altaria 716)
T  80  Trevenant       sends in Altaria
T  81  Registeel       decides fast LOCK_ON  (energy 0 < 75 needed for FOCUS_BLAST)
T  81  Altaria         decides fast DRAGON_BREATH  (energy 0 < 50 needed for SKY_ATTACK)
T  81  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 140, energy 5
T  81  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 39, energy 4
T  82  Registeel       decides fast LOCK_ON  (energy 5 < 75 needed for FOCUS_BLAST)
T  82  Altaria         decides fast DRAGON_BREATH  (energy 4 < 50 needed for SKY_ATTACK)
T  82  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 139, energy 10
T  82  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 38, energy 8
T  83  Registeel       decides fast LOCK_ON  (energy 10 < 75 needed for FOCUS_BLAST)
T  83  Altaria         decides fast DRAGON_BREATH  (energy 8 < 50 needed for SKY_ATTACK)
T  83  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 138, energy 15
T  83  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 37, energy 12
T  84  Registeel       decides fast LOCK_ON  (energy 15 < 75 needed for FOCUS_BLAST)
T  84  Altaria         decides fast DRAGON_BREATH  (energy 12 < 50 needed for SKY_ATTACK)
T  84  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 137, energy 20
T  84  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 36, energy 16
T  85  Registeel       decides fast LOCK_ON  (energy 20 < 75 needed for FOCUS_BLAST)
T  85  Altaria         decides fast DRAGON_BREATH  (energy 16 < 50 needed for SKY_ATTACK)
T  85  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 136, energy 25
T  85  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 35, energy 20
T  86  Registeel       decides fast LOCK_ON  (energy 25 < 75 needed for FOCUS_BLAST)
T  86  Altaria         decides fast DRAGON_BREATH  (energy 20 < 50 needed for SKY_ATTACK)
T  86  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 135, energy 30
T  86  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 34, energy 24
T  87  Registeel       decides fast LOCK_ON  (energy 30 < 75 needed for FOCUS_BLAST)
T  87  Altaria         decides fast DRAGON_BREATH  (energy 24 < 50 needed for SKY_ATTACK)
T  87  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 134, energy 35
T  87  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 33, energy 28
T  88  Registeel       decides fast LOCK_ON  (energy 35 < 75 needed for FOCUS_BLAST)
T  88  Altaria         decides fast DRAGON_BREATH  (energy 28 < 50 needed for SKY_ATTACK)
T  88  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 133, energy 40
T  88  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 32, energy 32
T  89  Registeel       decides fast LOCK_ON  (energy 40 < 75 needed for FOCUS_BLAST)
T  89  Altaria         decides fast DRAGON_BREATH  (energy 32 < 50 needed for SKY_ATTACK)
T  89  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 132, energy 45
T  89  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 31, energy 36
T  90  Registeel       decides fast LOCK_ON  (energy 45 < 75 needed for FOCUS_BLAST)
T  90  Altaria         decides fast DRAGON_BREATH  (energy 36 < 50 needed for SKY_ATTACK)
T  90  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 131, energy 50
T  90  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 30, energy 40
T  91  Registeel       decides fast LOCK_ON  (energy 50 < 75 needed for FOCUS_BLAST)
T  91  Altaria         decides fast DRAGON_BREATH  (energy 40 < 50 needed for SKY_ATTACK)
T  91  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 130, energy 55
T  91  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 29, energy 44
T  92  Registeel       decides fast LOCK_ON  (energy 55 < 75 needed for FOCUS_BLAST)
T  92  Altaria         decides fast DRAGON_BREATH  (energy 44 < 50 needed for SKY_ATTACK)
T  92  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 129, energy 60
T  92  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 28, energy 48
T  93  Registeel       decides fast LOCK_ON  (energy 60 < 75 needed for FOCUS_BLAST)
T  93  Altaria         decides fast DRAGON_BREATH  (energy 48 < 50 needed for SKY_ATTACK)
T  93  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 128, energy 65
T  93  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 27, energy 52
T  94  Registeel       decides fast LOCK_ON  (stay: HP 20% <= 25%; energy 65 < 75 needed for FOCUS_BLAST)
T  94  Altaria         decides charged SKY_ATTACK  (SKY_ATTACK ready (20 dmg, target by best_dpe))
T  94  Altaria         CHARGED SKY_ATTACK -> 20 dmg, Registeel HP 7, energy 2
T  94  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 127, energy 70
T  95  Registeel       decides not to switch  (stay: HP 5% <= 25%)
T  96  Registeel       decides fast LOCK_ON  (energy 70 < 75 needed for FOCUS_BLAST)
T  96  Altaria         decides fast DRAGON_BREATH  (energy 2 < 50 needed for SKY_ATTACK)
T  96  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 126, energy 75
T  96  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 6, energy 6
T  97  Registeel       decides fast LOCK_ON  (saving for ZAP_CANNON (75/80 energy, target by best_dpe))
T  97  Altaria         decides fast DRAGON_BREATH  (energy 6 < 50 needed for SKY_ATTACK)
T  97  Registeel       fast LOCK_ON -> 1 dmg, Altaria HP 125, energy 80
T  97  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 5, energy 10
T  98  Registeel       decides charged ZAP_CANNON  (ZAP_CANNON ready (60 dmg, target by best_dpe))
T  98  Altaria         decides fast DRAGON_BREATH  (energy 10 < 50 needed for SKY_ATTACK)
T  98  Registeel       CHARGED ZAP_CANNON -> 60 dmg, Altaria HP 65, energy 0
T  98  Altaria         fast DRAGON_BREATH -> 1 dmg, Registeel HP 4, energy 14
T  99  Registeel       decides zero_turn_switch -> Azumarill  (best response: switch to Azumarill (policy would stay: stay: HP 3% <= 25%))
T  99  Registeel       switches (0 turns) to Azumarill  (switch timer 45s)
T 100  Azumarill       decides fast BUBBLE  (energy 0 < 55 needed for ICE_BEAM)
T 100  Altaria         decides fast DRAGON_BREATH  (energy 14 < 50 needed for SKY_ATTACK)
T 100  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 161, energy 18
T 101  Altaria         decides fast DRAGON_BREATH  (energy 18 < 50 needed for SKY_ATTACK)
T 101  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 160, energy 22
T 102  Altaria         decides fast DRAGON_BREATH  (energy 22 < 50 needed for SKY_ATTACK)
T 102  Azumarill       fast BUBBLE -> 3 dmg, Altaria HP 62, energy 11
T 102  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 159, energy 26
T 103  Azumarill       decides fast BUBBLE  (energy 11 < 55 needed for ICE_BEAM)
T 103  Altaria         decides fast DRAGON_BREATH  (energy 26 < 50 needed for SKY_ATTACK)
T 103  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 158, energy 30
T 104  Altaria         decides fast DRAGON_BREATH  (energy 30 < 50 needed for SKY_ATTACK)
T 104  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 157, energy 34
T 105  Altaria         decides fast DRAGON_BREATH  (energy 34 < 50 needed for SKY_ATTACK)
T 105  Azumarill       fast BUBBLE -> 3 dmg, Altaria HP 59, energy 22
T 105  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 156, energy 38
T 106  Azumarill       decides fast BUBBLE  (energy 22 < 55 needed for ICE_BEAM)
T 106  Altaria         decides fast DRAGON_BREATH  (energy 38 < 50 needed for SKY_ATTACK)
T 106  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 155, energy 42
T 107  Altaria         decides fast DRAGON_BREATH  (energy 42 < 50 needed for SKY_ATTACK)
T 107  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 154, energy 46
T 108  Altaria         decides fast DRAGON_BREATH  (energy 46 < 50 needed for SKY_ATTACK)
T 108  Azumarill       fast BUBBLE -> 3 dmg, Altaria HP 56, energy 33
T 108  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 153, energy 50
T 109  Azumarill       decides fast BUBBLE  (energy 33 < 55 needed for ICE_BEAM)
T 109  Altaria         decides fast DRAGON_BREATH  (timing: opponent's fast move is not about to finish (its cooldown 0))
T 109  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 152, energy 54
T 110  Altaria         decides fast DRAGON_BREATH  (timing: opponent's fast move is not about to finish (its cooldown 2))
T 110  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 151, energy 58
T 111  Altaria         decides charged SKY_ATTACK  (SKY_ATTACK ready (44 dmg, target by best_dpe))
T 111  Altaria         CHARGED SKY_ATTACK -> 44 dmg, Azumarill HP 107, energy 8
T 111  Azumarill       fast BUBBLE -> 3 dmg, Altaria HP 53, energy 44
T 113  Azumarill       decides fast BUBBLE  (energy 44 < 55 needed for ICE_BEAM)
T 113  Altaria         decides fast DRAGON_BREATH  (energy 8 < 50 needed for SKY_ATTACK)
T 113  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 106, energy 12
T 114  Altaria         decides fast DRAGON_BREATH  (energy 12 < 50 needed for SKY_ATTACK)
T 114  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 105, energy 16
T 115  Altaria         decides fast DRAGON_BREATH  (energy 16 < 50 needed for SKY_ATTACK)
T 115  Azumarill       fast BUBBLE -> 3 dmg, Altaria HP 50, energy 55
T 115  Altaria         fast DRAGON_BREATH -> 1 dmg, Azumarill HP 104, energy 20
T 116  Azumarill       decides charged ICE_BEAM  (ICE_BEAM deals 89 >= opponent HP 50, no shields)
T 116  Altaria         decides fast DRAGON_BREATH  (energy 20 < 50 needed for SKY_ATTACK)
T 116  Azumarill       CHARGED ICE_BEAM -> 89 dmg, Altaria HP 0, energy 0
T 116  Altaria         DRAGON_BREATH cancelled (knocked out by a charged move this turn)
T 116  Altaria         FAINTS
```
