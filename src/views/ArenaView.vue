<script setup>
/* ============ AHGS NOVA Next · 对战玩法(Arena v2) ============
 * 四页签:① 游戏与 Bot(目录/上传/管理)② 约战(选 bot 入队)③ 对局记录(结果回放)④ ELO 榜。
 * 约战成功后提示到「对局记录」页签查看进度与结果(对局列表 15 秒自动刷新)。
 * result 形状(以 tictactoe.py 为准):Match.result = {arena, config, games:[GameRecord], scores};
 * GameRecord = {players, first, winner, reason: win|draw|illegal|timeout|crash, moves};
 * moves 元素 = {player, board(快照), move?(下标), outcome: ok|illegal|timeout|crash|pass…, detail?}。
 * 回放渲染按游戏目录协商:board_shape 定网格尺寸、pieces 定棋子字符、labels 定 reason/outcome 文案
 * (ARENA_GAMES.md §8),缺省回退井字棋形状;非数组 board 走 JSON 兜底。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import * as nova from "../api/nova";
import { useSessionStore } from "../stores/session";
import { toast } from "../stores/ui";
import { V2_STATUS_LABEL } from "../lib/constants";
import { fmtTime, parseServerTime } from "../lib/format";
import CodeBlock from "../components/CodeBlock.vue";
import EmptyState from "../components/EmptyState.vue";
import Medal from "../components/Medal.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();

function errText(e) {
    if (!e) return "";
    if (typeof e === "string") return e;
    if (e.code === "AUTH_FORBIDDEN") return "需要管理员账号";
    return e.message || "请求失败";
}

/* ============ 页签(route.query.tab 同步) ============ */
const TABS = [
    { key: "bots", label: "游戏与 Bot" },
    { key: "match", label: "约战" },
    { key: "records", label: "对局记录" },
    { key: "elo", label: "ELO 榜" },
];
const TAB_KEYS = new Set(TABS.map((t) => t.key));
const tab = computed(() => (TAB_KEYS.has(route.query.tab) ? String(route.query.tab) : "bots"));
function switchTab(k) {
    router.replace({ query: { ...route.query, tab: k } });
}

/* ============ 游戏目录(匿名可调,进入即拉) ============ */
const arenas = ref([]);
const arenasErr = ref(null);
const arenaByKey = computed(() => Object.fromEntries(arenas.value.map((a) => [a.key, a])));

async function loadArenas() {
    arenasErr.value = null;
    try {
        const r = await nova.listArenas();
        arenas.value = r.arenas ?? [];
    } catch (e) {
        arenasErr.value = errText(e);
    }
}

/* ---- 目录展示辅助 ---- */
function contractHead(a) {
    return (a.bot_contract || "").split("\n")[0] || "—";
}
function configSummary(a) {
    const cfg = a.default_config || {};
    const parts = Object.entries(cfg).map(([k, v]) => `${k}=${v}`);
    return parts.length ? parts.join(" · ") : "无默认参数";
}

/* ============ ① 游戏与 Bot:bot 列表 + 上传 ============ */
const bots = ref([]);
const botsLoading = ref(false);
const botsErr = ref(null);
const bArena = ref("");
const bMine = ref(false);
const codeOpenId = ref(null);
const codeMap = ref({}); // botId → {code?: string, denied?: boolean}
const deactivating = ref(null);

async function loadBots() {
    botsLoading.value = true;
    botsErr.value = null;
    try {
        const r = await nova.listBots({
            arena_key: bArena.value || undefined,
            mine: bMine.value || undefined,
            limit: 200,
        });
        bots.value = r.bots ?? [];
    } catch (e) {
        botsErr.value = errText(e);
    } finally {
        botsLoading.value = false;
    }
}

function isMine(b) {
    return b.user_id != null && b.user_id === session.user?.id;
}

async function toggleCode(b) {
    if (codeOpenId.value === b.id) {
        codeOpenId.value = null;
        return;
    }
    codeOpenId.value = b.id;
    if (codeMap.value[b.id]) return;
    try {
        const r = await nova.getBot(b.id);
        // 非 owner/admin 时后端直接省略 code 字段(不报错)
        codeMap.value = { ...codeMap.value, [b.id]: r.code ? { code: r.code } : { denied: true } };
    } catch (e) {
        codeMap.value = { ...codeMap.value, [b.id]: { denied: true } };
        toast(errText(e), "err");
    }
}

async function doDeactivate(b) {
    if (!window.confirm(`确认停用 bot「${b.name}」?停用后不可参与约战。`)) return;
    deactivating.value = b.id;
    try {
        await nova.deactivateBot(b.id);
        toast(`已停用 bot「${b.name}」`, "ok");
        await loadBots();
    } catch (e) {
        toast(errText(e), "err");
    } finally {
        deactivating.value = null;
    }
}

/* ---- 上传 bot ---- */
const upArena = ref("");
const upName = ref("");
const upCode = ref("");
const upLang = ref("python");
const upErr = ref(null);
const upBusy = ref(false);

async function submitBot() {
    upErr.value = null;
    if (!upArena.value) { upErr.value = "请选择对战游戏"; return; }
    if (!upName.value.trim()) { upErr.value = "请填写 bot 名称"; return; }
    if (!upCode.value.trim()) { upErr.value = "请填写 bot 源码"; return; }
    upBusy.value = true;
    try {
        const r = await nova.createBot({
            arena_key: upArena.value,
            name: upName.value.trim(),
            code: upCode.value,
            lang: upLang.value.trim() || "python",
        });
        toast(`Bot #${r.id}「${r.name}」已上传`, "ok");
        upName.value = "";
        upCode.value = "";
        await loadBots();
    } catch (e) {
        upErr.value = errText(e);
    } finally {
        upBusy.value = false;
    }
}

/* ---- 示例 Bot 一键填入(目录卡 → 上传表单) ---- */
function useStarter(a) {
    upArena.value = a.key;
    upLang.value = "python";
    upCode.value = a.starter_code || "";
    if (!upName.value.trim()) upName.value = `${a.key}-bot`;
    switchTab("bots");
    toast("已填入示例 Bot 源码,补充名称后即可上传", "ok");
}

/* ============ ② 约战 ============ */
const mArena = ref("");
const mBots = ref([]); // 该 arena 的全部 bot(前端过滤 active)
const mBotsLoading = ref(false);
const mBotsErr = ref(null);
const mSel = ref([]); // 已选 bot id
const mConfigText = ref("");
const mErr = ref(null);
const mBusy = ref(false);
const lastMatch = ref(null); // 成功创建的对局(含 run_id)

const mArenaObj = computed(() => arenaByKey.value[mArena.value] || null);
const mActiveBots = computed(() => mBots.value.filter((b) => b.active));
const mMinBots = computed(() => (mArenaObj.value ? mArenaObj.value.min_bots : 2));
const mMaxBots = computed(() => (mArenaObj.value ? mArenaObj.value.max_bots : 2));
const canCreateMatch = computed(() => mSel.value.length >= mMinBots.value);
const mOverHint = computed(() =>
    mSel.value.length > mMaxBots.value
        ? `已选 ${mSel.value.length} 个,超过「${mArenaObj.value?.display_name || mArena.value}」标称上限 ${mMaxBots.value},后端可能拒绝`
        : "");

async function loadMatchBots() {
    if (!mArena.value) { mBots.value = []; mSel.value = []; return; }
    mBotsLoading.value = true;
    mBotsErr.value = null;
    try {
        const r = await nova.listBots({ arena_key: mArena.value, limit: 200 });
        mBots.value = r.bots ?? [];
        mSel.value = mSel.value.filter((id) => mActiveBots.value.some((b) => b.id === id));
    } catch (e) {
        mBotsErr.value = errText(e);
    } finally {
        mBotsLoading.value = false;
    }
}

function pickArenaForMatch(key) {
    mArena.value = key;
    lastMatch.value = null;
    const a = arenaByKey.value[key];
    mConfigText.value = a ? JSON.stringify(a.default_config ?? {}, null, 2) : "";
    loadMatchBots();
}

async function submitMatch() {
    mErr.value = null;
    lastMatch.value = null;
    if (!mArena.value) { mErr.value = "请选择对战游戏"; return; }
    if (mSel.value.length < mMinBots.value) {
        mErr.value = `至少需要选择 ${mMinBots.value} 个 bot`;
        return;
    }
    let config = {};
    if (mConfigText.value.trim()) {
        try {
            config = JSON.parse(mConfigText.value);
        } catch {
            mErr.value = "config JSON 解析失败,请检查语法";
            return;
        }
        if (!config || typeof config !== "object" || Array.isArray(config)) {
            mErr.value = "config 需为 JSON 对象";
            return;
        }
    }
    mBusy.value = true;
    try {
        const r = await nova.createMatch({
            arena_key: mArena.value,
            bot_ids: mSel.value.map(Number),
            config,
        });
        lastMatch.value = r;
        toast(`约战 #${r.id} 已创建并入队`, "ok");
        await loadMatches(true);
    } catch (e) {
        if (e.code === "ARENA_NOT_FOUND") {
            mErr.value = "该对战游戏不存在或未加载";
        } else {
            mErr.value = errText(e);
        }
    } finally {
        mBusy.value = false;
    }
}

function gotoRecords() {
    switchTab("records");
}

/* ============ ③ 对局记录 ============ */
const matches = ref([]);
const matchesLoading = ref(false);
const matchesErr = ref(null);
const mtArena = ref("");
let matchTimer = null;

async function loadMatches(silent = false) {
    if (!silent) matchesLoading.value = true;
    matchesErr.value = null;
    try {
        const r = await nova.listMatches({
            arena_key: mtArena.value || undefined,
            limit: 100,
        });
        matches.value = r.matches ?? [];
    } catch (e) {
        matchesErr.value = errText(e);
    } finally {
        matchesLoading.value = false;
    }
}

function statusLabel(st) {
    return V2_STATUS_LABEL[st] || st || "—";
}
function statusBadge(st) {
    if (st === "running" || st === "finalizing") return "src-local";
    if (st === "completed") return "evo-st-running"; // 全局绿色徽章
    if (st === "failed") return "evo-st-failed";
    if (st === "canceled") return "evo-st-stopped";
    return "evo-st-pending"; // queued / provisioning
}
function botIdsText(m) {
    const ids = Array.isArray(m.bot_ids) ? m.bot_ids : [];
    const s = ids.map((i) => "#" + i).join(" ");
    return s.length > 28 ? s.slice(0, 28) + "…" : s || "—";
}
function matchFinished(m) {
    return m.finished_at ? fmtTime(m.finished_at) : "—";
}

/* ---- 对局详情(result 回放) ---- */
const detail = ref(null); // { match, result, names: {id: name} }
const detailLoadingId = ref(null);
const detailErr = ref(null);

async function toggleDetail(m) {
    if (detailLoadingId.value === m.id) return;
    if (detail.value?.match?.id === m.id) {
        detail.value = null;
        return;
    }
    detailLoadingId.value = m.id;
    detailErr.value = null;
    detail.value = null;
    try {
        const full = await nova.getMatch(m.id);
        const ids = new Set();
        for (const id of full.bot_ids || []) ids.add(Number(id));
        const result = full.result || null;
        if (result && Array.isArray(result.games)) {
            for (const g of result.games) {
                for (const pid of g.players || []) ids.add(Number(pid));
            }
        } else if (result && Array.isArray(result.players)) {
            for (const pid of result.players) ids.add(Number(pid));
        }
        const names = {};
        await Promise.all([...ids].map(async (id) => {
            try {
                const b = await nova.getBot(id);
                names[id] = b.name || `#${id}`;
            } catch {
                names[id] = `Bot #${id}`;
            }
        }));
        detail.value = { match: full, result, names };
    } catch (e) {
        detailErr.value = errText(e);
    } finally {
        detailLoadingId.value = null;
    }
}

function botName(id) {
    return detail.value?.names?.[Number(id)] || `Bot #${id}`;
}

/* 对局结果形状判定:arena 报告 {games,scores} / 单局 GameRecord {moves} / 其他原样 JSON */
const detailKind = computed(() => {
    const r = detail.value?.result;
    if (!r) return "none"; // 未完成或无结果
    if (Array.isArray(r.games)) return "report";
    if (Array.isArray(r.moves)) return "game";
    return "raw";
});
const reportGames = computed(() => (detailKind.value === "report" ? detail.value.result.games : []));
const reportConfig = computed(() => {
    if (detailKind.value !== "report") return "";
    const c = detail.value.result.config || {};
    const parts = Object.entries(c).map(([k, v]) => `${k}=${v}`);
    return parts.length ? parts.join(" · ") : "";
});
const reportScores = computed(() => {
    if (detailKind.value !== "report") return [];
    const sc = detail.value.result.scores || {};
    return Object.entries(sc).map(([id, s]) => ({
        id: Number(id),
        name: botName(id),
        win: s.win ?? 0,
        loss: s.loss ?? 0,
        draw: s.draw ?? 0,
    }));
});
const rawResultText = computed(() =>
    detailKind.value === "raw" ? JSON.stringify(detail.value.result, null, 2) : "");

/* ---- reason / outcome 中文映射:游戏目录 labels 优先,内置默认兜底 ---- */
const REASON_LABEL = {
    win: "规则达成获胜",
    draw: "终局平局",
    illegal: "非法落子判负",
    timeout: "落子超时判负",
    crash: "程序崩溃判负",
};
function reasonLabel(r) {
    const l = detailArenaObj()?.labels?.reason;
    return (l && l[r]) || REASON_LABEL[r] || r || "—";
}
const OUTCOME_LABEL = {
    ok: "落子",
    illegal: "非法",
    timeout: "超时",
    crash: "崩溃",
};
function outcomeLabel(o) {
    const l = detailArenaObj()?.labels?.outcome;
    return (l && l[o]) || OUTCOME_LABEL[o] || o || "—";
}
function gameWinnerLabel(g) {
    return g.winner != null ? `${botName(g.winner)} 获胜` : "平局";
}

/* ---- 回放渲染协商:目录下发 board_shape/pieces/labels(ARENA_GAMES.md §8),缺省回退井字棋形状 ---- */
function detailArenaObj() {
    return arenaByKey.value[detail.value?.match?.arena_key] || null;
}
function boardShape() {
    const s = detailArenaObj()?.board_shape;
    return s && s.rows > 0 && s.cols > 0 ? s : { rows: 3, cols: 3 };
}
function boardStyle() {
    const s = boardShape();
    return {
        gridTemplateColumns: `repeat(${s.cols}, 26px)`,
        gridTemplateRows: `repeat(${s.rows}, 26px)`,
    };
}
function piecesMap() {
    return detailArenaObj()?.pieces || { "1": "X", "2": "O" };
}
function pieceChar(v) {
    return v ? (piecesMap()[String(v)] || String(v)) : "";
}
function isBoard(mv) {
    const s = boardShape();
    const n = s.rows * s.cols;
    if (Array.isArray(mv?.board)) return mv.board.length === n;
    // dict 视图(如炸弹人):带 cells 数组即可按网格渲染
    return Array.isArray(mv?.board?.cells) && mv.board.cells.length === n;
}
function boardCellsOf(mv) {
    return Array.isArray(mv?.board) ? mv.board : (mv?.board?.cells || []);
}
function cellClassOf(v) {
    const map = detailArenaObj()?.cell_classes;
    if (map && map[String(v)]) return map[String(v)];
    return v === 1 ? "x" : v === 2 ? "o" : "";
}
function cellCls(v, mv, idx) {
    let c = cellClassOf(v);
    if (mv.outcome === "ok" && mv.move === idx) c += " last";
    else if ((mv.outcome === "illegal" || mv.outcome === "hit") && mv.move === idx) c += " bad";
    return c.trim();
}
/* mover 的玩家标记:目录 player_marks 优先(多人局支持 3/4 号色),players 顺序即编号 */
function markInfo(g, player) {
    const idx = (g.players || []).indexOf(player);
    if (idx < 0) return { char: "?", cls: "" };
    const marks = detailArenaObj()?.player_marks;
    const char = (marks && marks[String(idx + 1)]) || pieceChar(idx + 1) || "?";
    const cls = ["mk-x", "mk-o", "mk-p3", "mk-p4"][idx] || "mk-x";
    return { char, cls };
}
function gameJson(g) {
    return JSON.stringify(g, null, 2);
}

/* ============ ④ ELO 榜 ============ */
const eArena = ref("");
const board = ref([]);
const eloLoading = ref(false);
const eloErr = ref(null);

async function loadLeaderboard() {
    if (!eArena.value) { board.value = []; return; }
    eloLoading.value = true;
    eloErr.value = null;
    try {
        const r = await nova.arenaLeaderboard(eArena.value);
        board.value = r.leaderboard ?? [];
    } catch (e) {
        if (e.code === "ARENA_NOT_FOUND") {
            eloErr.value = "该对战游戏不存在或未加载";
            board.value = [];
        } else {
            eloErr.value = errText(e);
        }
    } finally {
        eloLoading.value = false;
    }
}

function pickEloArena(key) {
    eArena.value = key;
    loadLeaderboard();
}

/* ============ 初始化与页签懒加载 ============ */
let arenasInited = false;
watch(tab, (t) => {
    if (!arenasInited) return;
    if (t === "bots") loadBots();
    if (t === "records") loadMatches();
    if (t === "elo" && eArena.value && !board.value.length) loadLeaderboard();
});

onMounted(async () => {
    await loadArenas();
    arenasInited = true;
    if (arenas.value.length) {
        if (!upArena.value) upArena.value = arenas.value[0].key;
        if (!eArena.value) { eArena.value = arenas.value[0].key; loadLeaderboard(); }
    }
    if (tab.value === "bots") loadBots();
    if (tab.value === "records") loadMatches();
    // 对局记录 15 秒自动刷新(仅该页签活跃时)
    matchTimer = setInterval(() => {
        if (tab.value === "records" && !detailLoadingId.value) loadMatches(true);
    }, 15000);
});

onUnmounted(() => {
    if (matchTimer) clearInterval(matchTimer);
    matchTimer = null;
});

/* 服务器时间展示统一走 fmtTime(内部 parseServerTime,naive UTC 补 Z) */
function fmtFinished(iso) {
    const d = parseServerTime(iso);
    return d ? fmtTime(iso) : (iso || "—");
}
</script>

<template>
    <div>
        <h1 class="page-title">对战玩法 <span class="hint">上传 bot · 约战 · ELO 天梯</span></h1>

        <!-- 页签 -->
        <div class="chip-row tabs-row">
            <button v-for="t in TABS" :key="t.key" class="chip" :class="{ on: tab === t.key }" type="button" @click="switchTab(t.key)">{{ t.label }}</button>
        </div>

        <div class="error-banner" v-if="arenasErr">游戏目录加载失败:{{ arenasErr }}</div>

        <!-- ============ ① 游戏与 Bot ============ -->
        <template v-if="tab === 'bots'">
            <div class="grid cols-2">
                <div class="card" v-for="a in arenas" :key="a.key">
                    <h2>{{ a.display_name }} <span class="mono small dim">{{ a.key }}</span></h2>
                    <div class="kv"><span class="k">参与 bot 数</span><span class="mono">{{ a.min_bots }} – {{ a.max_bots }}</span></div>
                    <div class="kv"><span class="k">默认参数</span><span class="mono small">{{ configSummary(a) }}</span></div>
                    <div class="kv"><span class="k">bot 入口约定</span><span class="mono small">{{ contractHead(a) }}</span></div>
                    <details class="alg-details contract-fold" v-if="a.bot_contract">
                        <summary>完整 bot 实现约定</summary>
                        <CodeBlock :code="a.bot_contract" />
                    </details>
                    <span class="row-actions">
                        <button class="btn small" type="button" @click="pickArenaForMatch(a.key); switchTab('match')">去约战 →</button>
                        <button class="btn small" type="button" v-if="a.starter_code" @click="useStarter(a)">示例 Bot →</button>
                    </span>
                </div>
            </div>
            <EmptyState v-if="!arenas.length && !arenasErr" icon="🎮" desc="暂无已注册的对战游戏" />

            <!-- bot 列表 -->
            <div class="card">
                <h2>Bot 管理 <span class="tail">{{ bots.length }} 个 bot</span></h2>
                <div class="toolbar">
                    <div class="field">
                        <label>游戏</label>
                        <select v-model="bArena" @change="loadBots">
                            <option value="">全部游戏</option>
                            <option v-for="a in arenas" :key="a.key" :value="a.key">{{ a.display_name }}</option>
                        </select>
                    </div>
                    <label class="check-row"><input type="checkbox" v-model="bMine" @change="loadBots" />只看我的</label>
                    <button class="btn small" type="button" @click="loadBots">刷新</button>
                </div>
                <div class="error-banner" v-if="botsErr">{{ botsErr }}</div>
                <div class="loading-row" v-if="botsLoading && !bots.length"><span class="spinner"></span>加载 bot 列表…</div>
                <div class="table-wrap" v-if="bots.length">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>名称</th>
                                <th>游戏</th>
                                <th class="num">Rating</th>
                                <th class="num">胜</th>
                                <th class="num">负</th>
                                <th class="num">和</th>
                                <th>状态</th>
                                <th>创建时间</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <template v-for="b in bots" :key="b.id">
                                <tr>
                                    <td class="mono">#{{ b.id }}</td>
                                    <td><b>{{ b.name }}</b><span class="small dim" v-if="isMine(b)"> (我的)</span></td>
                                    <td class="small">{{ arenaByKey[b.arena_key]?.display_name || b.arena_key }}</td>
                                    <td class="num mono"><b>{{ b.rating }}</b></td>
                                    <td class="num mono">{{ b.wins }}</td>
                                    <td class="num mono">{{ b.losses }}</td>
                                    <td class="num mono">{{ b.draws }}</td>
                                    <td><span class="badge" :class="b.active ? 'evo-st-running' : 'evo-st-stopped'">{{ b.active ? "活跃" : "已停用" }}</span></td>
                                    <td class="small">{{ fmtFinished(b.created_at) }}</td>
                                    <td>
                                        <span class="row-actions">
                                            <button class="btn small" type="button" @click="toggleCode(b)">{{ codeOpenId === b.id ? "收起代码" : "查看代码" }}</button>
                                            <button class="btn small danger" type="button" v-if="b.active && isMine(b)" :disabled="deactivating === b.id" @click="doDeactivate(b)">{{ deactivating === b.id ? "停用中…" : "停用" }}</button>
                                        </span>
                                    </td>
                                </tr>
                                <tr v-if="codeOpenId === b.id">
                                    <td colspan="10" class="code-cell">
                                        <template v-if="codeMap[b.id]?.denied"><span class="hint">仅作者或管理员可见代码</span></template>
                                        <CodeBlock v-else-if="codeMap[b.id]?.code" :code="codeMap[b.id].code" />
                                        <span class="hint" v-else>加载中…</span>
                                    </td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
                <EmptyState v-else-if="!botsLoading && !botsErr" icon="🤖" desc="暂无 bot —— 在下方上传一个参战程序" />
            </div>

            <!-- 上传 bot -->
            <div class="card">
                <h2>上传 Bot <span class="tail">POST /api/v2/arena/bots · 源码在受限子进程执行</span></h2>
                <form @submit.prevent="submitBot">
                    <div class="grid-2">
                        <div class="field">
                            <label>对战游戏</label>
                            <select v-model="upArena">
                                <option value="">— 请选择 —</option>
                                <option v-for="a in arenas" :key="a.key" :value="a.key">{{ a.display_name }} · {{ a.key }}</option>
                            </select>
                        </div>
                        <div class="field">
                            <label>Bot 名称</label>
                            <input v-model="upName" placeholder="如 alpha-bot" maxlength="128" />
                        </div>
                        <div class="field">
                            <label>语言(lang)</label>
                            <input v-model="upLang" placeholder="python" />
                        </div>
                    </div>
                    <div class="field">
                        <label>Bot 源码(按所选游戏的入口约定实现)</label>
                        <textarea class="input mono" v-model="upCode" rows="9" spellcheck="false" placeholder="def move(board, me):&#10;    ..."></textarea>
                    </div>
                    <div class="error-banner" v-if="upErr">{{ upErr }}</div>
                    <button class="btn primary" type="submit" :disabled="upBusy">{{ upBusy ? "上传中…" : "上传 Bot" }}</button>
                </form>
            </div>
        </template>

        <!-- ============ ② 约战 ============ -->
        <template v-if="tab === 'match'">
            <div class="card">
                <h2>发起约战 <span class="tail">POST /api/v2/arena/matches · 对阵入队执行</span></h2>
                <div class="field">
                    <label>对战游戏</label>
                    <select :value="mArena" @change="pickArenaForMatch($event.target.value)">
                        <option value="">— 请选择 —</option>
                        <option v-for="a in arenas" :key="a.key" :value="a.key">{{ a.display_name }}({{ a.min_bots }}–{{ a.max_bots }} 个 bot)</option>
                    </select>
                </div>

                <template v-if="mArena">
                    <div class="field">
                        <label>选择参战 bot(至少 {{ mMinBots }} 个,已选 {{ mSel.length }}){{ mOverHint ? " · " + mOverHint : "" }}</label>
                        <div class="loading-row" v-if="mBotsLoading"><span class="spinner"></span>加载 bot…</div>
                        <div class="error-banner" v-else-if="mBotsErr">{{ mBotsErr }}</div>
                        <div class="bot-pick" v-else-if="mActiveBots.length">
                            <label class="bot-pick-item" v-for="b in mActiveBots" :key="b.id">
                                <input type="checkbox" :value="b.id" v-model="mSel" />
                                <span class="bp-name"><b>{{ b.name }}</b><span class="small dim mono">#{{ b.id }}</span></span>
                                <span class="mono small dim">rating {{ b.rating }} · {{ b.wins }}胜{{ b.losses }}负{{ b.draws }}和</span>
                            </label>
                        </div>
                        <EmptyState v-else icon="🤖" desc="该游戏暂无活跃 bot —— 先到「游戏与 Bot」上传" />
                    </div>

                    <details class="alg-details cfg-fold" :open="!mConfigText">
                        <summary>对局参数 config(JSON,留空用游戏默认)</summary>
                        <textarea class="input mono" v-model="mConfigText" rows="5" spellcheck="false" placeholder='{ "games_per_pairing": 4 }'></textarea>
                    </details>

                    <div class="error-banner" v-if="mErr">{{ mErr }}</div>
                    <button class="btn primary" type="button" :disabled="!canCreateMatch || mBusy" @click="submitMatch">{{ mBusy ? "创建中…" : canCreateMatch ? "创建约战" : `还需再选 ${mMinBots - mSel.length} 个 bot` }}</button>
                </template>
                <p class="hint" v-else>选择一款对战游戏后挑选 bot 开战。</p>
            </div>

            <!-- 约战成功卡 -->
            <div class="card match-ok" v-if="lastMatch">
                <h2>约战已创建 <span class="tail">match #{{ lastMatch.id }}</span></h2>
                <div class="kv"><span class="k">对局 ID</span><span class="mono">#{{ lastMatch.id }}</span></div>
                <div class="kv"><span class="k">运行 ID</span><span class="mono">{{ lastMatch.run_id }}</span></div>
                <div class="kv"><span class="k">参战 bot</span><span class="mono">{{ (lastMatch.bot_ids || []).map((i) => "#" + i).join(" ") }}</span></div>
                <div class="kv"><span class="k">生效参数</span><span class="mono small">{{ lastMatch.config ? Object.entries(lastMatch.config).map(([k, v]) => `${k}=${v}`).join(" · ") : "—" }}</span></div>
                <button class="btn primary" type="button" @click="gotoRecords">查看对局记录 →</button>
            </div>
        </template>

        <!-- ============ ③ 对局记录 ============ -->
        <template v-if="tab === 'records'">
            <div class="card">
                <h2>对局记录 <span class="tail">{{ matches.length }} 场 · 15 秒自动刷新</span></h2>
                <div class="toolbar">
                    <div class="field">
                        <label>游戏</label>
                        <select v-model="mtArena" @change="loadMatches()">
                            <option value="">全部游戏</option>
                            <option v-for="a in arenas" :key="a.key" :value="a.key">{{ a.display_name }}</option>
                        </select>
                    </div>
                    <button class="btn small" type="button" @click="loadMatches()">刷新</button>
                </div>
                <div class="error-banner" v-if="matchesErr">{{ matchesErr }}</div>
                <div class="error-banner" v-if="detailErr">详情加载失败:{{ detailErr }}</div>
                <div class="loading-row" v-if="matchesLoading && !matches.length"><span class="spinner"></span>加载对局记录…</div>
                <div class="table-wrap" v-if="matches.length">
                    <table>
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>运行</th>
                                <th>游戏</th>
                                <th>参战 bot</th>
                                <th>状态</th>
                                <th>创建时间</th>
                                <th>结束时间</th>
                                <th>操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            <template v-for="m in matches" :key="m.id">
                                <tr :class="{ 'detail-open': detail?.match?.id === m.id }">
                                    <td class="mono">#{{ m.id }}</td>
                                    <td class="mono small">{{ m.run_id }}</td>
                                    <td class="small">{{ arenaByKey[m.arena_key]?.display_name || m.arena_key }}</td>
                                    <td class="mono small" :title="(m.bot_ids || []).map((i) => '#' + i).join(' ')">{{ botIdsText(m) }}</td>
                                    <td>
                                        <span class="badge" :class="statusBadge(m.status)">{{ statusLabel(m.status) }}</span>
                                        <span class="small dim" v-if="m.error_code"> {{ m.error_code }}</span>
                                    </td>
                                    <td class="small">{{ fmtFinished(m.created_at) }}</td>
                                    <td class="small">{{ matchFinished(m) }}</td>
                                    <td>
                                        <button class="btn small" type="button" :disabled="detailLoadingId === m.id" @click="toggleDetail(m)">{{ detail?.match?.id === m.id ? "收起" : detailLoadingId === m.id ? "加载中…" : "详情" }}</button>
                                    </td>
                                </tr>
                                <tr v-if="detail?.match?.id === m.id">
                                    <td colspan="8" class="detail-cell">
                                        <div class="hint" v-if="detailKind === 'none'">对局尚未完成,暂无结果(完成后可回放)。</div>
                                        <template v-else>
                                            <!-- 总分(arena 报告形状) -->
                                            <div v-if="detailKind === 'report'" class="score-block">
                                                <div class="hint" v-if="reportConfig">参数:{{ reportConfig }}</div>
                                                <div class="table-wrap" v-if="reportScores.length">
                                                    <table class="score-table">
                                                        <thead>
                                                            <tr><th>Bot</th><th class="num">胜</th><th class="num">负</th><th class="num">和</th></tr>
                                                        </thead>
                                                        <tbody>
                                                            <tr v-for="s in reportScores" :key="s.id">
                                                                <td><b>{{ s.name }}</b><span class="small dim mono"> #{{ s.id }}</span></td>
                                                                <td class="num mono">{{ s.win }}</td>
                                                                <td class="num mono">{{ s.loss }}</td>
                                                                <td class="num mono">{{ s.draw }}</td>
                                                            </tr>
                                                        </tbody>
                                                    </table>
                                                </div>
                                            </div>

                                            <!-- 各局回放 -->
                                            <div class="game-block" v-for="(g, gi) in reportGames" :key="gi">
                                                <div class="g-head">
                                                    <b>第 {{ gi + 1 }} 局</b>
                                                    <span class="small">先手 <b :class="markInfo(g, g.first).cls">{{ markInfo(g, g.first).char }}</b> {{ botName(g.first) }}</span>
                                                    <span class="g-win">{{ gameWinnerLabel(g) }}</span>
                                                    <span class="badge feature-badge">{{ reasonLabel(g.reason) }}</span>
                                                </div>
                                                <details class="alg-details" v-if="g.moves?.length">
                                                    <summary>落子回放({{ g.moves.length }} 步)</summary>
                                                    <div class="boards">
                                                        <div class="mv" v-for="(mv, mi) in g.moves" :key="mi">
                                                        <div class="mv-cap"><template v-if="isBoard(mv)"><b :class="markInfo(g, mv.player).cls">{{ markInfo(g, mv.player).char }}</b> {{ botName(mv.player) }}</template><template v-else>第 {{ mi + 1 }} 步</template></div>
                                                        <div class="bgrid" v-if="isBoard(mv)" :style="boardStyle()">
                                                            <div v-for="(v, idx) in boardCellsOf(mv)" :key="idx" class="bcell" :class="cellCls(v, mv, idx)">{{ pieceChar(v) }}</div>
                                                        </div>
                                                            <pre class="mv-json mono" v-else>{{ gameJson(mv) }}</pre>
                                                            <div class="mv-out" :class="'oc-' + mv.outcome">{{ outcomeLabel(mv.outcome) }}</div>
                                                            <div class="mv-detail" v-if="mv.detail" :title="mv.detail">{{ mv.detail }}</div>
                                                        </div>
                                                    </div>
                                                </details>
                                                <details class="alg-details" v-else>
                                                    <summary>原始对局 JSON</summary>
                                                    <CodeBlock :code="gameJson(g)" />
                                                </details>
                                            </div>

                                            <!-- 单局 GameRecord 形状(非 arena 报告) -->
                                            <div class="game-block" v-if="detailKind === 'game'">
                                                <div class="g-head">
                                                    <b>单局结果</b>
                                                    <span class="small">先手 {{ botName(detail.result.first) }}</span>
                                                    <span class="g-win">{{ detail.result.winner != null ? botName(detail.result.winner) + " 获胜" : "平局" }}</span>
                                                    <span class="badge feature-badge">{{ reasonLabel(detail.result.reason) }}</span>
                                                </div>
                                                <div class="boards" v-if="(detail.result.moves || []).length && isBoard(detail.result.moves[0])">
                                                    <div class="mv" v-for="(mv, mi) in detail.result.moves" :key="mi">
                                                        <div class="mv-cap"><b :class="markInfo(detail.result, mv.player).cls">{{ markInfo(detail.result, mv.player).char }}</b> {{ botName(mv.player) }}</div>
                                                        <div class="bgrid" :style="boardStyle()">
                                                            <div v-for="(v, idx) in boardCellsOf(mv)" :key="idx" class="bcell" :class="cellCls(v, mv, idx)">{{ pieceChar(v) }}</div>
                                                        </div>
                                                        <div class="mv-out" :class="'oc-' + mv.outcome">{{ outcomeLabel(mv.outcome) }}</div>
                                                    </div>
                                                </div>
                                                <CodeBlock v-else :code="gameJson(detail.result)" />
                                            </div>

                                            <!-- 未知形状原样 JSON -->
                                            <CodeBlock v-if="detailKind === 'raw'" :code="rawResultText" />
                                        </template>
                                    </td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
                <EmptyState v-else-if="!matchesLoading && !matchesErr" icon="⚔️" desc="暂无对局记录 —— 去约战一局" />
            </div>
        </template>

        <!-- ============ ④ ELO 榜 ============ -->
        <template v-if="tab === 'elo'">
            <div class="card">
                <h2>ELO 榜 <span class="tail">{{ arenaByKey[eArena]?.display_name || eArena || "—" }} · 仅活跃 bot</span></h2>
                <div class="toolbar">
                    <div class="field">
                        <label>游戏</label>
                        <select :value="eArena" @change="pickEloArena($event.target.value)">
                            <option value="">— 请选择 —</option>
                            <option v-for="a in arenas" :key="a.key" :value="a.key">{{ a.display_name }}</option>
                        </select>
                    </div>
                    <button class="btn small" type="button" @click="loadLeaderboard">刷新</button>
                </div>
                <div class="error-banner" v-if="eloErr">{{ eloErr }}</div>
                <div class="loading-row" v-if="eloLoading && !board.length"><span class="spinner"></span>加载榜单…</div>
                <div class="table-wrap" v-if="board.length">
                    <table>
                        <thead>
                            <tr>
                                <th>排名</th>
                                <th>Bot</th>
                                <th class="num">Rating</th>
                                <th class="num">场次</th>
                                <th class="num">胜</th>
                                <th class="num">负</th>
                                <th class="num">和</th>
                                <th>语言</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="b in board" :key="b.id" :class="{ 'rank-top3': b.rank <= 3 }">
                                <td><Medal :rank="b.rank" /></td>
                                <td><b>{{ b.name }}</b><span class="small dim mono"> #{{ b.id }}</span></td>
                                <td class="num mono rating-cell">{{ b.rating }}</td>
                                <td class="num mono">{{ b.games }}</td>
                                <td class="num mono">{{ b.wins }}</td>
                                <td class="num mono">{{ b.losses }}</td>
                                <td class="num mono">{{ b.draws }}</td>
                                <td class="small mono">{{ b.lang || "—" }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <EmptyState v-else-if="!eloLoading && eArena && !eloErr" icon="🏆" desc="该游戏暂无活跃 bot 的排位数据" />
                <EmptyState v-else-if="!eArena" icon="🎮" desc="选择一款对战游戏查看 ELO 榜" />
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

.tabs-row {
    margin-bottom: 16px;
}

.dim {
    color: var(--text-faint);
}

.small {
    font-size: 12.5px;
}

.row-actions {
    display: inline-flex;
    gap: 6px;
}

/* 目录卡 / 约战卡 */
.contract-fold,
.cfg-fold {
    margin: 8px 0 10px;
}

/* bot 多选 */
.bot-pick {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 8px;
}

.bot-pick-item {
    display: flex;
    align-items: center;
    gap: 9px;
    background: var(--card-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px 12px;
    cursor: pointer;
    transition: border-color .15s;
}

.bot-pick-item:hover {
    border-color: var(--accent);
}

.bot-pick-item:has(input:checked) {
    border-color: var(--accent);
    box-shadow: inset 0 0 12px rgba(34, 211, 238, .08);
}

.bot-pick-item .bp-name {
    display: flex;
    flex-direction: column;
    line-height: 1.3;
    min-width: 0;
    flex: 1;
}

/* 约战成功卡 */
.match-ok {
    border-color: rgba(52, 211, 153, .45);
}

/* 对局详情展开行 */
.detail-open td {
    background: var(--row-hover);
}

.detail-cell,
.code-cell {
    white-space: normal;
    background: var(--card-2);
}

.score-block {
    margin-bottom: 10px;
}

.score-table {
    max-width: 420px;
}

.game-block {
    border: 1px dashed var(--border-strong);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 10px;
}

.g-head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 6px;
}

.g-win {
    color: var(--good);
    font-weight: 700;
    font-size: 13px;
}

/* 井字棋盘回放 */
.boards {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    padding: 4px 0;
}

.mv {
    text-align: center;
    font-size: 11.5px;
    color: var(--text-dim);
}

.mv-cap {
    margin-bottom: 4px;
    white-space: nowrap;
}

.mv-cap b {
    font-size: 13px;
}

.mv-out {
    margin-top: 3px;
    font-weight: 700;
}

.mv-out.oc-ok {
    color: var(--text-faint);
}

.mv-out.oc-illegal,
.mv-out.oc-timeout,
.mv-out.oc-crash,
.mv-out.oc-hit {
    color: var(--bad);
}

.mv-detail {
    max-width: 110px;
    margin: 0 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-faint);
}

.mv-json {
    margin: 0;
    max-width: 110px;
    max-height: 90px;
    overflow: auto;
    text-align: left;
    font-size: 10px;
    color: var(--text-dim);
}

/* 通用棋盘网格(尺寸由 board_shape 内联提供,井字棋 3×3 / 四子棋 7×6 / 15×15 均适配) */
.bgrid {
    display: grid;
    gap: 2px;
    padding: 2px;
    background: var(--border);
    border-radius: 7px;
    width: max-content;
    margin: 0 auto;
}

.bcell {
    background: var(--card);
    border-radius: 4px;
    display: grid;
    place-items: center;
    font-weight: 800;
    font-size: 15px;
}

.bcell.x {
    color: var(--accent);
}

.bcell.o {
    color: var(--accent-2);
}

.bcell.last {
    box-shadow: inset 0 0 0 2px var(--good);
}

.bcell.bad {
    box-shadow: inset 0 0 0 2px var(--bad);
}

/* 炸弹人等 dict 视图游戏的格子配色(经目录 cell_classes 协商) */
.bcell.wall {
    color: var(--text-faint);
    background: var(--border);
}

.bcell.soft {
    color: var(--text-dim);
    background: var(--card-2);
}

.bcell.bomb {
    color: var(--warn);
}

.bcell.flame {
    color: var(--bad);
}

/* 3/4 号玩家配色(多人同局,回放头部 mk-* 与棋盘格 p3/p4 同色系) */
.mk-p3,
.bcell.p3 {
    color: var(--warn);
}

.mk-p4,
.bcell.p4 {
    color: var(--good);
}

/* ELO 榜 */
.rating-cell {
    font-weight: 800;
}

.mk-x {
    color: var(--accent);
}

.mk-o {
    color: var(--accent-2);
}
</style>
