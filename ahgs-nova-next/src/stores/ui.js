/* ============ AHGS NOVA Next · UI 全局状态(主题/提示/抽屉) ============ */
import { defineStore } from "pinia";
import { LS } from "../lib/constants";

let toastSeq = 0;

export const useUiStore = defineStore("ui", {
    state: () => ({
        theme: localStorage.getItem(LS.theme) || "dark",
        toasts: [],
        /** 抽屉:{ comp: "sub-detail"|"user-profile"|"heur-detail", props } 或 null */
        drawer: null,
    }),
    actions: {
        applyTheme(theme) {
            this.theme = theme;
            document.documentElement.dataset.theme = theme;
            localStorage.setItem(LS.theme, theme);
        },
        toggleTheme() {
            this.applyTheme(this.theme === "dark" ? "light" : "dark");
        },
        pushToast(msg, kind = "") {
            const id = ++toastSeq;
            this.toasts.push({ id, msg, kind });
            setTimeout(() => {
                const i = this.toasts.findIndex((t) => t.id === id);
                if (i >= 0) this.toasts.splice(i, 1);
            }, 2600);
        },
        openDrawer(comp, props = {}) {
            this.drawer = { comp, props };
        },
        closeDrawer() {
            this.drawer = null;
        },
    },
});

/* ---- 独立动作:供非组件模块(如 format.js)与视图直接调用 ---- */
export function toast(msg, kind = "") {
    useUiStore().pushToast(msg, kind);
}

export function openSubmissionDrawer(id) {
    useUiStore().openDrawer("sub-detail", { sid: String(id) });
}

export function openUserDrawer(uid) {
    useUiStore().openDrawer("user-profile", { uid });
}

export function openHeurDrawer(h, gen, idx) {
    useUiStore().openDrawer("heur-detail", { h, gen, idx });
}

export function closeDrawer() {
    useUiStore().closeDrawer();
}
