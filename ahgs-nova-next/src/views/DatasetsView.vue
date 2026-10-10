<script setup>
/* ============ AHGS NOVA Next · Nova v2 数据集注册中心 ============
 * 按题列出已注册数据集 / 下载(原始字节流,必须带 Nova Bearer 令牌:
 * api() 对非 JSON 响应返回 Response → blob → objectURL 另存,
 * 不可直接 <a href>,datasetDownloadUrl 不带令牌)/ 上传入库(仅管理员)。
 */
import { onMounted, ref } from "vue";
import { api } from "../api/client";
import * as nova from "../api/nova";
import { useSessionStore } from "../stores/session";
import { useProblemsStore } from "../stores/problems";
import { toast } from "../stores/ui";
import { fmtTime, parseServerTime } from "../lib/format";
import EmptyState from "../components/EmptyState.vue";

const session = useSessionStore();
const problems = useProblemsStore();

function toastErr(e) {
    toast(e && e.code === "AUTH_FORBIDDEN" ? "需要管理员账号" : (e && e.message) || "请求失败", "err");
}

/* ============ 列表 ============ */
const selProblem = ref("");
const datasets = ref([]);
const loading = ref(false);
const listErr = ref(null);

async function load() {
    if (!selProblem.value) {
        datasets.value = [];
        listErr.value = null;
        return;
    }
    loading.value = true;
    try {
        const r = await nova.listDatasets(selProblem.value);
        datasets.value = r.datasets ?? [];
        listErr.value = null;
    } catch (e) {
        listErr.value = e;
    } finally {
        loading.value = false;
    }
}

/* ---- 展示辅助 ---- */
/** 人类可读字节数:B / KB / MB / GB */
function fmtBytes(n) {
    const v = Number(n);
    if (!isFinite(v) || v < 0) return "—";
    if (v < 1024) return v + " B";
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + " KB";
    if (v < 1024 * 1024 * 1024) return (v / (1024 * 1024)).toFixed(2) + " MB";
    return (v / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}

function metaSummary(meta) {
    if (meta == null || typeof meta !== "object") return "";
    const keys = Object.keys(meta);
    if (!keys.length) return "";
    return JSON.stringify(meta);
}

function timeTitle(iso) {
    const d = parseServerTime(iso);
    return d ? d.toLocaleString("zh-CN") : "";
}

/* ============ 下载(fetch 带 Bearer → blob → 另存) ============ */
const downloadingId = ref(null);

async function doDownload(d) {
    if (downloadingId.value != null) return;
    downloadingId.value = d.id;
    try {
        const resp = await api("/api/v2/datasets/" + d.id + "/download", { session: "nova" });
        const blob = resp instanceof Response ? await resp.blob() : new Blob([resp]);
        const name = d.problem_key + "_v" + String(d.version).replace(/[\\/:*?"<>|]/g, "_") + ".bin";
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        toast(`已开始下载 ${name}(${fmtBytes(d.size_bytes)})`, "ok");
    } catch (e) {
        toastErr(e);
    } finally {
        downloadingId.value = null;
    }
}

/* ============ 上传入库(仅管理员) ============ */
const upVersion = ref("");
const upFile = ref(null);
const upFileName = ref("");
const upFileSize = ref(0);
const upMeta = ref("");
const upErr = ref(null);
const upBusy = ref(false);
const fileInputEl = ref(null);

function onFileChange(ev) {
    const f = ev.target.files && ev.target.files[0];
    upFile.value = f || null;
    upFileName.value = f ? f.name : "";
    upFileSize.value = f ? f.size : 0;
}

/** ArrayBuffer → base64(分块拼接,避免大文件 apply 栈溢出) */
function bufToB64(buf) {
    const bytes = new Uint8Array(buf);
    let bin = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(bin);
}

function readFileB64(file) {
    return new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(bufToB64(fr.result));
        fr.onerror = () => reject(new Error("文件读取失败"));
        fr.readAsArrayBuffer(file);
    });
}

function resetUpload() {
    upVersion.value = "";
    upFile.value = null;
    upFileName.value = "";
    upFileSize.value = 0;
    upMeta.value = "";
    if (fileInputEl.value) fileInputEl.value.value = "";
}

async function submitUpload() {
    upErr.value = null;
    if (!selProblem.value) { upErr.value = "请先在上方选择题目"; return; }
    if (!upVersion.value.trim()) { upErr.value = "请填写版本号 version"; return; }
    if (!upFile.value) { upErr.value = "请选择要入库的数据集文件"; return; }
    let meta = {};
    if (upMeta.value.trim()) {
        try {
            meta = JSON.parse(upMeta.value);
        } catch {
            upErr.value = "meta JSON 解析失败,请检查语法";
            return;
        }
        if (!meta || typeof meta !== "object" || Array.isArray(meta)) {
            upErr.value = "meta 需为 JSON 对象";
            return;
        }
    }
    upBusy.value = true;
    try {
        const contentB64 = await readFileB64(upFile.value);
        const r = await nova.uploadDataset(selProblem.value, {
            version: upVersion.value.trim(),
            content_b64: contentB64,
            meta,
        });
        toast(`数据集 v${r.version} 已入库 · sha256 ${String(r.sha256 || "").slice(0, 8)}…`, "ok");
        resetUpload();
        await load();
    } catch (e) {
        toastErr(e);
    } finally {
        upBusy.value = false;
    }
}

onMounted(async () => {
    await problems.load().catch(() => { /* App 启动已加载,失败不阻塞 */ });
});
</script>

<template>
    <div>
        <h1 class="page-title">数据集注册中心 <span class="hint">Nova v2 · 版本化入库 + 带令牌下载</span></h1>

        <div class="card">
            <div class="toolbar">
                <div class="field">
                    <label>题目(必选)</label>
                    <select v-model="selProblem" @change="load">
                        <option value="">— 请选择 —</option>
                        <option v-for="p in problems.list" :key="p.key" :value="p.key">{{ p.name }} · {{ p.key }}</option>
                    </select>
                </div>
                <button class="btn small" type="button" :disabled="!selProblem" @click="load">刷新</button>
            </div>
        </div>

        <!-- 上传入库(仅管理员可见) -->
        <div class="card" v-if="session.isAdmin">
            <h2>上传入库 <span class="tail">POST /api/v2/problems/{key}/datasets · 仅管理员</span></h2>
            <form @submit.prevent="submitUpload">
                <div class="grid-2">
                    <div class="field">
                        <label>版本号 version</label>
                        <input v-model="upVersion" placeholder="如:v3 或 2026-09-30" />
                    </div>
                    <div class="field">
                        <label>数据集文件</label>
                        <input type="file" ref="fileInputEl" @change="onFileChange" />
                        <p class="hint" v-if="upFileName">{{ upFileName }} · {{ fmtBytes(upFileSize) }} → base64 content_b64</p>
                    </div>
                </div>
                <div class="field">
                    <label>meta JSON(可选)</label>
                    <textarea class="input mono" v-model="upMeta" rows="3" spellcheck="false" placeholder='{ "source": "官方榜快照", "rows": 500 }'></textarea>
                </div>
                <div class="error-banner" v-if="upErr">{{ upErr }}</div>
                <button class="btn primary" type="submit" :disabled="upBusy">{{ upBusy ? "上传中…" : "入库" }}</button>
                <p class="hint">入库后自动计算 sha256,并把该题目的 dataset_version 指向此版本。</p>
            </form>
        </div>

        <!-- 列表 -->
        <div class="card">
            <h2>已注册数据集 <span class="tail" v-if="selProblem">{{ problems.byKey[selProblem]?.name || selProblem }} · 共 {{ datasets.length }} 个版本</span><span class="tail" v-else>未选择题目</span></h2>
            <div class="error-banner" v-if="listErr">{{ listErr.message || "数据集列表加载失败" }}</div>
            <div class="loading-row" v-if="loading"><span class="spinner"></span>加载数据集列表…</div>
            <div class="table-wrap" v-if="!loading && datasets.length">
                <table>
                    <thead>
                        <tr>
                            <th>版本</th>
                            <th>sha256</th>
                            <th class="num">大小</th>
                            <th>meta</th>
                            <th>入库时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="d in datasets" :key="d.id">
                            <td class="mono">{{ d.version }}</td>
                            <td><span class="mono sha" :title="d.sha256">{{ d.sha256 }}</span></td>
                            <td class="num mono">{{ fmtBytes(d.size_bytes) }}</td>
                            <td class="meta-cell" :title="metaSummary(d.meta)">{{ metaSummary(d.meta) || "—" }}</td>
                            <td :title="timeTitle(d.created_at)">{{ fmtTime(d.created_at) }}</td>
                            <td>
                                <button class="btn small" type="button" :disabled="downloadingId === d.id" @click="doDownload(d)">{{ downloadingId === d.id ? "下载中…" : "下载" }}</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
            <EmptyState v-else-if="!loading && selProblem" icon="📦" desc="该题目暂无注册数据集" />
            <EmptyState v-else-if="!loading" icon="🗂️" desc="请先选择题目,查看其已注册的数据集版本" />
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

.sha {
    display: inline-block;
    max-width: 150px;
    overflow: hidden;
    text-overflow: ellipsis;
    vertical-align: middle;
}

.meta-cell {
    max-width: 260px;
    overflow: hidden;
    text-overflow: ellipsis;
}
</style>
