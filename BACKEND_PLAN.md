# AHGS Nova Backend · 新后端计划（草案 v0.1）

> 状态：**已开工 —— 实现在 [`ahgs-nova-be/`](ahgs-nova-be/)**（P0/P1/P3 完成,
> P2 部分可用, P4 主体 —— 本地进化引擎已落地;现状与扩展点说明以 `ahgs-nova-be/README.md` 为准）。
>
> **⚠️ 路线变更（2026-09-30）：Proxy+ 模式已废弃并从实现中整体移除。** 后端只以
> standalone 运行(自持数据与执行:本地进化引擎 + 契约裁判 + 种子库 + 榜单 + 对战 Arena),
> 不依赖官方平台。本文 §2 的双模式设计与 §6 的兼容性/迁移策略仅作历史记录保留。
>
> 本文档是 AHGS_NOVA（纯前端仓库）的配套后端设计，
> 目标读者：NOVA 维护者本人 / COOLAS@SEU。
> 依据：对现役 AHGS 平台后端（10.201.186.15:8090，FastAPI + nginx）的长期使用、
> 压测与逆向所得的全部一手经验，见 `../冲榜实验记录.md` 与 `../AHGS-越权访问实验报告.md`。

---

## 1. 为什么需要新后端

NOVA 前端目前完全寄生在官方后端上，以下能力**全部在客户端硬凑**，且受制于官方接口的
结构性缺陷：

| # | 现状痛点（实测） | 对 NOVA / 冲榜工作流的伤害 |
|---|---|---|
| 1 | 进化运行只落**每代最优值 + 最后一 Snapshot**，中间代种群不持久化 | 曲线分析只能看 best；种群明细靠"保存实例"手工触发 |
| 2 | 运行并发硬上限 20，无队列语义，超限直接 400 | 自动冲榜脚本必须自己排批次、自己重试 |
| 3 | LLM 调用 60s 硬超时 + 启动期连通性测试过严（推理模型频繁误判"LLM 调用失败"） | glm-5.3-flash / 4.5-air 在内置路线启动失败；无 thinking 级别控制 |
| 4 | 评估 30s 硬超时，无小样本预筛语义，坏候选全部烧满 30s | LLM 候选存活率曾是 0%；预筛只能在框架代码里自谋出路 |
| 5 | "数据保护中"模式无预告、无白名单、无 API 说明 | wave-14 十轮重试全被拦，自动化完全失明 |
| 6 | 数据集不出服务端（最小包固定 tsp-only，参数被忽略） | 本地验证只能合成数据；真实数据差异导致过 mtsp/orienteering 平台翻车 |
| 7 | 评估器对非法应答的健壮性存疑（parmachine -307.9 疑似被越界索引利用） | 榜单公正性无保障 |
| 8 | 安全欠账：全站 HTTP、JWT 38 天、登录无限速、CORS 反射任意源、`/api/users/{id}` 未鉴权、提交历史列表未鉴权（详见安全报告 §4/§5） | 同网段可批量拖取 PII 与成绩轨迹 |
| 9 | 无种子注入原语、无收割/棘轮概念 | 冲榜工作流（harvest→ratchet）只能用本地脚本+JSON 文件拼 |
| 10 | 无 WebSocket/SSE，进度靠 45s 轮询 status | NOVA 监控页延迟高、请求量大 |
| 11 | 提交语义：运行结束自动提交，无"提交最优"显式端点；同分按提交时间排序 | 并列最优者被迫刷提交时间戳 |
| 12 | 无幂等/重放保护，无结构化错误码（错误靠 detail 字符串） | 自动化只能字符串匹配错误文案 |

**结论**：官方后端是"单机课设级"实现。NOVA 要长大（以及冲榜工作流要工程化），
需要一个自己的后端，而不是继续在前端里堆 workaround。

## 2. 定位与两种运行模式（⚠️ 已废弃:Proxy+ 于 2026-09-30 移除,仅 standalone 保留,见顶部批注）

新后端命名为 **Nova Backend**（仓库建议 `AHGS_NOVA/ahgs-nova-be/`），支持两种模式：

| 模式 | 说明 | 适用 |
|---|---|---|
| **Proxy+ 模式**（先做） | 透明代理官方 API + 在旁路增加新端点（快照存档、冲榜编排、收割库、分析） | 官方平台继续是 source of truth；零迁移成本 |
| **Standalone 模式**（后做） | 自持数据与执行（自己的运行队列、沙箱评估器、LLM 网关、榜单），完整替代官方后端 | 实验室想换新后端时直接切换；NOVA 前端不改 |

关键原则：**对外 HTTP 契约与官方保持兼容**（同路径、同字段、naive UTC、`ascend` 语义），
NOVA 三个版本与现有 grind 工具链（`_launch_runs.py`/`_grind.py`/`grind_desktop.py`）不改动即可工作；
新能力全部走 `/api/v2/*` 版本化端点。

## 3. 总体架构

```
                    ┌──────────────────────────────┐
   NOVA 前端 ──────▶│  nginx / caddy (TLS 终结)     │
   grind 工具链 ────▶└──────────────┬───────────────┘
                                  │
                    ┌─────────────▼────────────────┐
                    │  FastAPI 应用（无状态 API 层） │
                    │  auth / runs / rankings /     │
                    │  snapshots / v2 端点          │
                    └───────┬──────────────┬───────┘
                            │              │
              ┌─────────────▼───┐   ┌──────▼──────────────┐
              │ Postgres        │   │ Redis (队列+缓存)    │
              │ users/runs/     │   │ run queue / pubsub  │
              │ submissions/    │   └──────┬──────────────┘
              │ snapshots/      │          │
              │ datasets meta   │   ┌──────▼──────────────────────┐
              └─────────────────┘   │ Worker 池 (Docker 沙箱×N)    │
                                    │  evolve worker / eval worker │
   对象存储(本地盘/S3) ◀────────────│  LLM Gateway(全提供商)        │
   datasets / frameworks / artifacts└─────────────────────────────┘
```

技术选型（与团队现状匹配，全 Python）：

| 组件 | 选择 | 理由 |
|---|---|---|
| Web 框架 | FastAPI（现役同款） | 团队熟悉；自动 OpenAPI；Pydantic 校验 |
| DB | PostgreSQL 16 + SQLAlchemy 2 | JSONB 存种群/配置；窗口函数算榜单 |
| 队列 | Redis + ARQ（轻量）或 Celery | 替代"并发上限 20"的裸线程；可观测、可重试 |
| 沙箱 | Docker 容器池（每 worker 一个沙箱镜像） | 官方已有沙箱概念；网络/文件系统/超时显式管控 |
| 实时推送 | WebSocket（fallback SSE） | 替代 45s 轮询 |
| 对象存储 | 本地目录起步，接口按 S3 语义抽象 | 数据集/框架/产物统一管理，支持下载 API（官方缺） |
| 部署 | docker compose（单机起步）→ worker 可水平扩 | 实验室一台 GPU 服务器起步足够 |

## 4. 模块设计

### 4.1 认证与安全（把安全报告的欠账一次还清）

- HTTPS 强制（内网自签或校园 CA）；HSTS。
- JWT 有效期 ≤ 2h + refresh token；HttpOnly Cookie 与 Bearer 双支持。
- 登录/注册限速（按账号+IP，5 次失败锁 15 分钟）+ 验证码；注册需邮箱/一卡通校验。
- `GET /api/users/{id}` 与 `/api/users/{id}/submissions` 强制鉴权；
  公开榜单走专门脱敏投影（昵称+分数，不返回一卡通号/role）。
- CORS 白名单（NOVA 部署域 + 官方域），去掉任意反射与 `allow-credentials: true`。
- 安全响应头：CSP、X-Frame-Options、nosniff、Referrer-Policy。
- 账号自助注销；管理员路由显式 `/api/admin/*` + RBAC。

### 4.2 运行编排器（替代"并发 20 + 400"）

- `runs` 状态机：`queued → provisioning → running(gen g/N) → finalizing → completed | failed | canceled`，
  所有转移落库并可查（"数据保护中"这类平台级开关变为显式的 `queue_paused` 状态 + 预告时间）。
- 优先级队列：`user_weight × problem_fairness` 公平调度；单用户并发上限可配置（替代一刀切 20）。
- 失败重试语义显式化（LLM 瞬断 ≠ 框架崩溃），错误结构化：`{code, message, retryable, detail}`。
- WebSocket 推送：每代结束推 `generation_end` 事件（含该代种群全量）。

### 4.3 评估服务（沙箱化 + 预筛内置）

- 每个候选在独立沙箱内评估：CPU/内存/网络限额、30s 超时、确定性随机种子。
- **内置预筛端点**（把冲榜工作流验证过的 `_prescreen` 机制产品化）：合成迷你实例 + SIGALRM，
  崩溃/非法/超时候选在进主评估前淘汰，并返回结构化 `fail_reason`。
- **评估器健壮性**：应答合法性白名单校验（越界机器索引、非法节点 id 一律判 inf 并记审计——
  堵住 parmachine -307 式的语义利用）。
- 每代种群**全量落库**（`snapshot(generation, heuristics[])`），CurveView 直读，不再靠保存实例。

### 4.4 LLM 网关

- 统一适配全部 preset（DeepSeek/OpenAI/Anthropic/Gemini/Qwen/GLM/Kimi/本地 vLLM）。
- **thinking 级别可配置**（`thinking: disabled|low|high` 透传），启动期连通性测试改为
  短超时+一次重试，不再一票否决推理模型。
- 每用户配额与限速、失败自动降级（旗舰→flash→本地）、调用日志与 token 计量落库。
- 平台默认 key 与个人 key 分池管理，保护模式显式化（哪个池被保护、何时恢复）。

### 4.5 冲榜工作流原语（把本地脚本产品化）

- **种子库（Seed Bank）**：`seeds(problem_key, algorithm, concept, objective, source)` 表；
  上传框架时可指定种子注入（官方只认 framework.py 的现状保留，但平台原生支持 seed 参数）。
- **收割 API**：`POST /api/v2/harvest {run_id}` → 方向感知地比较并入库（棘轮存档的守护逻辑内置）。
- **棘轮 API**：`POST /api/v2/run {problem, seed_id, template, gens, model}` 一键以某种子起步；
  批量编排端点替代 `_grind.py` 的分批/重试逻辑。
- **A/B 框架**：`POST /api/v2/abtest {problem, seeds, templates}` → 并行两组+自动对比报告
  （复刻 wave-13 的 A/B 实验）。

### 4.6 数据集注册中心

- 题目数据集入库对象存储，带版本号与校验和；`GET /api/v2/problems/{key}/datasets` 可下载
  （或按角色控制：仅训练用途 token 可拉取）。
- 最小运行实例包按题目动态生成（官方固定 tsp-only 的补全）。

### 4.7 对战小游戏扩展（v0.1 之后新增需求）

- 题目类型注册表:`problems.kind` 区分 `optimization` / `game`(可继续注册新类型),
  编排器按 kind 白名单校验运行负载,榜单语义分道(objective 榜 vs ELO 榜)。
- Arena 插件协议:实现 `run_match(bots, config)` 即接入一款对战游戏;
  bot 源码在独立子进程按步 JSON 问答(超时/崩溃/非法步判负),生产换 Docker 沙箱池。
- `/api/v2/arena/*`:游戏目录 / bot 上传 / 约战(复用 runs 队列)/ 对局记录 / ELO 榜。
- 参考实现 tictactoe 闭环;外部游戏经 `NOVA_ARENA_PLUGINS` 热加载,零改动接入。

## 5. 数据模型（核心表）

```
users(id, username, display_name, role, password_hash, quota, ...)
problems(key, name, ascend, contract jsonb, dataset_version, ...)
runs(id, user_id, problem_key, framework_id, seed_id, status, config jsonb,
     num_generations, started_at, finished_at, error_code)
generations(run_id, generation, started_at, best_objective,
            snapshot jsonb)                      -- 全量种群
submissions(id, user_id, problem_key, run_id, objective, created_at, is_official)
seeds(id, problem_key, algorithm, concept, objective, source, created_at)
abtests(id, problem_key, arm_a, arm_b, result jsonb)
llm_calls(id, run_id, provider, model, tokens, latency_ms, ok, error_code)
audit_log(id, actor, action, target, created_at)
```

榜单视图用 SQL 窗口函数实时算（`rank() over (partition by problem order by best asc/desc)`），
同分排序规则显式化（先到先得 + `tie_break_policy` 可配置）。

## 6. 兼容性与迁移

- **Proxy+ 模式不需要任何迁移**：新端点挂在 `/api/v2`，老路径原样转发。
- Standalone 切换时提供一次性导入脚本：从官方库导出 users/problems/runs/submissions/ranking
  （官方接口可读出的全部数据）。
- NOVA 前端只需要把 `nova_api_base` 指向新后端；`parseServerTime()`（naive UTC）契约继续遵守。
- 官方平台数据保护/维护窗口期间，Proxy+ 模式的旁路功能（历史快照、分析、收割库）照常可用。

## 7. 里程碑

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P0（1 周） | FastAPI 骨架 + 透明代理 + TLS + 登录限速 | NOVA 指向新后端全功能可用 |
| P1（2 周） | Postgres 数据模型 + 运行队列（ARQ）+ WebSocket 进度 + 每代全量快照 | 一次 10 代运行全程无轮询、CurveView 直读种群 |
| P2（2 周） | 沙箱评估池 + 预筛端点 + LLM 网关（thinking/降级/配额） | LLM 候选存活率 ≥80%；glm-5.3 可正常启动 |
| P3（1 周） | Seed Bank / harvest / ratchet / A/B 端点 | `_grind.py` 全部逻辑迁入 API，本地脚本退役 |
| P4（按需） | Standalone 模式：自有榜单+提交语义（显式"提交最优"端点、同分策略可配） | 脱离官方后端独立举办一场内测赛 |

## 8. 风险与开放问题

1. **官方平台的地位**：Proxy+ 模式下官方仍是权威；若实验室决定整体替换官方后端，
   需要数据迁移授权与停机窗口（P4 的前置条件）。
2. **沙箱逃逸面**：自建评估沙箱要按安全报告 §6 的清单自查（env、挂载、网络、RPC 面）。
3. **LLM 成本**：网关的配额与降级策略需要实验室确认各池预算。
4. **评估器语义统一**：parmachine 类"越界应答"必须在 Spec 里写死为非法（audit + inf），
   否则榜单公信力问题会在新后端复现。
5. **人力**：当前只有一名维护者，P0-P3 串行约 6 周；建议 P0/P1 优先（对 NOVA 体验提升最直接）。

---

*本文档基于 2026-09-28/29 的实测证据写成；后续修订请同步 `../冲榜实验记录.md` 的新发现。*
