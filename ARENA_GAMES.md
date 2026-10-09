# AHGS NOVA 对战玩法 · 游戏设计（草案 v0.1）

> 状态:**P0 + P1 已落地(2026-09-30)**——内置六款对战游戏:井字棋(参考)/四子棋/五子棋/
> 黑白棋(P0)+ 光轮 Tron/炸弹人(P1,翻牌配对经评审取消);炸弹人支持 **2-4 人同局**
> (名次组制多人 ELO,格子独占)。后端 pytest 111 通过,`npm run build` 通过。P2 仍为设计。
> 本文是对战玩法(Arena)的游戏设计文档,覆盖
> [`ahgs-nova-be/app/arenas/`](ahgs-nova-be/app/arenas/)（规则与裁判实现）与
> [`ahgs-nova-next/src/views/ArenaView.vue`](ahgs-nova-next/src/views/ArenaView.vue)（玩法呈现）。
> tictactoe 为参考实现闭环（上传 bot → 约战 → 回放 → ELO 榜）。

---

## 1. 职责范围

- **管**：对战游戏的内容设计（规则、bot 契约、参数、判定与回放格式）、元玩法（赛制 / ELO / 防刷）、
  ArenaView 的玩法呈现设计。
- **不管**：执行调度与队列（`services/executors/`）、鉴权与配额、进化等其他模块。

## 2. 硬约束（来自执行框架，游戏设计不得违反）

约束出处：`app/arenas/runtime.py`（bot 子进程 JSON 行协议）、
`services/executors/arena_match.py`（ELO 落库）、`app/arenas/base.py`（扩展点协议）。

| # | 约束 | 对游戏设计的含义 |
|---|---|---|
| 1 | bot 入口固定为 `move(board, me)`，worker 只把返回值装进 `{"move": ...}` | 所有动作必须编码为**单个整数**：多维动作用 `r*N+c` 或方向枚举；返回 None/list/越界一律判非法 |
| 2 | `config` 不透传给 bot（worker 只传 board / me，见 `_WORKER_SRC`） | **board 自描述原则**：bot 需要感知的规则参数（棋盘尺寸等）必须能从 board 本身读出；禁止设计"不读 config 就不会玩"的游戏 |
| 3 | `board` 是任意 JSON 值（worker 原样透传） | board 语义 = "**该玩家的观测视图**"，不必是原始棋盘 → 隐藏信息游戏零改动支持；list / dict 均可 |
| 4 | 每 bot 每局一个**持久**子进程，局间销毁重建 | bot 可在局内自建记忆与缓存（博弈树、翻牌记忆）；跨局无状态 |
| 5 | 按步超时 / 异常 / 非法 → 当局判负，不取消整场 | reason 固定五值（§3.2）；每局新起进程的放大效应见 §3.4 |
| 6 | ~~ELO 逐局两两更新（`players` 恰 2 人）~~ | 双人局两两更新（legacy）；**多人同局（2026-09 起）经 `GameRecord.ranking` 名次组走 `ratings.apply_ranking`**（线性名次分，n=2 时与双人公式一致，严格零和） |
| 7 | 回放 = moves 逐快照存 board | 回放体积 = 步数 × 棋盘大小；大棋盘游戏注意 gpp 与 JSON 体积 |
| 8 | bot 仅有进程级隔离（非安全沙箱，Docker 池为生产规划） | 裁判持有完整状态，**任何私密信息不得进入对手观测**（如翻牌游戏的牌面只存在于裁判侧） |

初始 rating 1000（`db/models.py` `Bot.rating`）。

## 3. 元玩法（与具体游戏无关的公共规则）

### 3.1 赛制与先手

- 一场 match = 参战 bot 两两循环（C(n,2) 组）× `games_per_pairing` 局；组内**轮换先手**
  （gpp 取偶数 → 先手次数对半），ELO 天然颜色公平，不再做先手分值补偿。
- 开销公式：games = C(n,2) × gpp，子进程生成 = 2 × games（现 runtime 每局新起 2 个进程）。
  4 bot × gpp=4 → 24 局 / 48 进程，可接受；大棋盘重棋类 gpp 建议 ≤ 8。
- `max_bots` 对新游戏一律严格生效（tictactoe 里 `max_bots + 8` 的宽限属历史遗留，不效仿），
  且要求 API 层 `create_match` 硬校验，前端只做提示。

### 3.2 判定词汇表

- `reason`（局级，**固定五值**，各游戏不得自创）：
  `win`（规则达成胜利）/ `draw`（终局平）/ `illegal`（非法动作判负）/
  `timeout`（超步判负）/ `crash`（崩溃判负）。细节信息放 `moves[].detail`（如 "38:26 子数比"）。
- `outcome`（步级，**可扩展**）：基础四值 `ok / illegal / timeout / crash`；游戏可按需追加
  （黑白棋 `pass`、翻牌 `flip`），并随目录下发中文文案（§8）。

### 3.3 ELO 与战绩

- 现状：初始 1000，标准 K=32，逐局更新（胜 1 / 和 0.5 / 负 0）。
- 规划（按优先级）：
  1. **定级曲线**：前 10 局 K=48，11–49 局 K=32，≥50 局 K=16（新 bot 快速归位，尾部收敛防抖）。
  2. **同 owner 对局 K 减半**：抬高互刷成本。零和下"牺牲一个 bot 抬另一个"仍可行，
     减半不能根除，配合榜单公开 owner 即足够透明。
  3. 榜单并列排序显式化：rating 同分 → 胜场多者 → 场次少者 → 先达成者。

### 3.4 随机性与可复现

- 含随机 SETUP 的游戏（翻牌洗牌、随机地形）：裁判统一 `random.Random(seed)`；
  `config["seed"]` 缺省时由裁判生成并**写回 result.config**。
  可复现标准：同 seed + 同 bot 源码 + 同 config ⇒ 逐位重放一致；对局过程中不引入其他随机源。

## 4. 游戏阵容路线图

| 批次 | 游戏 | key | 类型 | 框架改动 | 规格 |
|---|---|---|---|---|---|
| ✅ 已上线 | 井字棋 | `tictactoe` | 轮流落子 | — | 参考实现 |
| ✅ P0 | 四子棋 | `connect4` | 轮流落子（重力） | 无，纯新增 Arena 子类 | §5.1 |
| ✅ P0 | 五子棋 | `gomoku` | 轮流落子 | 无 | §5.2 |
| ✅ P0 | 黑白棋 | `reversi` | 轮流落子 + 自动 pass | 无（outcome 扩一词） | §5.3 |
| ✅ P1 | 光轮 Tron | `tron` | 轮流移动 | 无（outcome="hit" 扩一词） | §6.1 |
| ✅ P1 | 炸弹人 | `bomberman` | 回合制布雷 + 随机 setup | 视图化 board + seed 约定 + FE dict 渲染 | §6.2 |
| ✅ 首例落地 | 多人同局（3–4 人）+ 多人 ELO | 炸弹人先行 | 多方 | `apply_ranking` 名次组 ELO | §6.2 / §7 |
| P2 | 赛季制天梯（定级 / 段位 / 重置） | — | 元玩法 | DB + FE | §7 |
| P2 | 逐围观直播（per-move WS） | — | 呈现 | per-move hook | §7 |

**P0 选择理由**：三款都是"回合落子、board = 全量公开棋盘、动作 = 列号或格下标"的最简形状，
零框架改动即可验证前端"通用渲染 + 目录词条"机制；同时覆盖三种判定形态
（重力落子 / 连线即胜 / 终局计子 + pass），为后续游戏建立规格模板。

## 5. P0 游戏详细规格

公共约定：`(0,0)` 为棋盘**左上**，`index = row * cols + col`；`me` = 1（先手）/ 2（后手），整局固定；
board 为全量公开棋盘列表，0 = 空。

### 5.1 四子棋 connect4

| 项 | 值 |
|---|---|
| 棋盘 | 7 列 × 6 行 = 42 格 |
| 动作 | 列号 0–6；棋子落入该列**最下方空位**（该列行号最大的空格）；列满仍选 = illegal |
| 胜负 | 同色四连（横 / 竖 / 两斜）→ win；42 步满盘无四连 → draw |
| config | `{"games_per_pairing": 4, "move_timeout": 3.0}` |
| bots | min 2 / max 2 |
| 回放 | 每步快照 board（含新子），`move` = 列号；FE 7×6 网格 |

bot 契约（`bot_contract` 全文）：

```
def move(board, me) -> int:
    board: 长度42列表, index = row*7+col, (0,0)左上, 0=空 1/2=双方棋子
    me:    己方棋子(1或2)
    返回:  列号0-6, 棋子落入该列最下方空位; 列满/越界/非int判负
    示例(挑最左未满列):
def move(board, me):
    for col in range(7):
        if board[col] == 0:   # 顶行(第0行)为空 => 该列未满
            return col
    return -1
```

示例 bot（`starter_code`，随机合法列）：

```python
import random

def move(board, me):
    cols = [c for c in range(7) if board[c] == 0]
    return random.choice(cols) if cols else 0
```

裁判要点：合法性 = `0 <= col < 7` 且该列未满；落子后查四连（预生成 69 条四连线表）；
先手优势存在理论必胜但搜索空间大（~4.5 万亿局面），实战有竞技性，无需平衡改造。

### 5.2 五子棋 gomoku

| 项 | 值 |
|---|---|
| 棋盘 | 15 × 15 = 225 格 |
| 动作 | 0–224 落子下标；已占用 = illegal |
| 规则 | **自由规则、无禁手**：任意方向连成 5 子**及以上**即胜（长连亦胜，写入契约避免争议） |
| 胜负 | 连五 → win；满盘 → draw（15×15 实战和棋率极低，无需额外反和机制） |
| config | `{"games_per_pairing": 4, "move_timeout": 5.0}`（搜索型 bot 多给时间；gpp 建议 ≤ 8） |
| bots | min 2 / max 2 |
| 回放 | 每步快照 225 格 board；单局 JSON 约 100–200KB，可接受（约束 #7） |

bot 契约（`bot_contract` 全文）：

```
def move(board, me) -> int:
    board: 长度225列表(15x15), index = row*15+col, 0=空 1/2=棋子
    me:    己方棋子(1=先手黑, 2=后手白)
    规则:  自由规则无禁手, 横/竖/斜连成5子及以上即胜(长连亦胜)
    返回:  0-224 落子下标; 占用/越界/非int判负
```

示例 bot（`starter_code`）：

```python
import random

def move(board, me):
    empties = [i for i, v in enumerate(board) if v == 0]
    return random.choice(empties) if empties else 0
```

### 5.3 黑白棋 reversi

| 项 | 值 |
|---|---|
| 棋盘 | 8 × 8 = 64 格；初始 `(3,3)=2, (3,4)=1, (4,3)=1, (4,4)=2`；1 = 黑 = 先手 |
| 动作 | 0–63，必须是能翻转至少一枚对方棋子的合法点；否则 illegal |
| pass | **由裁判执行**：当前玩家无合法着法 → 记一条 `outcome="pass"` 的步并换手（不会询问该 bot）；双方连续无着 → 终局计子 |
| 胜负 | 子多者 win（`detail` 记 "38:26" 子数比）；平子 draw（罕见） |
| config | `{"games_per_pairing": 4, "move_timeout": 3.0}` |
| bots | min 2 / max 2 |

bot 契约（`bot_contract` 全文）：

```
def move(board, me) -> int:
    board: 长度64列表(8x8), index = row*8+col, 0=空 1=黑(先手) 2=白
    me:    己方棋子(1或2, 整局固定)
    返回:  0-63, 必须是能翻转至少一枚对方棋子的空格; 不合法判负
    说明:  无合法着法时裁判自动pass(不会询问你), 双方均无着法即终局计子
```

示例 bot（`starter_code`，取第一个合法点）：

```python
def move(board, me):
    opp, n = 3 - me, 8
    for idx in range(64):
        if board[idx] != 0:
            continue
        r, c = divmod(idx, n)
        for dr, dc in ((0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)):
            i, j, k = r + dr, c + dc, 0
            while 0 <= i < n and 0 <= j < n and board[i*n+j] == opp:
                i += dr; j += dc; k += 1
            if k and 0 <= i < n and 0 <= j < n and board[i*n+j] == me:
                return idx
    return 0
```

裁判要点：pass 循环 `while` 双方都无着法即终局；每条自动 pass 都落一条 moves
（`{"player": <应行动方>, "board": 快照, "outcome": "pass"}`）保证回放连续可读。

## 6. P1 游戏规格（✅ 已落地）

### 6.1 光轮 Tron（"轮流移动"模板）

- 15 × 15；1 起点左中 `(7,0)`，2 起点右中 `(7,14)`；起点格即为车痕。
- **board 编码（落地时修正）**：`0=空 1/2=车痕 3/4=车头`（3 为 1 号车头）。草案原设计
  "车痕含车头"不可实现——协议不向 bot 传历史，车头必须能从 board 直读，否则 bot 无法定位自己。
- 动作：`0上 1下 2左 3右`；撞墙 / 撞痕 / 出界 → mover 出局（`reason="win"`、`outcome="hit"`、
  `detail="撞墙"`——玩法性出局，非非法动作）；满盘无人出局 → draw。
- config：`{"games_per_pairing": 4, "move_timeout": 2.0}`（gpp clamp ≤ 20）。
- 落地：`app/arenas/tron.py`。确定性基准：首个安全方向 bot 互弈，先手第 59 步
  （58 步移动 + 1 步 hit）撞墙出局，后手胜。

### 6.2 炸弹人（"回合制布雷 + 随机 setup"模板，**2-4 人同局**）

> 设计变更：原 §6.2 翻牌配对（Memory）经评审取消，由炸弹人承接"dict 视图 board +
> 随机 setup + seed 可复现"的模板职责。**多人同局（3-4 人）为本游戏首个落地**

- 13 × 13；边框 + 柱状硬墙（偶行偶列），软墙按 0.45 概率随机填充；出生点按人数：
  2 人 = 对角 `(1,1)/(11,11)`，3 人 = `(1,1)/(1,11)/(11,6)`，4 人 = 四角；出生点及其通路格清空。
- **board = dict 视图**（首次实战约束 #2/#3）：
  `cells`（渲染层：0空地 1硬墙 2软墙 3炸弹 4火焰 5/6/7/8=各玩家，踩弹仍显示玩家码）、
  `players`（各玩家位置下标）、`bombs`（`{cell, fuse, owner}` 结构层——脚下有弹以此为准）。
- 动作：`0上 1下 2左 3右 4原地布雷 5原地不动`；走入火焰 / 被爆炸波及 → 出局
  （多人局死亡即离场、对局继续，`outcome="hit"`）；**格子独占：不可走进任何玩家所在格
  （2-4 人一律适用，违反判非法）**；撞墙 / 撞弹 / 越界 / 违规布雷 → 非法判负。
- 引信每回合（全部存活玩家各行动一次）-1；十字半径爆炸：硬墙截断、软墙炸毁（火舌止于其上）、
  触及他弹连锁引爆；火焰持续到下一次爆炸结算；**终局条件：仅剩 1 人 → 胜；
  全灭 / `max_rounds` 耗尽 → 平**。名次组 = 存活组（并列）+ 死亡组按死亡顺序倒序
  （越早死越差），执行器据此走 `apply_ranking` 多人 ELO（战绩计数：冠军组 win、
  末位组 loss、其余 draw）。
- 赛制：双人局 = pairwise 循环赛（legacy，`games_per_pairing`）；3-4 人局 = 全员同场，
  每局轮换先手，`games` 局数（默认 2，clamp 1-8）。
- seed：`config["seed"]` 缺省生成并写回 `result.config`（§3.4）；逐局派生
  `f"nova-bomber-{seed}-{n}"`，同 seed 全场可复现。
- config 默认：`{"games_per_pairing": 2, "games": 2, "move_timeout": 3.0, "fuse": 3,
  "radius": 2, "max_bombs": 2, "max_rounds": 100, "seed": null}`。
- 落地：`app/arenas/bomberman.py`。确定性基准：双人首个合法行动 bot 互弈（seed=12345）
  100 回合耗尽平局（201 条记录 = 200 行动 + 1 收尾）；`fuse=1` 下"永远布雷"bot
  第 3 条记录被自己的炸弹炸死；**4 人局**同款自爆 bot 首回合末出局（63 条记录），
  存活三人并列冠军组、ELO 严格零和（API 榜单 sum == 4000）。

## 7. P2 方向（立项时再出详细规格）

1. **多人同局 + 多人 ELO**：✅ 机制已由炸弹人首例落地（2-4 人,`apply_ranking` 名次组制,
   约束 #6 已解除）；后续可复用该路径接入新多人玩法（轮流出题抢答、多方圈地等）。
   遗留：多人局的赛季/段位语义与战绩展示细化。
2. **赛季制天梯**：定级赛（新 bot 前 N 场不计正式分）、段位徽章（目录下发段位表，FE 渲染）、
   周期重置（rating 归 1000，历史入档）。
3. **逐围观直播**：执行器 per-move hook → WS `match_move` 事件；ArenaView 直播子页按步推进棋盘
   （现 `match_game_end` 粒度为"局"）。
4. **rating 历史曲线**：bot_rating 流水表 → ELO 榜 sparkline。
5. **Docker 沙箱池**替换 `runtime.py`（接口不变，约束 #8 解除后可承载更高保密要求的玩法）。

## 8. 前端配合改造（ahgs-nova-next）

Arena 基类新增**可选**类属性（缺省回退现状，老游戏零改动）：

```python
board_shape = {"rows": 6, "cols": 7}          # 通用网格渲染
pieces = {"1": "●", "2": "○"}                 # 棋子显示字符
cell_classes = {"4": "flame"}                 # 格子值 → CSS 类(缺省回退内置 1→x/2→o)
player_marks = {"1": "◆", "2": "◆"}          # 玩家编号 → 回放头部标记字符(多人局必需)
labels = {"reason": {...}, "outcome": {...}}  # 中文文案, 覆盖前端内置默认
starter_code = "..."                          # 可运行示例 bot
```

`ArenaRegistry.list()` 原样下发，`ArenaView` 消费：

1. **回放渲染泛化**：`isBoard()` 由 `length === 9` 改为"数组且长度 = rows×cols"；格子高亮
   （`last` / `bad`）与落子交互平移到通用 `.bgrid`（样式在 ArenaView scoped style，井字棋一并
   迁移——其目录声明 3×3 形状，渲染结果不变）；不匹配的 board（dict 等）走现有 JSON 兜底。
2. **文案协商**：`REASON_LABEL` / `OUTCOME_LABEL` 硬编码改为"目录 `labels` 优先，内置默认兜底"
   （黑白棋的 `pass`、翻牌的 `flip` 因此零前端改动可显示）。
3. **示例闭环**：目录卡加「复制示例 Bot」→ 一键填入上传表单（看规则 → 拿样例 → 上传 → 约战）。
4. 约战 / 对局记录 / ELO 榜的交互结构不变。

## 9. 验收与验证

- **后端**：每款游戏 pytest —— 裁判判定（构造必胜序列 / 非法步 / 终局）+ ELO 落库次数断言；
  冒烟：随机合法 bot 自对弈 ≥ 50 场，统计 illegal 率与和棋率（和棋率异常高 → 反和机制复审）。
- **前端**：`npm run build` 过 + mock 数据核对三种渲染分支（网格 / 单局 / JSON 兜底）。
- **上线楔子**：每款新游戏用"首个合法步"bot 与"随机合法步"bot 互弈 gpp=2，人工抽查 1 场回放。

## 10. 实施顺序（文件级）

1. ✅ `app/arenas/connect4.py`、`gomoku.py`、`reversi.py` + `__init__.py` 注册 + `tests/test_arena_games.py`
   （裁判规则单测 + 真子进程约战全流程,gomoku/reversi 用确定性基准断言:先手第 61 步连五、
   终局 19:45 白胜双 pass 收尾）。
2. ✅ `base.py`:可选目录属性默认值 + `apply_score_pair` + `run_round_robin` 公共赛制助手
   （tictactoe 已重构接入,行为不变）；`registry.list()` 下发新字段;
   API `create_match` 硬校验 min/max（tictactoe 原 `max+8` 宽限一并移除,统一严格 2–2）。
3. ✅ FE `ArenaView.vue`:渲染泛化（`.bgrid` 通用网格）+ labels 协商 + 「示例 Bot →」一键填入。
4. ✅ P1:`tron.py` + `bomberman.py` 注册；`cell_classes` 目录字段下发（格子配色协商,
   内置默认 1→x/2→o 兜底）;FE 支持 dict-with-cells 视图的网格渲染与 `hit` 红色徽标;
   翻牌配对（原 §6.2）经评审取消。
5. ✅ 多人同局（2026-09-30）:炸弹人升至 2-4 人（`SPAWNS` 按人数、格码 7/8、`_play_multi`、
   格子独占推广到全部人数）;`ratings.apply_ranking` 名次组 ELO + 执行器 ranking 分支;
   目录新增 `player_marks`,FE 回放头部支持 3/4 号玩家配色。
6. P2 其余项单独立项（§7）。
