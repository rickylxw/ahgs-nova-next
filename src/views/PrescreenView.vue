<script setup>
/* ============ AHGS NOVA Next · Nova v2 评估预筛测试台 ============
 * POST /api/v2/prescreen:合成迷你实例 + 子进程限时,把崩溃/非法/超时候选
 * 在进主评估前淘汰。返回结构化 {ok, objective, fail_reason, detail, elapsed_ms, ascend}。
 */
import { onMounted, ref } from "vue";
import * as nova from "../api/nova";
import { useProblemsStore } from "../stores/problems";
import { fmtObj, fullNum } from "../lib/format";
import CodeBlock from "../components/CodeBlock.vue";

const problems = useProblemsStore();

/* ============ 表单 ============ */
const psProblem = ref("");
const psCode = ref("");
const psInstance = ref("");
const psSolution = ref("");
const psTimeout = ref(10);
const instOpen = ref(false);
const solOpen = ref(false);
const psErr = ref(null);
const psBusy = ref(false);
const result = ref(null);

const FAIL_LABEL = {
    load_error: "加载失败",
    crash: "运行崩溃",
    timeout: "超时",
    bad_return: "返回值不合法",
};

/** 方向标注:ascend !== false 即目标越低越好 */
function dirLabel(asc) {
    return asc !== false ? "越低越好" : "越高越好";
}

/** fail_reason → 中文;未知原因原样展示 */
function failLabel(r) {
    return FAIL_LABEL[r] || r || "未知原因";
}

/** 可选 JSON 文本 → 对象;空串返回 null(字段省略) */
function parseOptionalJson(text, label) {
    if (!text.trim()) return null;
    let v;
    try {
        v = JSON.parse(text);
    } catch {
        throw new Error(`${label} JSON 解析失败,请检查语法`);
    }
    if (!v || typeof v !== "object" || Array.isArray(v)) {
        throw new Error(`${label} 需为 JSON 对象`);
    }
    return v;
}

async function submitPrescreen() {
    psErr.value = null;
    if (!psProblem.value) { psErr.value = "请选择题目"; return; }
    if (!psCode.value.trim()) { psErr.value = "请填写候选代码 candidate_code"; return; }
    let instance;
    let solution;
    try {
        instance = parseOptionalJson(psInstance.value, "instance");
        solution = parseOptionalJson(psSolution.value, "solution");
    } catch (e) {
        psErr.value = e.message;
        return;
    }
    let timeout = Number(psTimeout.value);
    if (!isFinite(timeout) || timeout <= 0) timeout = 10;
    if (timeout > 60) timeout = 60; // 后端上限 60s
    const body = {
        problem_key: psProblem.value,
        candidate_code: psCode.value,
        timeout_seconds: timeout,
    };
    if (instance) body.instance = instance;
    if (solution) body.solution = solution;
    psBusy.value = true;
    try {
        result.value = await nova.prescreen(body);
    } catch (e) {
        psErr.value = (e && e.message) || "预筛请求失败";
    } finally {
        psBusy.value = false;
    }
}

/* ============ 示例候选 ============ */
const SAMPLE_CODE = `# 示例候选:贪心累加求和,仅用于联调预筛链路。
# 真实候选以题目 contract 的 evaluate 约定为准:
#   evaluate(instance, config) -> number | {"objective": number}
def evaluate(instance, config):
    items = instance.get("numbers") or []
    total = 0.0
    for x in sorted((float(v) for v in items), reverse=True):
        total += x
    return {"objective": total}`;

const SAMPLE_INSTANCE = '{ "numbers": [3, 1, 4, 1, 5, 9, 2, 6] }';

function fillExample() {
    psCode.value = SAMPLE_CODE;
    if (!psInstance.value.trim()) {
        psInstance.value = SAMPLE_INSTANCE;
        instOpen.value = true;
    }
}

onMounted(async () => {
    await problems.load().catch(() => { /* App 启动已加载,失败不阻塞 */ });
});
</script>

<template>
    <div>
        <h1 class="page-title">评估预筛 <span class="hint">Nova v2 · 迷你实例限时试跑,先淘汰坏候选</span></h1>

        <!-- 表单 -->
        <div class="card">
            <h2>候选试跑 <span class="tail">POST /api/v2/prescreen</span></h2>
            <form @submit.prevent="submitPrescreen">
                <div class="grid-2">
                    <div class="field">
                        <label>题目</label>
                        <select v-model="psProblem">
                            <option value="">— 请选择 —</option>
                            <option v-for="p in problems.list" :key="p.key" :value="p.key">{{ p.name }} · {{ p.key }}</option>
                        </select>
                    </div>
                    <div class="field">
                        <label>超时 timeout_seconds(1–60,默认 10)</label>
                        <input type="number" min="1" max="60" step="any" v-model.number="psTimeout" />
                    </div>
                </div>
                <div class="field">
                    <label>
                        <span class="label-row">候选代码 candidate_code
                            <button class="btn small" type="button" @click="fillExample">填入示例候选</button>
                        </span>
                    </label>
                    <textarea class="input mono" v-model="psCode" rows="10" spellcheck="false" placeholder="def evaluate(instance, config): …(以题目 contract 的 evaluate 约定为准)"></textarea>
                </div>
                <div class="adv-head">
                    <button class="chip" type="button" :class="{ on: instOpen }" @click="instOpen = !instOpen">{{ instOpen ? "收起 instance ▴" : "instance JSON(可选)▾" }}</button>
                </div>
                <div class="field" v-show="instOpen">
                    <label>合成迷你实例 instance(留空则用题目 contract 的 prescreen_instance)</label>
                    <textarea class="input mono" v-model="psInstance" rows="4" spellcheck="false" placeholder='{ "numbers": [3, 1, 4] }'></textarea>
                </div>
                <div class="adv-head">
                    <button class="chip" type="button" :class="{ on: solOpen }" @click="solOpen = !solOpen">{{ solOpen ? "收起 solution ▴" : "solution JSON(可选)▾" }}</button>
                </div>
                <div class="field" v-show="solOpen">
                    <label>参考解 solution(部分题目评估器需要,如 TSP 的初始线路)</label>
                    <textarea class="input mono" v-model="psSolution" rows="4" spellcheck="false" placeholder='{ "route": [0, 1, 2] }'></textarea>
                </div>
                <div class="error-banner" v-if="psErr">{{ psErr }}</div>
                <button class="btn primary" type="submit" :disabled="psBusy">{{ psBusy ? "预筛中…" : "运行预筛" }}</button>
                <p class="hint">候选在子进程限时运行:崩溃 / 非法返回 / 超时会以结构化 fail_reason 给出,不会进入主评估队列。</p>
            </form>
        </div>

        <!-- 结果 -->
        <div class="card" v-if="result">
            <h2>预筛结果 <span class="tail">{{ result.problem_key }} · 耗时 {{ result.elapsed_ms }} ms</span></h2>
            <div class="result-head">
                <span class="badge big-badge" :class="result.ok ? 'src-local' : 'evo-st-failed'">{{ result.ok ? "✓ 通过预筛" : "✗ 未通过预筛" }}</span>
                <span class="badge evo-st-failed" v-if="!result.ok && result.fail_reason">{{ failLabel(result.fail_reason) }}</span>
            </div>
            <div class="grid-2 result-kv">
                <div class="kv"><span class="k">objective(目标值)</span><span class="mono" :title="fullNum(result.objective)">{{ result.objective == null ? "—" : fmtObj(result.objective) }}<span class="hint"> {{ dirLabel(result.ascend) }}</span></span></div>
                <div class="kv"><span class="k">失败原因 fail_reason</span><span>{{ result.ok ? "—" : failLabel(result.fail_reason) }}</span></div>
                <div class="kv"><span class="k">耗时 elapsed_ms</span><span class="mono">{{ result.elapsed_ms }} ms</span></div>
                <div class="kv"><span class="k">优化方向 ascend</span><span>{{ result.ascend == null ? "—" : dirLabel(result.ascend) }}</span></div>
            </div>
            <template v-if="result.detail">
                <p class="detail-label">detail(诊断信息)</p>
                <CodeBlock :code="result.detail" maxHeight="260px" />
            </template>
            <p class="hint" v-else-if="result.ok">无附加诊断信息 —— 候选可安全进入主评估。</p>
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

.label-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
}

.adv-head {
    margin: 2px 0 10px;
}

.result-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 14px;
}

.big-badge {
    font-size: 15px;
    padding: 6px 18px;
}

.result-kv {
    margin-bottom: 10px;
}

.detail-label {
    margin: 4px 0 0;
    font-size: 12px;
    color: var(--text-dim);
    letter-spacing: .05em;
}
</style>
