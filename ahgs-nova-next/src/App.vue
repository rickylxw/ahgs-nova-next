<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, apiBase, setTokenRefreshHandler } from "./api/client";
import { DEFAULT_API, APP_VERSION, REPO_URL } from "./lib/constants";
import { useSessionStore } from "./stores/session";
import { useProblemsStore } from "./stores/problems";
import { useUiStore, closeDrawer, toast } from "./stores/ui";
import { fullName } from "./lib/format";
import Avatar from "./components/Avatar.vue";
import DrawerHost from "./components/drawers/DrawerHost.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const problems = useProblemsStore();
const ui = useUiStore();

const ready = ref(false);
const bootErr = ref("");
const settingsOpen = ref(false);
const userMenuOpen = ref(false);
const navOpen = ref(false);
const apiInput = ref(apiBase());
const apiMsg = ref("");
const year = new Date().getFullYear();

/** 顶级分区:AI 进化 / 对战竞技(管理端仅管理员可见)。
 *  进化板块用左侧分组侧边栏;对战/管理端是单页,无侧边栏。 */
const SECTIONS = [
    {
        key: "evolution",
        label: "AI 进化",
        defaultPath: "/dashboard",
        sidebar: [
            { label: "", items: [{ name: "dashboard", label: "总览" }] },
            { label: "榜单", items: [{ name: "leaderboard", label: "排行榜" }, { name: "live", label: "实时流" }] },
            { label: "进化工作台", items: [{ name: "evo", label: "发起进化" }, { name: "curve", label: "曲线分析" }, { name: "compare", label: "对比" }] },
            { label: "题目与数据", items: [{ name: "cprob", label: "自定义问题" }, { name: "seeds", label: "种子库" }, { name: "datasets", label: "数据集" }, { name: "prescreen", label: "预筛" }] },
            { label: "个人", items: [{ name: "mine", label: "我的" }] },
        ],
    },
    { key: "arena", label: "对战竞技", defaultPath: "/arena", sidebar: [] },
    { key: "admin", label: "管理端", adminOnly: true, defaultPath: "/admin", sidebar: [] },
];

const routeSection = computed(() => route.meta.section || "evolution");
const shownSections = computed(() => SECTIONS.filter(s => !s.adminOnly || session.isAdmin));
/** 当前分区是否带侧边栏(仅 AI 进化) */
const sidebarGroups = computed(() =>
    routeSection.value === "evolution" ? SECTIONS[0].sidebar : null
);

function switchSection(s) {
    if (routeSection.value !== s.key) router.push(s.defaultPath);
}

const displayUser = computed(() => session.user);

/** 页脚接口地址展示/链接(模板里不能直接用 location —— 编译器会加 _ctx. 前缀) */
const apiHref = computed(() => apiBase() || window.location.href);
const apiLabel = computed(() => apiBase() || "同源");

onMounted(() => {
    ui.applyTheme(ui.theme);
    // 令牌刷新回调注册给 HTTP 客户端(401 → 续期重放一次)
    setTokenRefreshHandler(() => session.refresh());
    // 启动即校验本地 JWT:已过期直接清槽引导重登(不等首个 401)
    const exp = session.expiry;
    if (session.authed && exp != null && Date.now() >= exp) {
        session.clear();
        toast("登录已过期,请重新登录", "err");
    }
    session.verify();
    loadBoot();
    window.addEventListener("next:session-expired", onSessionExpired);
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    // 长驻页面:令牌临近过期自动刷新
    timer = setInterval(() => {
        if (session.authed && session.expiry != null && session.expiry - Date.now() < 5 * 60 * 1000) {
            session.refresh();
        }
        const offExp = session.expiry;
        if (session.authed && offExp != null && Date.now() >= offExp) onSessionExpired();
    }, 60_000);
});

let timer = null;
onUnmounted(() => {
    window.removeEventListener("next:session-expired", onSessionExpired);
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("click", onClick);
    if (timer) clearInterval(timer);
});

async function loadBoot() {
    try {
        await problems.load();
        ready.value = true;
    } catch (e) {
        bootErr.value = e.message;
        ready.value = true;
    }
}

/** 会话失效(带令牌请求 401 且刷新失败 / 主动检出过期):清槽并引导重登 */
function onSessionExpired() {
    if (!session.authed) return;
    session.clear();
    toast("登录已失效,请重新登录", "err");
    if (route.meta.requires) router.push({ path: "/login", query: { redirect: route.fullPath } });
}

async function saveApi() {
    const v = apiInput.value.trim().replace(/\/+$/, "");
    if (v) localStorage.setItem("next_api_base", v);
    else localStorage.removeItem("next_api_base");
    apiMsg.value = "测试连接中…";
    try {
        await api("/api/problems", { session: null });
        apiMsg.value = "✅ 连接成功";
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        apiMsg.value = "❌ " + e.message;
    }
}

function resetApi() {
    localStorage.removeItem("next_api_base");
    location.reload();
}

function goLogin() {
    userMenuOpen.value = false;
    router.push({ path: "/login", query: { redirect: route.fullPath } });
}

async function doLogout() {
    userMenuOpen.value = false;
    await session.logout();
    toast("已退出登录");
    if (route.meta.requires) router.push("/dashboard");
}

const onKey = ev => {
    if (ev.key === "Escape") {
        closeDrawer();
        settingsOpen.value = false;
        userMenuOpen.value = false;
        navOpen.value = false;
    }
};
const onClick = ev => {
    if (settingsOpen.value && !ev.target.closest(".popover") && !ev.target.closest(".icon-btn"))
        settingsOpen.value = false;
    if (userMenuOpen.value && !ev.target.closest(".popover") && !ev.target.closest(".user-chip"))
        userMenuOpen.value = false;
    if (navOpen.value && !ev.target.closest("#sidebar") && !ev.target.closest(".nav-toggle"))
        navOpen.value = false;
};
</script>

<template>
    <div id="bg-glow" aria-hidden="true"></div>
    <header id="topbar">
        <a class="brand" href="#/dashboard">
            <span class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 32 32" width="22" height="22">
                    <path d="M5 24 L12 9 L17 19 L21 12 L27 24" stroke="currentColor" stroke-width="3" fill="none"
                        stroke-linecap="round" stroke-linejoin="round" />
                </svg>
            </span>
            <span class="brand-text">AHGS<em>NOVA</em></span>
            <span class="brand-sub">Next</span>
        </a>
        <div class="sec-row" role="tablist" aria-label="板块切换">
            <button v-for="s in shownSections" :key="s.key" class="sec-chip"
                :class="{ on: routeSection === s.key }" type="button"
                @click="switchSection(s); navOpen = false">{{ s.label }}</button>
        </div>
        <div class="topbar-right">
            <button class="icon-btn" title="接口设置" @click="settingsOpen = !settingsOpen">
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round">
                    <circle cx="12" cy="12" r="3" />
                    <path
                        d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
            </button>
            <button class="icon-btn" title="切换主题" @click="ui.toggleTheme()">
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round">
                    <template v-if="ui.theme === 'dark'">
                        <circle cx="12" cy="12" r="4" />
                        <path
                            d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                    </template>
                    <template v-else>
                        <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z" />
                    </template>
                </svg>
            </button>
            <button v-if="!displayUser" class="btn-login" @click="goLogin">登录 / 注册</button>
            <div v-else class="user-chip link-ish" title="账户菜单" @click="userMenuOpen = !userMenuOpen">
                <Avatar :user="displayUser" :size="26" /><b>{{ fullName(displayUser) }}</b>
            </div>
        </div>
        <button v-if="sidebarGroups" class="icon-btn nav-toggle" title="导航菜单" :aria-expanded="navOpen" @click="navOpen = !navOpen">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round">
                <template v-if="!navOpen">
                    <path d="M4 6h16M4 12h16M4 18h16" />
                </template>
                <template v-else>
                    <path d="M6 6l12 12M18 6L6 18" />
                </template>
            </svg>
        </button>
        <div v-if="settingsOpen" class="popover" style="right: 16px; top: 58px" @click.stop>
            <h4>接口设置 <span class="hint">v{{ APP_VERSION }}</span></h4>
            <div class="field">
                <label>API 基地址</label>
                <input v-model="apiInput" :placeholder="'留空 = 同源(默认 ' + (DEFAULT_API || '同源') + ')'" />
            </div>
            <div class="hint" style="margin: 4px 0 10px">
                开发模式下默认同源,经 vite 代理访问本地后端(免 CORS);部署后可填完整地址,如
                <span class="mono">http://127.0.0.1:8000</span>。
            </div>
            <div style="display: flex; gap: 8px">
                <button class="btn primary" style="flex: 1" @click="saveApi">保存并测试</button>
                <button class="btn" @click="resetApi">恢复默认</button>
            </div>
            <div class="hint" style="margin-top: 8px">{{ apiMsg }}</div>
        </div>
        <div v-if="userMenuOpen && displayUser" class="popover" style="right: 16px; top: 58px" @click.stop>
            <h4>账户</h4>
            <div class="user-cell" style="margin-bottom: 12px">
                <Avatar :user="displayUser" />
                <div class="u-name">
                    <span class="u-main">{{ fullName(displayUser) }}</span>
                    <span class="u-sub mono">{{ displayUser.username }}</span>
                </div>
            </div>
            <div class="field">
                <label>会话状态</label>
                <div class="badge-row">
                    <span class="badge" :class="session.authed ? 'src-local' : 'src-api'">
                        {{ session.authed ? "✓ 已登录 · " + fullName(session.user) : "未登录" }}</span>
                    <span v-if="session.isAdmin" class="badge src-api">管理员</span>
                </div>
            </div>
            <div style="display: flex; flex-direction: column; gap: 8px">
                <button class="btn" @click="userMenuOpen = false; router.push('/mine')">👤 我的空间</button>
                <button v-if="!session.authed" class="btn" @click="goLogin">🔑 登录</button>
                <button class="btn danger" @click="doLogout">🚪 退出登录</button>
            </div>
        </div>
    </header>

    <div id="shell">
        <aside v-if="sidebarGroups" id="sidebar" :class="{ open: navOpen }" aria-label="AI 进化导航">
            <template v-for="g in sidebarGroups" :key="g.label">
                <div v-if="g.label" class="side-label">{{ g.label }}</div>
                <a v-for="item in g.items" :key="item.name" class="side-item"
                    :class="{ on: route.name === item.name }" :href="'#/' + item.name"
                    @click="navOpen = false">{{ item.label }}</a>
            </template>
        </aside>
        <main id="view" class="view">
            <div v-if="!ready" class="card">
                <div class="loading-row"><span class="spinner"></span>加载中…</div>
            </div>
            <div v-else-if="bootErr" class="card">
                <div class="error-banner">无法连接平台接口（{{ apiBase() || "同源" }}）：{{ bootErr }}</div>
                <p class="hint">请确认后端已启动(<span class="mono">python serve.py --port 8000</span>),或点击右上角 ⚙ 修改接口地址。</p>
            </div>
            <RouterView v-else />
        </main>
    </div>

    <footer id="footer">
        <span>AHGS NOVA · Next 版 v{{ APP_VERSION }} · 兼容层 + Nova v2 全量前端</span>
        <span>© {{ year }} Rickylxw, Midairlogn ·
            <a :href="REPO_URL" target="_blank" rel="noopener">GitHub</a> · GPLv3</span>
        <span id="footer-api" class="mono"><a :href="apiHref" target="_blank" rel="noopener">{{ apiLabel }}</a></span>
    </footer>

    <DrawerHost />

    <div class="toast-root" aria-live="polite">
        <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.msg }}</div>
    </div>
</template>
