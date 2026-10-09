/* ============ AHGS NOVA Next · 题目注册表(兼容层) ============ */
import { defineStore } from "pinia";
import { api } from "../api/client";

export const useProblemsStore = defineStore("problems", {
    state: () => ({
        list: [],
        loaded: false,
    }),
    getters: {
        byKey: (s) => Object.fromEntries(s.list.map((p) => [p.key, p])),
    },
    actions: {
        async load(force = false) {
            if (this.loaded && !force) return;
            const r = await api("/api/problems");
            this.list = r.problems ?? [];
            this.loaded = true;
        },
    },
});
