# Nova Backend(ahgs-nova-be · 自建后端)

依据 [`../BACKEND_PLAN.md`](../BACKEND_PLAN.md) 实现的**独立后端**:自持数据与执行,
默认即 standalone 模式 —— 本地进化引擎(LLM 变异→预筛→评测→选择)、榜单、种子库、对战 Arena
全部自持,不依赖官方平台(官方端口不稳定也不影响)。
对 NOVA 前端零改动可用(官方契约同形:同路径、同字段、naive UTC、`ascend` 语义)。

当前实现状态对照计划里程碑:

| 里程碑 | 状态 | 说明 |
|---|---|---|
| P0 骨架 + 透明代理 + 认证加固 | ✅ | FastAPI 工厂 / 透明转发 / JWT 2h+refresh / 登录限速锁定 / 安全响应头 / CORS 白名单 / 用户详情代理侧强制鉴权 |
| P1 数据模型 + 运行队列 + WS + 全量快照 | ✅ | SQLAlchemy 2 异步(SQLite 开发 / Postgres 生产)/ 优先级队列 + 状态机 / WebSocket 每代推送 / 每代种群全量落库 |
| P2 评估预筛 + LLM 网关 | ⚙️ 部分 | 结构化 fail_reason 预筛端点已可用;LLM 网关(openai_compat+mock、thinking 透传、降级链、调用计量)已可用;Docker 沙箱池与各题流式评估适配器待接 |
| P3 冲榜工作流原语 | ✅ | Seed Bank / 方向感知收割(棘轮守护内置)/ `/api/v2/grind` 批量棘轮 / `/api/v2/abtest` 自动判优;`_grind.py` 逻辑全部迁入 API |
| P4 Standalone 完整替代 | ⚙️ 主体 | 兼容层核心集已通;**本地进化引擎 `evolve_llm` 已落地**(契约自带 judge,LLM 变异+预筛+评测+选择,产物与收割/棘轮直通);custom-problems 长尾端点待补 |

**超出计划的扩展**(为对战小游戏玩法预留,见下文"Arena 扩展点"):
题目类型注册表(`optimization`/`game` 双类型已内置)、统一运行负载抽象(执行器插件)、
Arena 协议 + bot 子进程运行时 + ELO 榜,内置六款对战游戏
(井字棋 / 四子棋 / 五子棋 / 黑白棋 / 光轮 Tron / 炸弹人,规格见仓库根 `ARENA_GAMES.md`),
`/api/v2/arena/*` 全套端点可用。

## 快速开始

```bash
cd ahgs-nova-be
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Linux/macOS: .venv/bin/pip

cp .env.example .env                          # 至少改 NOVA_JWT_SECRET
python scripts/seed_demo.py                   # 管理员 + 21 题 + 示例 bot
python serve.py --port 8000                  # http://127.0.0.1:8000/docs
#(serve.py 自动落到 .venv,任意 Python 可跑;也可激活 venv 后用 uvicorn app.main:app)
```

测试(47 项,含真实子进程对弈、透明代理、限速锁定):

```bash
.venv/Scripts/python -m pytest tests/ -q
```

Docker(单机起步):

```bash
NOVA_ADMIN_PASSWORD=... docker compose up -d --build
```

## 运行模式(单一)

后端只以 standalone 运行:官方兼容层与 `/api/v2/*` 挂载于同一应用、同一 JWT 签名密钥
—— NOVA 把 `nova_api_base` 指向本后端,登录一次即通吃,前端无双会话问题。

**官方接口覆盖(2026-09-30 起:100%)**:auth(login/register/me/me/password)、
problems(list/detail)、ranking(key/me)、submissions(recent/my/id/record)、
users(id/submissions)、evolution(start/my/status/results/population/prompt/stop/submit)、
instances、developer(validate/upload/run)、custom-problems(list/upload/get/delete +
agent plan/execute/runs)、llm-presets(网关降级链生成)。
说明:custom-problems 的 Agent 建题为 LLM 生成裁判+实例(经编译与违规冒烟校验);
数据集构建脚本(dataset_builder)仅存档,执行属 Standalone 深水区,按需再启。

## API 速览

兼容层(standalone)之外,新能力全部在 `/api/v2`:

| 端点 | 用途 |
|---|---|
| `POST /api/v2/run` | 统一运行入口(kind=evolve_official/evolve_local;template+seed_id 服务端渲染框架) |
| `GET /api/v2/runs/{id}` / `.../generations` | 运行详情 / 每代全量种群(CurveView 直读) |
| `POST /api/v2/runs/{id}/cancel` | 取消(协作式;官方执行器会同步停上游) |
| `POST /api/v2/harvest/{run_id}` | 方向感知收割,劣于档案直接拒绝(`force` 可越过) |
| `POST /api/v2/grind` | 批量棘轮:分批并发 + 每批自动收割 + 总报告 |
| `POST /api/v2/abtest` | A/B 对照:并行双臂 + ascend 方向自动判优 |
| `POST /api/v2/prescreen` | 预筛:迷你实例 + 子进程限时,结构化 fail_reason |
| `/api/v2/seeds`、`/api/v2/problems/{key}/datasets` | 种子库 / 数据集注册中心(版本+校验和+下载) |
| `WS /api/v2/ws/runs/{run_id}?token=` | 实时事件:`generation_end`(含全量种群)/ 状态转移 |
| `/api/v2/arena/*` | 对战玩法:游戏目录 / bot 上传 / 约战 / 对局记录 / ELO 榜 |
| `/api/v2/admin/*` | 队列暂停(显式"数据保护中")/ 题目注册 / 审计日志 / LLM 运营 |

错误统一信封 `{"code", "message", "retryable", "detail"}`;自动化按 `code` 分派,
不再做 detail 字符串匹配。

## 本地进化引擎(kind=evolve_llm)

standalone 模式的核心:不依赖官方平台跑真进化。题目在注册时于 `contract.evaluate`
内自带**可信裁判**,引擎负责其余全部环节:

```jsonc
// PUT /api/v2/admin/problems/<key> 的 contract 字段
{
  "description": "0-1 背包",
  "evaluate": {
    "entry": "solve",                          // 候选必须实现的入口
    "entry_doc": "def solve(instance, config) -> list[int]",
    "instance": {"items": [[5,10],[4,40]], "capacity": 10},
    "prescreen_instance": {"items": [[5,10]], "capacity": 10},  // 可选迷你实例
    "judge": "def judge(instance, solution, config):
    ...", // 可信裁判源码
    "judge_entry": "judge", "timeout": 10
  }
}
```

启动运行(`POST /api/v2/run`,契约带 evaluate 时 kind 省略即自动选 `evolve_llm`):

```jsonc
{"problem_key": "knap", "config": {
  "num_generations": 5, "population_size": 6, "candidates_per_gen": 3,
  "seed_code": "def solve(instance, config): ...",   // 可选,或 seed_id 引种子库
  "llm_model": "glm-4.6", "llm_thinking": "default"  // 网关降级链里的适配器与模型
}}
```

**21/21 题契约就绪**(2026-09-30):全部题目的判定程序已内建
(`app/contracts/`),`python scripts/seed_problems.py` 一键注册;
每题配确定性合成实例(全量+预筛迷你版),候选违规/异常一律 10⁹ 罚值。
qwen3 系的"越界机器索引"类语义漏洞在 parmachine 裁判中显式堵死。

**接本地 Ollama(免费)**:`.env` 两行即可,适配器直连(不走系统代理):

```
NOVA_LLM_PLATFORM_KEYS={"ollama":{"base_url":"http://127.0.0.1:11434/v1","api_key":"ollama"}}
NOVA_LLM_FALLBACK_CHAIN=ollama:gemma3:1b
```

**模型实测(Ollama 0.34,纯 CPU)**:推荐 **gemma3:1b** —— 16 秒出可解析候选,
端到端一轮进化 30 秒(2026-09-30 实测:候选通过预筛+裁判全流程)。
**不推荐 qwen3:4b**:其思考过程无法经 Ollama 0.34 的 OpenAI 兼容层关闭
(`/no_think` 软开关与 `think:false` 均被无视,输出全部进入 `reasoning` 字段,
`content` 恒为空,3072 token 预算内写不完一次回答);适配器已兼容回退到
`reasoning` 字段提取,但预算消耗使得它在本机不可用。跑 qwen3 系建议走云端 API
(降级链前置)或带 think 开关的部署。其他旋钮(运行 config):`llm_max_tokens`、
`llm_timeout`、`llm_repair_attempts`(解析失败修复回路,默认 1)、`llm_prompt_suffix`。

每代流程:精英选择 → LLM 变异(`candidates_per_gen` 次,经网关降级链,计量入
`llm_calls`)→ 迷你实例预筛秒杀坏候选 → 全量评测(候选与裁判同子进程,超时整杀)
→ 方向感知截断 + 目标值去重 → `generation_end` 全量种群推送。失败反馈自动喂回下一代
提示词。结束时产出与官方 results 同构的 `best_heuristic`,`POST /api/v2/harvest/{run_id}`
直接收割入种子库(棘轮闭环)。真 LLM 在 `.env` 配置 `NOVA_LLM_PLATFORM_KEYS` 后即用。

## 扩展性设计(四种插件点)

1. **题目类型注册表**(`app/services/registry.py`):`problems.kind` 决定该类题目允许的
   运行负载与榜单语义。内置 `optimization`(objective 榜单)与 `game`(ELO 榜)。
   入队时编排器强制校验,game 类题目无法误入进化队列。
2. **运行执行器**(`app/services/executors/`):`runs.kind` 分派执行器,编排器只管
   queued→running→终态的生命周期。内置:official(驱动官方平台全过程并镜像落库)、
   mock(无上游联调)、grind(批量棘轮)、abtest、arena_match。新增负载 = 新文件 + 一行注册。
3. **Arena 对战插件**(`app/arenas/`):实现 `Arena` 协议(`key`/`bot_contract`/`run_match`)
   即接入一款新游戏;bot 在独立子进程按步 JSON 问答(超时/崩溃/非法步判负),生产可整体
   换 Docker 沙箱实现而不动协议。外部游戏走 `NOVA_ARENA_PLUGINS=mypkg.mygame:MyGameArena`
   热加载,API/榜单/执行器零改动。内置:tictactoe(参考实现)、connect4、gomoku、reversi、
   tron、bomberman(2-4 人同局)
   (规格与新增指引见仓库根 `ARENA_GAMES.md`;双人赛制走 `Arena.run_round_robin`,
   多人局经 `GameRecord.ranking` 走 `ratings.apply_ranking` 名次组 ELO;
   目录可选下发 `board_shape`/`pieces`/`cell_classes`/`player_marks`/`labels`/`starter_code`
   供前端渲染协商)。
4. **基础设施接口**(`app/services/queue.py`、`app/services/storage.py`、LLM 适配器):
   队列(现为进程内优先级队列,可换 ARQ/Redis)、存储(本地目录,按 S3 语义抽象)、
   LLM 提供商(OpenAI 兼容适配覆盖 GLM/DeepSeek/Qwen/Kimi/vLLM;注册新适配器即可)。

> 部署提示:进程内队列的 worker 数(`n_workers`)应大于 grind 批大小,否则批量子运行
> 需排队等待(不会死锁,但会变慢)。换 ARQ 后此限制消失。

## 前端接入

兼容层登录(`/api/auth/login`)签发的 JWT 与 `/api/v2` 同密钥同源,一个会话通吃;
NOVA 无需任何改动即可使用全部 v2 能力。`parseServerTime()` 的 naive UTC 契约继续遵守。
## 安全清单落实(对照安全报告 §4/§5)

HTTPS(部署层 compose 预留 caddy)、JWT 2h+刷新轮换、PBKDF2 密码哈希、登录/注册限速锁定、
CORS 白名单且不带凭证、CSP/nosniff/DENY/no-referrer 响应头、用户详情与提交轨迹强制鉴权、
榜单脱敏投影、敏感参数(llm key)不落库用后即弃、管理动作与收割全量审计。
