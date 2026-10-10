/* ============ AHGS NOVA Next · 会话(单一 Nova 会话) ============
 * 后端独立运行,不再有官方平台双会话:登录即 /api/v2/auth/*,兼容层端点
 * (standalone 模式)接受同一套 JWT。
 */
import { defineStore } from "pinia";
import { LS } from "../lib/constants";
import * as compat from "../api/compat";
import * as nova from "../api/nova";

/** 解析 JWT payload.exp(毫秒);非 JWT / 无 exp 返回 null */
function jwtExp(tok) {
    const part = (tok || "").split(".")[1];
    if (!part) return null;
    try {
        let b64 = part.replace(/-/g, "+").replace(/_/g, "/");
        while (b64.length % 4) b64 += "=";
        const payload = JSON.parse(atob(b64));
        return typeof payload.exp === "number" ? payload.exp * 1000 : null;
    } catch {
        return null;
    }
}

function readJson(key) {
    try {
        return JSON.parse(localStorage.getItem(key) || "null");
    } catch {
        return null;
    }
}

/** 刷新请求并发去重(refresh 单次轮换,重复触发只会发一次) */
let refreshing = null;

export const useSessionStore = defineStore("session", {
    state: () => ({
        access: localStorage.getItem(LS.novaAccess) || "",
        refresh: localStorage.getItem(LS.novaRefresh) || "",
        user: readJson(LS.novaUser),
    }),

    getters: {
        authed: (s) => !!s.access,
        isAdmin: (s) => s.user?.role === "admin",
        expiry: (s) => jwtExp(s.access),
    },

    actions: {
        setSession(access, refreshTok, user) {
            if (access) {
                this.access = access;
                localStorage.setItem(LS.novaAccess, access);
            }
            if (refreshTok) {
                this.refresh = refreshTok;
                localStorage.setItem(LS.novaRefresh, refreshTok);
            }
            if (user) {
                this.user = user;
                localStorage.setItem(LS.novaUser, JSON.stringify(user));
            }
        },
        clear() {
            this.access = "";
            this.refresh = "";
            this.user = null;
            localStorage.removeItem(LS.novaAccess);
            localStorage.removeItem(LS.novaRefresh);
            localStorage.removeItem(LS.novaUser);
        },

        async login(username, password) {
            const r = await nova.login(username, password);
            this.setSession(r.access_token, r.refresh_token, r.user);
            return r.user;
        },
        async register(username, password, display_name = "") {
            const r = await nova.register(username, password, display_name);
            return r; // {id, username, display_name}
        },

        /** 刷新令牌(refresh 单次轮换;失败即清槽并广播) */
        refresh() {
            if (refreshing) return refreshing;
            const rt = this.refresh;
            if (!rt) return Promise.resolve(false);
            refreshing = (async () => {
                try {
                    const r = await nova.refresh(rt);
                    this.setSession(r.access_token, r.refresh_token, r.user ?? this.user);
                    return true;
                } catch {
                    this.clear();
                    try {
                        window.dispatchEvent(new CustomEvent("next:session-expired"));
                    } catch { /* ignore */ }
                    return false;
                } finally {
                    refreshing = null;
                }
            })();
            return refreshing;
        },

        /** 登出:best-effort 吊销刷新令牌,再清槽 */
        async logout() {
            if (this.access && this.refresh) {
                try {
                    await nova.logout(this.refresh);
                } catch { /* 已失效也无妨 */ }
            }
            this.clear();
        },

        /** 启动时校验会话(拉最新用户信息;失效由 401 中央刷新/清槽处理) */
        verify() {
            if (!this.access) return;
            nova.me()
                .then((u) => this.setSession(null, null, u))
                .catch(() => { /* 刷新失败已清槽 */ });
        },

        /** 资料更新后回写本地用户(MineView 用) */
        setUser(u) {
            if (u) this.setSession(null, null, u);
        },

        /** 改密(兼容层端点,同一 JWT) */
        changePassword(old_password, new_password) {
            return compat.changePassword(old_password, new_password);
        },
    },
});
