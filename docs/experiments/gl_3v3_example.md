3v3 例子：Azumarill / Medicham / Registeel 对 Swampert / Altaria / Trevenant，超级联盟，双方都用默认的 3v3 策略。

- 配置文件：`experiments/gl_3v3_example.toml`
- 联盟：超级联盟；赛季规则：PvPoke 兼容
- 机制规则：与 PvPoke 一致（默认）
- 策略：双方都是 3v3 策略 TeamPolicy（规则和默认参数见 docs/mechanics.md 13.7）。出招照简单规则策略；倒下后换上对位评分最高的；当前对位不好就主动换人；不在必输的对位上开盾
- 评分：本项目的口径（docs/mechanics.md 13.2 D1），500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整。双方加起来 1000

## 队伍

**Team A**（第 0 方，2 盾）

- 首发 Azumarill：Azumarill，CP 1499，45.5 级，IV 0/15/15，BUBBLE / ICE_BEAM, PLAY_ROUGH
- 后备 Medicham：Medicham，CP 1499，50 级，IV 5/15/15，COUNTER / ICE_PUNCH, PSYCHIC
- 后备 Registeel：Registeel，CP 1499，23.5 级，IV 2/13/14，LOCK_ON / FOCUS_BLAST, ZAP_CANNON
- 策略：TeamPolicy，默认参数

**Team B**（第 1 方，2 盾）

- 首发 Swampert：Swampert，CP 1498，19 级，IV 0/14/14，MUD_SHOT / HYDRO_CANNON, EARTHQUAKE
- 后备 Altaria：Altaria，CP 1497，29 级，IV 0/14/15，DRAGON_BREATH / SKY_ATTACK, MOONBLAST
- 后备 Trevenant：Trevenant，CP 1497，22 级，IV 0/15/15，SHADOW_CLAW / SEED_BOMB, SHADOW_BALL
- 策略：TeamPolicy，默认参数

队伍检查通过：每队 3 只；没有同一种宝可梦（按图鉴编号）；Mega 不超过 1 只。

## 结果

Team B 赢。评分 221 对 778；剩余 0 只对 3 只；剩余盾 0 对 0；100 回合，对战时间 145 秒（大招每次按 10 秒算）。

## 每只的情况

挨大招：被大招打中时开盾挡下的次数 / 队伍还有盾但没开的次数。被盾挡下的大招算 1 点伤害。

| 队伍 | 宝可梦 | 剩余 HP | 剩余能量 | 造成伤害 | 受到伤害 | 快招 | 大招 | 挨大招：开盾 / 没开 | 倒下 |
|---|---|---|---|---|---|---|---|---|---|
| Team A | Azumarill | 0 / 196 | 55 | 80 | 219 | 15 | ICE_BEAM ×2 | 2 / 0 | 第 55 回合 |
| Team A | Medicham | 0 / 142 | 36 | 18 | 143 | 6 | — | 0 / 0 | 第 100 回合 |
| Team A | Registeel | 0 / 132 | 50 | 81 | 144 | 26 | ZAP_CANNON ×1 | 0 / 0 | 第 86 回合 |
| Team B | Swampert | 84 / 139 | 37 | 41 | 55 | 13 | HYDRO_CANNON ×2 | 1 / 0 | — |
| Team B | Altaria | 141 / 141 | 0 | 0 | 0 | 0 | — | 0 / 0 | — |
| Team B | Trevenant | 9 / 133 | 2 | 465 | 124 | 29 | SEED_BOMB ×2, SHADOW_BALL ×3 | 1 / 0 | — |

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
| 31 | Team B | Swampert → Trevenant | 0 回合换人 | switch: matchup vs Azumarill 424 < 450, Trevenant 644 >= 524 (Trevenant 644, Altaria 338) |
| 56 | Team A | Azumarill → Registeel | 倒下后换人 | best matchup vs Trevenant: Registeel 398, Medicham 172 |
| 87 | Team A | Registeel → Medicham | 倒下后换人 | best matchup vs Trevenant: Medicham 466 |

## 大招和开盾

| 回合 | 出招 | 大招 | 挨打 | 结果 | 开不开盾的原因 |
|---|---|---|---|---|---|
| 21 | Swampert | HYDRO_CANNON | Azumarill | 开盾挡下 | always shield (2 left); with a shield, matchup vs Swampert 555 |
| 26 | Azumarill | ICE_BEAM | Swampert | 开盾挡下 | always shield (2 left); with a shield, matchup vs Azumarill 512 |
| 30 | Swampert | HYDRO_CANNON | Azumarill | 开盾挡下 | always shield (1 left); with a shield, matchup vs Swampert 567 |
| 35 | Azumarill | ICE_BEAM | Trevenant | 开盾挡下 | always shield (1 left); with a shield, matchup vs Azumarill 586 |
| 45 | Trevenant | SEED_BOMB | Azumarill | 64 伤害，剩 HP 61 | 没有盾 |
| 55 | Trevenant | SEED_BOMB | Azumarill | 64 伤害，剩 HP 0 | 没有盾 |
| 71 | Trevenant | SHADOW_BALL | Registeel | 46 伤害，剩 HP 58 | 没有盾 |
| 74 | Registeel | ZAP_CANNON | Trevenant | 55 伤害，剩 HP 37 | 没有盾 |
| 86 | Trevenant | SHADOW_BALL | Registeel | 46 伤害，剩 HP 0 | 没有盾 |
| 100 | Trevenant | SHADOW_BALL | Medicham | 101 伤害，剩 HP 0 | 没有盾 |

## 时间线

每回合的决定（decides …，括号里是原因）和结算。T 后面是回合数。

```text
T   1  Azumarill       decides fast BUBBLE  (stay: matchup vs Swampert 452 >= 450; energy 0 < 55 needed for ICE_BEAM)
T   1  Swampert        decides fast MUD_SHOT  (stay: matchup vs Azumarill 547 >= 450; energy 0 < 40 needed for HYDRO_CANNON)
T   2  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 193, energy 9
T   3  Swampert        decides fast MUD_SHOT  (energy 9 < 40 needed for HYDRO_CANNON)
T   3  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 133, energy 11
T   4  Azumarill       decides fast BUBBLE  (energy 11 < 55 needed for ICE_BEAM)
T   4  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 190, energy 18
T   5  Swampert        decides fast MUD_SHOT  (energy 18 < 40 needed for HYDRO_CANNON)
T   6  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 127, energy 22
T   6  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 187, energy 27
T   7  Azumarill       decides fast BUBBLE  (energy 22 < 55 needed for ICE_BEAM)
T   7  Swampert        decides fast MUD_SHOT  (energy 27 < 40 needed for HYDRO_CANNON)
T   8  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 184, energy 36
T   9  Swampert        decides fast MUD_SHOT  (energy 36 < 40 needed for HYDRO_CANNON)
T   9  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 121, energy 33
T  10  Azumarill       decides fast BUBBLE  (energy 33 < 55 needed for ICE_BEAM)
T  10  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 181, energy 45
T  11  Swampert        decides fast MUD_SHOT  (saving for EARTHQUAKE (45/65 energy, target by best_dpe))
T  12  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 115, energy 44
T  12  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 178, energy 54
T  13  Azumarill       decides fast BUBBLE  (energy 44 < 55 needed for ICE_BEAM)
T  13  Swampert        decides fast MUD_SHOT  (saving for EARTHQUAKE (54/65 energy, target by best_dpe))
T  14  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 175, energy 63
T  15  Swampert        decides fast MUD_SHOT  (saving for EARTHQUAKE (63/65 energy, target by best_dpe))
T  15  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 109, energy 55
T  16  Azumarill       decides fast BUBBLE  (saving for PLAY_ROUGH (55/60 energy, target by best_dpe))
T  16  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 172, energy 72
T  17  Swampert        decides fast MUD_SHOT  (timing: opponent's fast move is not about to finish (its cooldown 2))
T  18  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 103, energy 66
T  18  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 169, energy 81
T  19  Azumarill       decides fast BUBBLE  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  19  Swampert        decides fast MUD_SHOT  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  20  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 166, energy 90
T  21  Swampert        decides charged HYDRO_CANNON  (bait: opponent has 2 shield(s), throw HYDRO_CANNON (40) instead of EARTHQUAKE)
T  21  Swampert        CHARGED HYDRO_CANNON -> 1 dmg (shielded), Azumarill HP 165, energy 50  [shield: always shield (2 left); with a shield, matchup vs Swampert 555]
T  21  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 97, energy 77
T  22  Azumarill       decides not to switch  (stay: matchup vs Swampert 609 >= 450)
T  22  Swampert        decides not to switch  (stay: matchup vs Azumarill 390 < 450, no bench option >= 500 (Trevenant 403, Altaria 238))
T  23  Azumarill       decides fast BUBBLE  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  23  Swampert        decides fast MUD_SHOT  (saving for EARTHQUAKE (50/65 energy, target by best_dpe))
T  24  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 162, energy 59
T  25  Swampert        decides fast MUD_SHOT  (saving for EARTHQUAKE (59/65 energy, target by best_dpe))
T  25  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 91, energy 88
T  26  Azumarill       decides charged ICE_BEAM  (bait: opponent has 2 shield(s), throw ICE_BEAM (55) instead of PLAY_ROUGH)
T  26  Azumarill       CHARGED ICE_BEAM -> 1 dmg (shielded), Swampert HP 90, energy 33  [shield: always shield (2 left); with a shield, matchup vs Azumarill 512]
T  26  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 159, energy 68
T  27  Azumarill       decides not to switch  (stay: matchup vs Swampert 472 >= 450)
T  27  Swampert        decides not to switch  (stay: matchup vs Azumarill 527 >= 450)
T  28  Azumarill       decides fast BUBBLE  (energy 33 < 55 needed for ICE_BEAM)
T  28  Swampert        decides fast MUD_SHOT  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  29  Swampert        fast MUD_SHOT -> 3 dmg, Azumarill HP 156, energy 77
T  30  Swampert        decides charged HYDRO_CANNON  (bait: opponent has 1 shield(s), throw HYDRO_CANNON (40) instead of EARTHQUAKE)
T  30  Swampert        CHARGED HYDRO_CANNON -> 1 dmg (shielded), Azumarill HP 155, energy 37  [shield: always shield (1 left); with a shield, matchup vs Swampert 567]
T  30  Azumarill       fast BUBBLE -> 6 dmg, Swampert HP 84, energy 44
T  31  Azumarill       decides not to switch  (stay: matchup vs Swampert 574 >= 450)
T  31  Swampert        decides zero_turn_switch -> Trevenant  (switch: matchup vs Azumarill 424 < 450, Trevenant 644 >= 524 (Trevenant 644, Altaria 338))
T  31  Swampert        switches (0 turns) to Trevenant  (switch timer 45s)
T  32  Azumarill       decides fast BUBBLE  (stay: matchup vs Trevenant 355 < 450, no bench option >= 500 (Registeel 202, Medicham 78); energy 44 < 55 needed for ICE_BEAM)
T  32  Trevenant       decides fast SHADOW_CLAW  (energy 0 < 40 needed for SEED_BOMB)
T  33  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 150, energy 8
T  34  Trevenant       decides fast SHADOW_CLAW  (energy 8 < 40 needed for SEED_BOMB)
T  34  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 129, energy 55
T  35  Azumarill       decides charged ICE_BEAM  (ICE_BEAM ready (81 dmg, target by best_dpe))
T  35  Azumarill       CHARGED ICE_BEAM -> 1 dmg (shielded), Trevenant HP 128, energy 0  [shield: always shield (1 left); with a shield, matchup vs Azumarill 586]
T  35  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 145, energy 16
T  36  Azumarill       decides not to switch  (stay: matchup vs Trevenant 93 < 450, no bench option >= 500 (Registeel 308, Medicham 97))
T  37  Azumarill       decides fast BUBBLE  (energy 0 < 55 needed for ICE_BEAM)
T  37  Trevenant       decides fast SHADOW_CLAW  (energy 16 < 40 needed for SEED_BOMB)
T  38  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 140, energy 24
T  39  Trevenant       decides fast SHADOW_CLAW  (energy 24 < 40 needed for SEED_BOMB)
T  39  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 124, energy 11
T  40  Azumarill       decides fast BUBBLE  (energy 11 < 55 needed for ICE_BEAM)
T  40  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 135, energy 32
T  41  Trevenant       decides fast SHADOW_CLAW  (energy 32 < 40 needed for SEED_BOMB)
T  42  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 120, energy 22
T  42  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 130, energy 40
T  43  Azumarill       decides fast BUBBLE  (energy 22 < 55 needed for ICE_BEAM)
T  43  Trevenant       decides fast SHADOW_CLAW  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  44  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 125, energy 48
T  45  Trevenant       decides charged SEED_BOMB  (SEED_BOMB ready (64 dmg, target by best_dpe))
T  45  Trevenant       CHARGED SEED_BOMB -> 64 dmg, Azumarill HP 61, energy 8
T  45  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 116, energy 33
T  46  Azumarill       decides not to switch  (stay: matchup vs Trevenant 93 < 450, no bench option >= 500 (Registeel 360, Medicham 131))
T  47  Azumarill       decides fast BUBBLE  (energy 33 < 55 needed for ICE_BEAM)
T  47  Trevenant       decides fast SHADOW_CLAW  (energy 8 < 40 needed for SEED_BOMB)
T  48  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 56, energy 16
T  49  Trevenant       decides fast SHADOW_CLAW  (energy 16 < 40 needed for SEED_BOMB)
T  49  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 112, energy 44
T  50  Azumarill       decides fast BUBBLE  (energy 44 < 55 needed for ICE_BEAM)
T  50  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 51, energy 24
T  51  Trevenant       decides fast SHADOW_CLAW  (energy 24 < 40 needed for SEED_BOMB)
T  52  Azumarill       fast BUBBLE -> 4 dmg, Trevenant HP 108, energy 55
T  52  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 46, energy 32
T  53  Azumarill       decides fast BUBBLE  (timing: opponent's fast move is not about to finish (its cooldown 0))
T  53  Trevenant       decides fast SHADOW_CLAW  (energy 32 < 40 needed for SEED_BOMB)
T  54  Trevenant       fast SHADOW_CLAW -> 5 dmg, Azumarill HP 41, energy 40
T  55  Trevenant       decides charged SEED_BOMB  (SEED_BOMB deals 64 >= opponent HP 41, no shields)
T  55  Trevenant       CHARGED SEED_BOMB -> 64 dmg, Azumarill HP 0, energy 0
T  55  Azumarill       BUBBLE cancelled (knocked out by a charged move this turn)
T  55  Azumarill       FAINTS
T  56  Azumarill       decides replacement -> Registeel  (best matchup vs Trevenant: Registeel 398, Medicham 172)
T  56  Azumarill       sends in Registeel
T  57  Registeel       decides fast LOCK_ON  (stay: matchup vs Trevenant 398 < 450, no bench option >= 500 (Medicham 172); energy 0 < 75 needed for FOCUS_BLAST)
T  57  Trevenant       decides fast SHADOW_CLAW  (energy 0 < 40 needed for SEED_BOMB)
T  57  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 107, energy 5
T  58  Registeel       decides fast LOCK_ON  (energy 5 < 75 needed for FOCUS_BLAST)
T  58  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 128, energy 8
T  58  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 106, energy 10
T  59  Registeel       decides fast LOCK_ON  (energy 10 < 75 needed for FOCUS_BLAST)
T  59  Trevenant       decides fast SHADOW_CLAW  (energy 8 < 40 needed for SEED_BOMB)
T  59  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 105, energy 15
T  60  Registeel       decides fast LOCK_ON  (energy 15 < 75 needed for FOCUS_BLAST)
T  60  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 124, energy 16
T  60  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 104, energy 20
T  61  Registeel       decides fast LOCK_ON  (energy 20 < 75 needed for FOCUS_BLAST)
T  61  Trevenant       decides fast SHADOW_CLAW  (energy 16 < 40 needed for SEED_BOMB)
T  61  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 103, energy 25
T  62  Registeel       decides fast LOCK_ON  (energy 25 < 75 needed for FOCUS_BLAST)
T  62  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 120, energy 24
T  62  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 102, energy 30
T  63  Registeel       decides fast LOCK_ON  (energy 30 < 75 needed for FOCUS_BLAST)
T  63  Trevenant       decides fast SHADOW_CLAW  (energy 24 < 40 needed for SEED_BOMB)
T  63  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 101, energy 35
T  64  Registeel       decides fast LOCK_ON  (energy 35 < 75 needed for FOCUS_BLAST)
T  64  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 116, energy 32
T  64  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 100, energy 40
T  65  Registeel       decides fast LOCK_ON  (energy 40 < 75 needed for FOCUS_BLAST)
T  65  Trevenant       decides fast SHADOW_CLAW  (stay: matchup vs Registeel 601 >= 450; energy 32 < 40 needed for SEED_BOMB)
T  65  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 99, energy 45
T  66  Registeel       decides fast LOCK_ON  (energy 45 < 75 needed for FOCUS_BLAST)
T  66  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 112, energy 40
T  66  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 98, energy 50
T  67  Registeel       decides fast LOCK_ON  (energy 50 < 75 needed for FOCUS_BLAST)
T  67  Trevenant       decides fast SHADOW_CLAW  (saving for SHADOW_BALL (40/50 energy, target by best_dpe))
T  67  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 97, energy 55
T  68  Registeel       decides fast LOCK_ON  (energy 55 < 75 needed for FOCUS_BLAST)
T  68  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 108, energy 48
T  68  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 96, energy 60
T  69  Registeel       decides fast LOCK_ON  (energy 60 < 75 needed for FOCUS_BLAST)
T  69  Trevenant       decides fast SHADOW_CLAW  (saving for SHADOW_BALL (48/50 energy, target by best_dpe))
T  69  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 95, energy 65
T  70  Registeel       decides fast LOCK_ON  (energy 65 < 75 needed for FOCUS_BLAST)
T  70  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 104, energy 56
T  70  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 94, energy 70
T  71  Registeel       decides fast LOCK_ON  (energy 70 < 75 needed for FOCUS_BLAST)
T  71  Trevenant       decides charged SHADOW_BALL  (SHADOW_BALL ready (46 dmg, target by best_dpe))
T  71  Trevenant       CHARGED SHADOW_BALL -> 46 dmg, Registeel HP 58, energy 6
T  71  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 93, energy 75
T  72  Registeel       decides not to switch  (stay: matchup vs Trevenant 398 < 450, no bench option >= 500 (Medicham 218))
T  72  Trevenant       decides not to switch  (stay: matchup vs Registeel 601 >= 450)
T  73  Registeel       decides fast LOCK_ON  (saving for ZAP_CANNON (75/80 energy, target by best_dpe))
T  73  Trevenant       decides fast SHADOW_CLAW  (energy 6 < 40 needed for SEED_BOMB)
T  73  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 92, energy 80
T  74  Registeel       decides charged ZAP_CANNON  (ZAP_CANNON ready (55 dmg, target by best_dpe))
T  74  Registeel       CHARGED ZAP_CANNON -> 55 dmg, Trevenant HP 37, energy 0
T  74  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 54, energy 14
T  75  Registeel       decides not to switch  (stay: matchup vs Trevenant 398 < 450, no bench option >= 500 (Medicham 439))
T  75  Trevenant       decides not to switch  (stay: matchup vs Registeel 601 >= 450)
T  76  Registeel       decides fast LOCK_ON  (energy 0 < 75 needed for FOCUS_BLAST)
T  76  Trevenant       decides fast SHADOW_CLAW  (energy 14 < 40 needed for SEED_BOMB)
T  76  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 36, energy 5
T  77  Registeel       decides fast LOCK_ON  (energy 5 < 75 needed for FOCUS_BLAST)
T  77  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 50, energy 22
T  77  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 35, energy 10
T  78  Registeel       decides fast LOCK_ON  (energy 10 < 75 needed for FOCUS_BLAST)
T  78  Trevenant       decides fast SHADOW_CLAW  (energy 22 < 40 needed for SEED_BOMB)
T  78  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 34, energy 15
T  79  Registeel       decides fast LOCK_ON  (energy 15 < 75 needed for FOCUS_BLAST)
T  79  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 46, energy 30
T  79  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 33, energy 20
T  80  Registeel       decides fast LOCK_ON  (energy 20 < 75 needed for FOCUS_BLAST)
T  80  Trevenant       decides fast SHADOW_CLAW  (energy 30 < 40 needed for SEED_BOMB)
T  80  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 32, energy 25
T  81  Registeel       decides fast LOCK_ON  (energy 25 < 75 needed for FOCUS_BLAST)
T  81  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 42, energy 38
T  81  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 31, energy 30
T  82  Registeel       decides fast LOCK_ON  (energy 30 < 75 needed for FOCUS_BLAST)
T  82  Trevenant       decides fast SHADOW_CLAW  (energy 38 < 40 needed for SEED_BOMB)
T  82  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 30, energy 35
T  83  Registeel       decides fast LOCK_ON  (energy 35 < 75 needed for FOCUS_BLAST)
T  83  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 38, energy 46
T  83  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 29, energy 40
T  84  Registeel       decides fast LOCK_ON  (energy 40 < 75 needed for FOCUS_BLAST)
T  84  Trevenant       decides fast SHADOW_CLAW  (saving for SHADOW_BALL (46/50 energy, target by best_dpe))
T  84  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 28, energy 45
T  85  Registeel       decides fast LOCK_ON  (energy 45 < 75 needed for FOCUS_BLAST)
T  85  Trevenant       fast SHADOW_CLAW -> 4 dmg, Registeel HP 34, energy 54
T  85  Registeel       fast LOCK_ON -> 1 dmg, Trevenant HP 27, energy 50
T  86  Registeel       decides fast LOCK_ON  (energy 50 < 75 needed for FOCUS_BLAST)
T  86  Trevenant       decides charged SHADOW_BALL  (SHADOW_BALL deals 46 >= opponent HP 34, no shields)
T  86  Trevenant       CHARGED SHADOW_BALL -> 46 dmg, Registeel HP 0, energy 4
T  86  Registeel       LOCK_ON cancelled (knocked out by a charged move this turn)
T  86  Registeel       FAINTS
T  87  Registeel       decides replacement -> Medicham  (best matchup vs Trevenant: Medicham 466)
T  87  Trevenant       decides not to switch  (stay: HP 20% <= 25%)
T  87  Registeel       sends in Medicham
T  88  Medicham        decides fast COUNTER  (energy 0 < 40 needed for ICE_PUNCH)
T  88  Trevenant       decides fast SHADOW_CLAW  (stay: HP 20% <= 25%; energy 4 < 40 needed for SEED_BOMB)
T  89  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 24, energy 6
T  89  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 135, energy 12
T  90  Medicham        decides fast COUNTER  (energy 6 < 40 needed for ICE_PUNCH)
T  90  Trevenant       decides fast SHADOW_CLAW  (energy 12 < 40 needed for SEED_BOMB)
T  91  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 21, energy 12
T  91  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 128, energy 20
T  92  Medicham        decides fast COUNTER  (energy 12 < 40 needed for ICE_PUNCH)
T  92  Trevenant       decides fast SHADOW_CLAW  (energy 20 < 40 needed for SEED_BOMB)
T  93  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 18, energy 18
T  93  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 121, energy 28
T  94  Medicham        decides fast COUNTER  (energy 18 < 40 needed for ICE_PUNCH)
T  94  Trevenant       decides fast SHADOW_CLAW  (energy 28 < 40 needed for SEED_BOMB)
T  95  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 15, energy 24
T  95  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 114, energy 36
T  96  Medicham        decides fast COUNTER  (energy 24 < 40 needed for ICE_PUNCH)
T  96  Trevenant       decides fast SHADOW_CLAW  (energy 36 < 40 needed for SEED_BOMB)
T  97  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 12, energy 30
T  97  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 107, energy 44
T  98  Medicham        decides fast COUNTER  (energy 30 < 40 needed for ICE_PUNCH)
T  98  Trevenant       decides fast SHADOW_CLAW  (saving for SHADOW_BALL (44/50 energy, target by best_dpe))
T  99  Medicham        fast COUNTER -> 3 dmg, Trevenant HP 9, energy 36
T  99  Trevenant       fast SHADOW_CLAW -> 7 dmg, Medicham HP 100, energy 52
T 100  Medicham        decides fast COUNTER  (energy 36 < 40 needed for ICE_PUNCH)
T 100  Trevenant       decides charged SHADOW_BALL  (SHADOW_BALL deals 101 >= opponent HP 100, no shields)
T 100  Trevenant       CHARGED SHADOW_BALL -> 101 dmg, Medicham HP 0, energy 2
T 100  Medicham        FAINTS
```
