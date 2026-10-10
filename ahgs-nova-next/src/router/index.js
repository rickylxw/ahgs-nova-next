/* ============ AHGS NOVA Next · 路由 ============
 * 顶级分区(meta.section):evolution = AI 进化 | arena = 对战竞技 | admin = 管理端。
 */
import { createRouter, createWebHashHistory } from "vue-router";
import { useSessionStore } from "../stores/session";
import { useUiStore } from "../stores/ui";

const routes = [
    { path: "/", redirect: "/dashboard" },
    { path: "/dashboard", name: "dashboard", component: () => import("../views/DashboardView.vue"), meta: { title: "总览", section: "evolution" } },
    { path: "/leaderboard", name: "leaderboard", component: () => import("../views/LeaderboardView.vue"), meta: { title: "排行榜", section: "evolution" } },
    { path: "/live", name: "live", component: () => import("../views/LiveView.vue"), meta: { title: "实时流", section: "evolution" } },
    { path: "/evo", name: "evo", component: () => import("../views/EvolveView.vue"), meta: { title: "进化", requires: "nova", section: "evolution" } },
    { path: "/cprob", name: "cprob", component: () => import("../views/CprobView.vue"), meta: { title: "自定义问题", requires: "nova", section: "evolution" } },
    { path: "/curve", name: "curve", component: () => import("../views/CurveView.vue"), meta: { title: "进化分析", section: "evolution" } },
    { path: "/compare", name: "compare", component: () => import("../views/CompareView.vue"), meta: { title: "对比", section: "evolution" } },
    { path: "/mine", name: "mine", component: () => import("../views/MineView.vue"), meta: { title: "我的", requires: "nova", section: "evolution" } },
    { path: "/seeds", name: "seeds", component: () => import("../views/SeedsView.vue"), meta: { title: "种子库", requires: "nova", section: "evolution" } },
    { path: "/datasets", name: "datasets", component: () => import("../views/DatasetsView.vue"), meta: { title: "数据集", requires: "nova", section: "evolution" } },
    { path: "/prescreen", name: "prescreen", component: () => import("../views/PrescreenView.vue"), meta: { title: "预筛", requires: "nova", section: "evolution" } },
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { title: "登录" } },
    { path: "/arena", name: "arena", component: () => import("../views/ArenaView.vue"), meta: { title: "对战", requires: "nova", section: "arena" } },
    { path: "/admin", name: "admin", component: () => import("../views/AdminView.vue"), meta: { title: "管理端", requires: "nova", admin: true, section: "admin" } },
    { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
];

export const SECTION_LABEL = {
    evolution: "AI 进化",
    arena: "对战竞技",
    admin: "管理端",
};

export const router = createRouter({
    history: createWebHashHistory(),
    routes,
    scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach((to) => {
    const s = useSessionStore();
    if (to.meta.requires === "nova" && !s.authed) {
        return { path: "/login", query: { redirect: to.fullPath, why: "auth" } };
    }
    if (to.meta.admin && !s.isAdmin) {
        useUiStore().toast("该页面需要 Nova 管理员账号", "err");
        return { path: "/dashboard" };
    }
});

router.afterEach((to) => {
    const sec = to.meta.section ? SECTION_LABEL[to.meta.section] + " · " : "";
    document.title = (to.meta.title ? to.meta.title + " · " : "") + sec + "AHGS NOVA Next";
});
