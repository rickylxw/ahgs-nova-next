<script setup>
/* ============ AHGS NOVA Next · 管理端(v2 admin) ============
 * ① 健康总览 + 队列暂停/恢复(显式"数据保护中")② 题目注册(putProblem)
 * ③ 审计日志 ④ LLM 运营(providers/测试对话/调用记录)+ 对战插件重载。
 * 路由守卫已拦非 admin,此处仅兜底展示空态。
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import * as nova from "../api/nova";
import { useSessionStore } from "../stores/session";
import { useProblemsStore } from "../stores/problems";
import { toast } from "../stores/ui";
import { fmtTime, parseServerTime } from "../lib/format";
import CodeBlock from "../components/CodeBlock.vue";
import EmptyState from "../components/EmptyState.vue";

const session = useSessionStore();
const problems = useProblemsStore();

function errText(e) {
    if (!e) return "";
    if (typeof e === "string") return e;
    if (e.code === "AUTH_FORBIDDEN") return "需要管理员账号";
    return e.message || "请求失败";
}

/** naive UTC ISO → 本地可读时间(绝不 new Date(iso)) */
function fmtResume(iso) {
    const d = parseServerTime(iso);
    if (!d) return iso || "待定";
    return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** datetime-local(本地时区)→ naive UTC 字符串,与服务器 naive UTC 契约对齐 */
function localToUtcNaive(v) {
    if (!v) return "";
    const d = new Date(v);
    return isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 19);
}

/** naive UTC ISO → datetime-local 本地值(回填表单用) */
function utcNaiveToLocalInput(iso) {
    const d = parseServerTime(iso);
    if (!d) return "";
    const pad = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function trunc(s, n = 80) {
    const t = String(s ?? "");
    return t.length > n ? t.slice(0, n) + "…" : t;
}

/* ============ ① 健康 / 队列 ============ */
const health = ref(null);
const healthErr = ref(null);
const healthLoading = ref(false);

async function loadHealth() {
    healthLoading.value = true;
    try {
        health.value = await nova.health();
        healthErr.value = null;
        syncPauseForm();
    } catch (e) {
        healthErr.value = errText(e);
    } finally {
        healthLoading.value = false;
    }
}

const q = computed(() => health.value?.queue || null);
const isPaused = computed(() => !!q.value?.paused);

/* ---- 队列暂停/恢复操作 ---- */
const pPaused = ref(false);
const pReason = ref("");
const pResume = ref(""); // datetime-local,可留空
const pErr = ref(null);
const pBusy = ref(false);
let pauseFormSynced = false;

/** 首次拿到 health 后用当前队列状态初始化表单(此后不覆盖用户输入) */
function syncPauseForm() {
    if (pauseFormSynced || !q.value) return;
    pPaused.value = !!q.value.paused;
    pReason.value = q.value.reason || "";
    pResume.value = utcNaiveToLocalInput(q.value.resume_at);
    pauseFormSynced = true;
}

async function submitPause() {
    pErr.value = null;
    pBusy.value = true;
    try {
        const r = await nova.setQueuePaused({
            paused: pPaused.value,
            reason: pReason.value.trim(),
            resume_at: localToUtcNaive(pResume.value),
        });
        toast(r.paused ? "队列已暂停(数据保护中)" : "队列已恢复", "ok");
        pauseFormSynced = false;
        await loadHealth();
    } catch (e) {
        pErr.value = errText(e);
    } finally {
        pBusy.value = false;
    }
}

/* ============ ② 题目注册 ============ */
const prKey = ref("");
const prName = ref("");
const prKind = ref("optimization");
const prAscend = ref(true);
const prContract = ref("{}");
const prDataset = ref("");
const prErr = ref(null);
const prBusy = ref(false);
const knownKeys = computed(() => problems.list.map((p) => p.key));

async function submitProblem() {
    prErr.value = null;
    const key = prKey.value.trim();
    if (!key) { prErr.value = "请填写题目 key"; return; }
    let contract = {};
    if (prContract.value.trim()) {
        try {
            contract = JSON.parse(prContract.value);
        } catch {
            prErr.value = "contract JSON 解析失败,请检查语法";
            return;
        }
        if (!contract || typeof contract !== "object" || Array.isArray(contract)) {
            prErr.value = "contract 需为 JSON 对象";
            return;
        }
    }
    const body = {
        name: prName.value.trim() || key,
        kind: prKind.value,
        ascend: prAscend.value,
        contract,
    };
    if (prDataset.value.trim()) body.dataset_version = prDataset.value.trim();
    prBusy.value = true;
    try {
        const r = await nova.putProblem(key, body);
        toast(`题目「${r.key}」已注册(${r.kind},${r.ascend ? "越低越好" : "越高越好"})`, "ok");
        problems.load(true).catch(() => { /* 刷新注册表缓存,失败不阻塞 */ });
    } catch (e) {
        prErr.value = errText(e);
    } finally {
        prBusy.value = false;
    }
}

/* ============ ③ 审计日志 ============ */
const audit = ref([]);
const auditLoading = ref(false);
const auditErr = ref(null);

async function loadAudit() {
    auditLoading.value = true;
    auditErr.value = null;
    try {
        const r = await nova.auditLog(200);
        audit.value = r.audit ?? [];
    } catch (e) {
        auditErr.value = errText(e);
    } finally {
        auditLoading.value = false;
    }
}

function auditDetailText(a) {
    if (a.detail == null) return "—";
    return typeof a.detail === "string" ? a.detail : JSON.stringify(a.detail);
}

/* ============ ④ LLM 运营 ============ */
const providers = ref([]);
const fallbackChain = ref([]);
const calls = ref([]);
const llmLoading = ref(false);
const llmErr = ref(null);

async function loadLlm() {
    llmLoading.value = true;
    llmErr.value = null;
    try {
        const [pr, cl] = await Promise.all([nova.llmProviders(), nova.llmCalls(50)]);
        providers.value = pr.providers ?? [];
        fallbackChain.value = pr.fallback_chain ?? [];
        calls.value = cl.calls ?? [];
    } catch (e) {
        llmErr.value = errText(e);
    } finally {
        llmLoading.value = false;
    }
}

/* ---- 测试对话 ---- */
const chatProvider = ref("");
const chatModel = ref("");
const chatPrompt = ref("");
const chatErr = ref(null);
const chatBusy = ref(false);
const chatResult = ref(null); // {text, prompt_tokens, completion_tokens, latency_ms, provider, model}

async function submitChat() {
    chatErr.value = null;
    chatResult.value = null;
    if (!chatPrompt.value.trim()) { chatErr.value = "请填写测试 prompt"; return; }
    const body = { messages: [{ role: "user", content: chatPrompt.value }] };
    if (chatModel.value.trim()) body.model = chatModel.value.trim();
    if (chatProvider.value.trim()) body.provider = chatProvider.value.trim();
    chatBusy.value = true;
    try {
        chatResult.value = await nova.llmChat(body);
        toast("测试对话成功", "ok");
        loadLlm(); // 刷新调用记录
    } catch (e) {
        chatErr.value = errText(e);
    } finally {
        chatBusy.value = false;
    }
}

/* ============ 对战插件重载 ============ */
const reloadBusy = ref(false);

async function doReloadPlugins() {
    reloadBusy.value = true;
    try {
        const r = await nova.reloadArenaPlugins();
        const names = (r.arenas ?? []).map((a) => a.display_name).join("、") || "无";
        toast(`插件重载完成:成功加载 ${(r.loaded ?? []).length} 个;当前游戏:${names}`, "ok");
        loadAudit();
    } catch (e) {
        toast(errText(e), "err");
    } finally {
        reloadBusy.value = false;
    }
}

/* ============ 初始化 ============ */
let healthTimer = null;

onMounted(() => {
    if (!session.isAdmin) return; // 兜底空态,不发起管理端请求
    loadHealth();
    loadAudit();
    loadLlm();
    problems.load().catch(() => { /* App 启动已加载 */ });
    healthTimer = setInterval(() => {
        if (!healthLoading.value) loadHealth();
    }, 15000);
});

onUnmounted(() => {
    if (healthTimer) clearInterval(healthTimer);
    healthTimer = null;
});
</script>

<template>
    <div>
        <h1 class="page-title">管理端 <span class="hint">队列 / 题目注册中心 / 审计 / LLM 运营</span></h1>

        <!-- 非 admin 兜底(路由守卫已拦) -->
        <EmptyState v-if="!session.isAdmin" icon="🔒" desc="需要管理员账号" />

        <template v-else>
            <!-- ============ ① 健康总览 ============ -->
            <div class="card">
                <h2>服务健康 <span class="tail">15 秒自动刷新</span></h2>
                <div class="error-banner" v-if="healthErr">健康检查失败:{{ healthErr }}</div>
                <div class="loading-row" v-if="!health && !healthErr"><span class="spinner"></span>加载健康状态…</div>
                <template v-if="health">
                    <div class="grid cols-4">
                        <div class="stat"><div class="k">运行模式</div><div class="v">{{ health.mode || "—" }}</div><div class="s">v{{ health.version || "?" }} · {{ health.service }}</div></div>
                        <div class="stat"><div class="k">队列深度</div><div class="v">{{ q?.depth ?? "—" }}</div><div class="s">排队等待的运行</div></div>
                        <div class="stat"><div class="k">活跃运行</div><div class="v">{{ health.runs_active ?? "—" }}</div><div class="s">正在执行</div></div>
                        <div class="stat"><div class="k">队列状态</div><div class="v queue-state">
                            <span class="badge" :class="isPaused ? 'evo-st-pending' : 'evo-st-running'">{{ isPaused ? "暂停中" : "正常" }}</span>
                        </div><div class="s" v-if="isPaused">{{ q?.reason || "数据保护中" }} · 预计 {{ fmtResume(q?.resume_at) }} 恢复</div></div>
                    </div>
                </template>
            </div>

            <!-- ============ 队列暂停 / 恢复 ============ -->
            <div class="card" :class="{ 'pause-on': isPaused }">
                <h2>队列暂停 / 恢复 <span class="tail">POST /api/v2/admin/queue/pause</span></h2>
                <p class="section-note">暂停后新运行不再入队,前端各处展示"数据保护中"横幅;恢复请给出原因与预告时间。</p>
                <form @submit.prevent="submitPause">
                    <div class="grid-2">
                        <div class="field">
                            <label>目标状态</label>
                            <select v-model="pPaused">
                                <option :value="false">正常运行(恢复入队)</option>
                                <option :value="true">暂停入队(数据保护中)</option>
                            </select>
                        </div>
                        <div class="field">
                            <label>暂停原因(公开展示)</label>
                            <input v-model="pReason" placeholder="如:数据集迁移,10:00 恢复" />
                        </div>
                        <div class="field">
                            <label>预计恢复时间(可留空)</label>
                            <input type="datetime-local" v-model="pResume" />
                        </div>
                    </div>
                    <div class="error-banner" v-if="pErr">{{ pErr }}</div>
                    <button class="btn primary" type="submit" :disabled="pBusy">{{ pBusy ? "提交中…" : pPaused ? "暂停队列" : "恢复队列" }}</button>
                </form>
            </div>

            <!-- ============ ② 题目注册 ============ -->
            <div class="card">
                <h2>题目注册 <span class="tail">PUT /api/v2/admin/problems/{key}</span></h2>
                <form @submit.prevent="submitProblem">
                    <div class="grid-2">
                        <div class="field">
                            <label>题目 key(可下拉选已有,或直接输入新 key)</label>
                            <input v-model="prKey" list="problem-keys" placeholder="如 tsp_2opt" />
                            <datalist id="problem-keys">
                                <option v-for="k in knownKeys" :key="k" :value="k"></option>
                            </datalist>
                        </div>
                        <div class="field">
                            <label>名称(name,留空用 key)</label>
                            <input v-model="prName" placeholder="如 TSP 旅行商问题" />
                        </div>
                        <div class="field">
                            <label>类型(kind)</label>
                            <select v-model="prKind">
                                <option value="optimization">optimization(优化)</option>
                                <option value="game">game(对战)</option>
                            </select>
                        </div>
                        <div class="field">
                            <label>数据集版本(dataset_version,可留空)</label>
                            <input v-model="prDataset" placeholder="如 v3" />
                        </div>
                    </div>
                    <label class="check-row"><input type="checkbox" v-model="prAscend" />ascend(勾选 = 目标越低越好)</label>
                    <div class="field">
                        <label>contract JSON(评估器/负载约定;留空则不改动)</label>
                        <textarea class="input mono" v-model="prContract" rows="5" spellcheck="false" placeholder='{ "entry": "evaluate", "objective": "distance", "evolve_defaults": { "population_size": 10, "num_generations": 15 } }'></textarea>
                        <p class="hint">契约里的 <span class="mono">evolve_defaults</span> 是该题的默认进化参数(种群容量/进化代数/突变数/杂交数/反思数/策略更新数),进化页选中该题时自动预填。</p>
                    </div>
                    <div class="error-banner" v-if="prErr">{{ prErr }}</div>
                    <button class="btn primary" type="submit" :disabled="prBusy">{{ prBusy ? "提交中…" : "注册 / 更新题目" }}</button>
                </form>
            </div>

            <!-- ============ ③ 审计日志 ============ -->
            <div class="card">
                <h2>审计日志 <span class="tail">最近 {{ audit.length }} 条</span></h2>
                <div class="error-banner" v-if="auditErr">{{ auditErr }}</div>
                <div class="loading-row" v-if="auditLoading && !audit.length"><span class="spinner"></span>加载审计日志…</div>
                <div class="table-wrap" v-if="audit.length">
                    <table>
                        <thead>
                            <tr>
                                <th>时间</th>
                                <th>操作者</th>
                                <th>动作</th>
                                <th>对象</th>
                                <th>详情</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="a in audit" :key="a.id">
                                <td class="small">{{ fmtTime(a.created_at) }}</td>
                                <td>{{ a.actor || "—" }}</td>
                                <td><span class="badge feature-badge mono">{{ a.action }}</span></td>
                                <td class="mono small" :title="a.target || ''">{{ trunc(a.target, 40) }}</td>
                                <td class="small detail-td" :title="auditDetailText(a)">{{ trunc(auditDetailText(a)) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <EmptyState v-else-if="!auditLoading && !auditErr" icon="📜" desc="暂无审计记录" />
            </div>

            <!-- ============ ④ LLM 运营 ============ -->
            <div class="card">
                <h2>LLM 网关 <span class="tail">{{ providers.length }} 个提供商</span></h2>
                <div class="error-banner" v-if="llmErr">{{ llmErr }}</div>
                <div class="loading-row" v-if="llmLoading && !providers.length && !calls.length"><span class="spinner"></span>加载 LLM 运营数据…</div>
                <template v-if="providers.length">
                    <div class="kv"><span class="k">已注册提供商</span><span class="badge-row">
                        <span class="badge src-local mono" v-for="p in providers" :key="p.name">{{ p.name }}<span class="small dim">({{ p.class }})</span></span>
                    </span></div>
                    <div class="kv"><span class="k">降级链</span><span class="badge-row">
                        <span class="badge feature-badge mono" v-for="(f, i) in fallbackChain" :key="i">{{ i + 1 }}. {{ f }}</span>
                        <span class="hint" v-if="!fallbackChain.length">未配置</span>
                    </span></div>
                </template>

                <!-- 测试对话 -->
                <div class="chat-block">
                    <h3>测试对话 <span class="hint">网关自测调用,计入 llm_calls 计量</span></h3>
                    <div class="grid-2">
                        <div class="field">
                            <label>provider(留空走默认降级链)</label>
                            <input v-model="chatProvider" placeholder="如 mock / openai_compat" />
                        </div>
                        <div class="field">
                            <label>model(留空用 mock)</label>
                            <input v-model="chatModel" placeholder="如 glm-4.5-air" />
                        </div>
                    </div>
                    <div class="field">
                        <label>Prompt(user 消息)</label>
                        <textarea class="input mono" v-model="chatPrompt" rows="3" spellcheck="false" placeholder="你好,请自我介绍一句话"></textarea>
                    </div>
                    <div class="error-banner" v-if="chatErr">{{ chatErr }}</div>
                    <button class="btn primary" type="button" :disabled="chatBusy" @click="submitChat">{{ chatBusy ? "调用中…" : "发送测试对话" }}</button>

                    <div class="chat-result" v-if="chatResult">
                        <div class="kv"><span class="k">实际提供商 / 模型</span><span class="mono">{{ chatResult.provider }} : {{ chatResult.model }}</span></div>
                        <div class="kv"><span class="k">计量</span><span class="mono">输入 {{ chatResult.prompt_tokens }} tok · 输出 {{ chatResult.completion_tokens }} tok · 延迟 {{ chatResult.latency_ms }} ms</span></div>
                        <CodeBlock :code="chatResult.text || '(空响应)'" />
                    </div>
                </div>

                <!-- 调用记录 -->
                <h3>调用记录 <span class="hint">最近 {{ calls.length }} 条</span></h3>
                <div class="table-wrap" v-if="calls.length">
                    <table>
                        <thead>
                            <tr>
                                <th>时间</th>
                                <th>提供商</th>
                                <th>模型</th>
                                <th class="num">输入 tok</th>
                                <th class="num">输出 tok</th>
                                <th class="num">延迟</th>
                                <th>结果</th>
                                <th>运行</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="c in calls" :key="c.id">
                                <td class="small">{{ fmtTime(c.created_at) }}</td>
                                <td class="mono small">{{ c.provider }}</td>
                                <td class="mono small">{{ c.model }}</td>
                                <td class="num mono">{{ c.prompt_tokens ?? "—" }}</td>
                                <td class="num mono">{{ c.completion_tokens ?? "—" }}</td>
                                <td class="num mono">{{ c.latency_ms != null ? c.latency_ms + " ms" : "—" }}</td>
                                <td>
                                    <span class="badge" :class="c.ok ? 'evo-st-running' : 'evo-st-failed'">{{ c.ok ? "成功" : "失败" }}</span>
                                    <span class="small dim mono" v-if="c.error_code"> {{ c.error_code }}</span>
                                </td>
                                <td class="mono small">{{ c.run_id != null ? "#" + c.run_id : "—" }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <EmptyState v-else-if="!llmLoading && !llmErr" icon="💬" desc="暂无 LLM 调用记录" />
            </div>

            <!-- 对战插件重载 -->
            <div class="card">
                <h2>对战插件 <span class="tail">NOVA_ARENA_PLUGINS 环境变量指定的外部游戏</span></h2>
                <p class="section-note">修改环境变量后无需重启后端:点此重新加载外部对战游戏插件,注册表立即对新游戏开放全套 Arena 端点。</p>
                <button class="btn" type="button" :disabled="reloadBusy" @click="doReloadPlugins">{{ reloadBusy ? "重载中…" : "重载对战插件" }}</button>
            </div>
        </template>
    </div>
</template>

<style scoped>
.page-title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin: 4px 0 14px;
    font-size: 20px;
}

.dim {
    color: var(--text-faint);
}

.small {
    font-size: 12.5px;
}

.section-note {
    font-size: 13px;
    color: var(--text-faint);
    margin: 0 0 12px;
}

.queue-state .badge {
    font-size: 14px;
}

.pause-on {
    border-color: rgba(251, 191, 36, .5);
}

.detail-td {
    max-width: 280px;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* LLM 卡内分区 */
.chat-block {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px dashed var(--border-strong);
}

.card h3 {
    margin: 18px 0 10px;
    font-size: 15.5px;
    display: flex;
    align-items: baseline;
    gap: 8px;
}

.chat-block h3 {
    margin-top: 0;
}

.chat-result {
    margin-top: 12px;
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 14px;
}
</style>
