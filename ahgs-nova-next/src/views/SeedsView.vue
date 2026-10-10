<script setup>
/* ============ AHGS NOVA Next · Nova v2 种子库 ============
 * 列表(GET /api/v2/seeds,列表不含 algorithm)/ 行内展开懒加载详情(getSeed)
 * / 手动导入种子(POST) / 删除种子(DELETE,仅管理员)。
 */
import { onMounted, ref } from "vue";
import * as nova from "../api/nova";
import { useSessionStore } from "../stores/session";
import { useProblemsStore } from "../stores/problems";
import { toast } from "../stores/ui";
import { fmtObj, fullNum, fmtTime, isAscend, parseServerTime } from "../lib/format";
import CodeBlock from "../components/CodeBlock.vue";
import EmptyState from "../components/EmptyState.vue";

const session = useSessionStore();
const problems = useProblemsStore();

/* ============ 错误提示:AUTH_FORBIDDEN 按规约换文案 ============ */
function toastErr(e) {
    toast(e && e.code === "AUTH_FORBIDDEN" ? "需要管理员账号" : (e && e.message) || "请求失败", "err");
}

/* ============ 列表 ============ */
const seeds = ref([]);
const loading = ref(false);
const listErr = ref(null);
const fProblem = ref("");
const fLimit = ref(100);

async function load() {
    loading.value = true;
    try {
        const r = await nova.listSeeds({
            problem_key: fProblem.value || undefined,
            limit: Number(fLimit.value) || 100,
        });
        seeds.value = r.seeds ?? [];
        listErr.value = null;
    } catch (e) {
        listErr.value = e;
    } finally {
        loading.value = false;
    }
}

/* ---- 展示辅助 ---- */
function pName(key) {
    if (!key) return "—";
    return problems.byKey[key]?.name || key;
}

/** 方向标注:ascend !== false 即目标越低越好(与后端方向守卫一致) */
function objDir(key) {
    return isAscend(key) ? "越低越好" : "越高越好";
}

function objTitle(s) {
    if (s.objective == null) return "";
    return `方向:${objDir(s.problem_key)} · 完整值:${fullNum(s.objective)}`;
}

/** feature 兼容:数组或逗号串(全角/半角)统一成字符串数组 */
function featureList(f) {
    if (Array.isArray(f)) return f.map((x) => String(x)).filter((x) => x.trim());
    if (typeof f === "string") return f.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
    return [];
}

/** 来源徽章:manual→手动 / harvest→收割,其余原样展示 */
function sourceInfo(s) {
    if (s.source === "manual") return { label: "手动", cls: "feature-badge" };
    if (s.source === "harvest") return { label: "收割", cls: "src-local" };
    return { label: s.source || "—", cls: "feature-badge" };
}

function timeTitle(iso) {
    const d = parseServerTime(iso);
    return d ? d.toLocaleString("zh-CN") : "";
}

/* ============ 详情展开(懒加载 getSeed,含 algorithm) ============ */
const expandedId = ref(null);
const algoCache = ref({});
const algoLoadingId = ref(null);
const algoErr = ref(null);

async function toggleDetail(s) {
    if (expandedId.value === s.id) {
        expandedId.value = null;
        return;
    }
    expandedId.value = s.id;
    if (algoCache.value[s.id] === undefined) {
        algoLoadingId.value = s.id;
        algoErr.value = null;
        try {
            const r = await nova.getSeed(s.id);
            algoCache.value[s.id] = r.algorithm || "";
        } catch (e) {
            algoErr.value = (e && e.message) || "加载种子详情失败";
        } finally {
            algoLoadingId.value = null;
        }
    }
}

/* ============ 删除(仅管理员) ============ */
const deletingId = ref(null);

async function doDelete(s) {
    if (!window.confirm(`确认删除种子 #${s.id}?该操作不可撤销。`)) return;
    deletingId.value = s.id;
    try {
        await nova.deleteSeed(s.id);
        toast(`种子 #${s.id} 已删除`, "ok");
        if (expandedId.value === s.id) expandedId.value = null;
        await load();
    } catch (e) {
        toastErr(e);
    } finally {
        deletingId.value = null;
    }
}

/* ============ 手动导入种子(折叠卡) ============ */
const nsOpen = ref(false);
const nsProblem = ref("");
const nsConcept = ref("");
const nsFeature = ref("");
const nsObjective = ref("");
const nsAlgorithm = ref("");
const nsErr = ref(null);
const nsBusy = ref(false);

async function submitCreate() {
    nsErr.value = null;
    if (!nsProblem.value) { nsErr.value = "请选择题目"; return; }
    if (!nsAlgorithm.value.trim()) { nsErr.value = "请填写算法代码(algorithm)"; return; }
    let objective = null;
    if (nsObjective.value !== "" && nsObjective.value != null) {
        objective = Number(nsObjective.value);
        if (!isFinite(objective)) { nsErr.value = "目标值 objective 需为数字"; return; }
    }
    const body = {
        problem_key: nsProblem.value,
        algorithm: nsAlgorithm.value,
        concept: nsConcept.value.trim(),
        feature: nsFeature.value.split(/[,，]/).map((x) => x.trim()).filter(Boolean),
        objective,
    };
    nsBusy.value = true;
    try {
        const r = await nova.createSeed(body);
        toast(`种子 #${r.id} 已导入`, "ok");
        nsOpen.value = false;
        nsConcept.value = "";
        nsFeature.value = "";
        nsObjective.value = "";
        nsAlgorithm.value = "";
        await load();
    } catch (e) {
        toastErr(e);
    } finally {
        nsBusy.value = false;
    }
}

onMounted(async () => {
    await problems.load().catch(() => { /* App 启动已加载,失败不阻塞 */ });
    await load();
});
</script>

<template>
    <div>
        <h1 class="page-title">种子库 <span class="hint">Nova v2 · 思想档案,只追加(删除为管理员例外出口)</span></h1>

        <!-- 筛选 -->
        <div class="card">
            <div class="toolbar">
                <div class="field">
                    <label>题目</label>
                    <select v-model="fProblem" @change="load">
                        <option value="">全部题目</option>
                        <option v-for="p in problems.list" :key="p.key" :value="p.key">{{ p.name }} · {{ p.key }}</option>
                    </select>
                </div>
                <div class="field">
                    <label>条数上限</label>
                    <select v-model.number="fLimit" @change="load">
                        <option :value="20">20</option>
                        <option :value="50">50</option>
                        <option :value="100">100</option>
                        <option :value="200">200</option>
                        <option :value="500">500</option>
                    </select>
                </div>
                <button class="btn small" type="button" @click="load">刷新</button>
                <span class="toolbar-spacer"></span>
                <button class="btn primary" type="button" @click="nsOpen = !nsOpen">{{ nsOpen ? "收起导入 ▴" : "导入种子 + ▾" }}</button>
            </div>

            <!-- 手动导入(折叠) -->
            <form v-show="nsOpen" class="ns-form" @submit.prevent="submitCreate">
                <div class="grid-2">
                    <div class="field">
                        <label>题目</label>
                        <select v-model="nsProblem">
                            <option value="">— 请选择 —</option>
                            <option v-for="p in problems.list" :key="p.key" :value="p.key">{{ p.name }} · {{ p.key }}</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>目标值 objective(可选)</label>
                        <input type="number" step="any" v-model="nsObjective" placeholder="留空则不计入方向判优" />
                    </div>
                    <div class="field">
                        <label>思想 concept(可选)</label>
                        <input v-model="nsConcept" placeholder="一句话概括该种子的核心思想" />
                    </div>
                    <div class="field">
                        <label>关键词 feature(可选,逗号分隔)</label>
                        <input v-model="nsFeature" placeholder="如:贪心, 局部搜索" />
                    </div>
                </div>
                <div class="field">
                    <label>算法代码 algorithm</label>
                    <textarea class="input mono" v-model="nsAlgorithm" rows="8" spellcheck="false" placeholder="启发式框架源码…"></textarea>
                </div>
                <p class="hint">提交后 source 记为「手动」;收割产生的种子走运行收割通道,不带此表单。</p>
                <button class="btn primary" type="submit" :disabled="nsBusy">{{ nsBusy ? "提交中…" : "导入种子" }}</button>
            </form>
        </div>

        <!-- 列表 -->
        <div class="card">
            <h2>种子列表 <span class="tail">共 {{ seeds.length }} 条<template v-if="fProblem"> · {{ pName(fProblem) }}</template></span></h2>
            <div class="error-banner" v-if="listErr">{{ listErr.message || "种子列表加载失败" }}</div>
            <div class="loading-row" v-if="loading && !seeds.length"><span class="spinner"></span>加载种子列表…</div>
            <div class="table-wrap" v-if="seeds.length">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>题目</th>
                            <th>思想 concept</th>
                            <th>关键词 feature</th>
                            <th>objective</th>
                            <th>来源</th>
                            <th>代数</th>
                            <th>入库时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <template v-for="s in seeds" :key="s.id">
                            <tr :class="{ 'expanded-row': expandedId === s.id }">
                                <td class="mono">#{{ s.id }}</td>
                                <td :title="s.problem_key">{{ pName(s.problem_key) }}</td>
                                <td class="concept-cell" :title="s.concept || ''">{{ s.concept || "—" }}</td>
                                <td>
                                    <span class="badge-row" v-if="featureList(s.feature).length">
                                        <span class="badge feature-badge" v-for="f in featureList(s.feature)" :key="f">{{ f }}</span>
                                    </span>
                                    <span v-else>—</span>
                                </td>
                                <td><span class="mono" :title="objTitle(s)">{{ fmtObj(s.objective) }}<span class="hint" v-if="s.objective != null"> {{ objDir(s.problem_key) }}</span></span></td>
                                <td><span class="badge" :class="sourceInfo(s).cls">{{ sourceInfo(s).label }}</span></td>
                                <td class="mono">{{ s.generation == null ? "—" : s.generation }}</td>
                                <td :title="timeTitle(s.created_at)">{{ fmtTime(s.created_at) }}</td>
                                <td>
                                    <span class="row-actions">
                                        <button class="btn small" type="button" @click="toggleDetail(s)">{{ expandedId === s.id ? "收起" : "详情" }}</button>
                                        <button class="btn small danger" type="button" v-if="session.isAdmin" :disabled="deletingId === s.id" @click="doDelete(s)">{{ deletingId === s.id ? "删除中…" : "删除" }}</button>
                                    </span>
                                </td>
                            </tr>
                            <tr class="detail-row" v-if="expandedId === s.id">
                                <td colspan="9">
                                    <div class="loading-row" v-if="algoLoadingId === s.id"><span class="spinner"></span>加载算法代码…</div>
                                    <div class="error-banner" v-else-if="algoErr">{{ algoErr }}</div>
                                    <template v-else>
                                        <div class="grid-2 detail-kv">
                                            <div class="kv"><span class="k">来源运行</span><span class="mono">{{ s.source_run_id == null ? "—" : "#" + s.source_run_id }}</span></div>
                                            <div class="kv"><span class="k">收割代数</span><span class="mono">{{ s.generation == null ? "—" : s.generation }}</span></div>
                                        </div>
                                        <CodeBlock :code="algoCache[s.id] || '// 无 algorithm 内容'" maxHeight="420px" />
                                    </template>
                                </td>
                            </tr>
                        </template>
                    </tbody>
                </table>
            </div>
            <EmptyState v-else-if="!loading" icon="🌱" desc="暂无种子 —— 手动导入,或从运行收割产出" />
        </div>
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

.toolbar-spacer {
    flex: 1;
}

.ns-form {
    border-top: 1px dashed var(--border-strong);
    padding-top: 14px;
}

.concept-cell {
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
}

.detail-row>td {
    background: var(--card-2);
    white-space: normal;
}

.detail-kv {
    margin-bottom: 10px;
}

.expanded-row td {
    border-bottom-color: transparent;
}

.row-actions {
    display: inline-flex;
    gap: 6px;
}
</style>
