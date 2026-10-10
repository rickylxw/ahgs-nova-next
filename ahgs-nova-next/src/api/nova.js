/* ============ AHGS NOVA Next · Nova v2 端点 ============
 * 401 刷新与重放由 api/client.js 统一处理(经 session store 注册的回调)。
 */
import { api } from "./client";

/* ---- 认证(匿名) ---- */
export const login = (username, password) =>
    api("/api/v2/auth/login", { method: "POST", body: { username, password }, session: null });

export const register = (username, password, display_name = "") =>
    api("/api/v2/auth/register", { method: "POST", body: { username, password, display_name }, session: null });

export const refresh = (refresh_token) =>
    api("/api/v2/auth/refresh", { method: "POST", body: { refresh_token }, session: null });

export const logout = (refresh_token) => api("/api/v2/auth/logout", { method: "POST", body: { refresh_token } });

export const me = () => api("/api/v2/auth/me");

/* ---- 元信息 ---- */
export const health = () => api("/api/health", { session: null });

/* ---- 预筛 ---- */
export const prescreen = (body) => api("/api/v2/prescreen", { method: "POST", body });

/* ---- 种子库 ---- */
export const listSeeds = (params = {}) => api("/api/v2/seeds?" + qs(params));
export const getSeed = (id) => api(`/api/v2/seeds/${id}`);
export const createSeed = (body) => api("/api/v2/seeds", { method: "POST", body });
export const deleteSeed = (id) => api(`/api/v2/seeds/${id}`, { method: "DELETE" });

/* ---- 数据集 ---- */
export const listDatasets = (problemKey) => api(`/api/v2/problems/${problemKey}/datasets`);
export const uploadDataset = (problemKey, body) => api(`/api/v2/problems/${problemKey}/datasets`, { method: "POST", body });

/* ---- Arena 对战 ---- */
export const listArenas = () => api("/api/v2/arena/arenas", { session: null });
export const listBots = (params = {}) => api("/api/v2/arena/bots?" + qs(params));
export const createBot = (body) => api("/api/v2/arena/bots", { method: "POST", body });
export const getBot = (id) => api(`/api/v2/arena/bots/${id}`);
export const deactivateBot = (id) => api(`/api/v2/arena/bots/${id}/deactivate`, { method: "POST", body: {} });
export const listMatches = (params = {}) => api("/api/v2/arena/matches?" + qs(params));
export const createMatch = (body) => api("/api/v2/arena/matches", { method: "POST", body });
export const getMatch = (id) => api(`/api/v2/arena/matches/${id}`);
export const arenaLeaderboard = (arenaKey) => api(`/api/v2/arena/leaderboard/${arenaKey}`);

/* ---- 管理端 ---- */
export const putProblem = (key, body) => api(`/api/v2/admin/problems/${key}`, { method: "PUT", body });
export const setQueuePaused = (body) => api("/api/v2/admin/queue/pause", { method: "POST", body });
export const auditLog = (limit = 100) => api(`/api/v2/admin/audit?limit=${limit}`);
export const llmProviders = () => api("/api/v2/admin/llm/providers");
export const llmChat = (body) => api("/api/v2/admin/llm/chat", { method: "POST", body });
export const llmCalls = (limit = 50) => api(`/api/v2/admin/llm/calls?limit=${limit}`);
export const reloadArenaPlugins = () => api("/api/v2/admin/arenas/reload-plugins", { method: "POST", body: {} });

function qs(params) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
        if (v === undefined || v === null || v === "") continue;
        sp.set(k, String(v));
    }
    const s = sp.toString();
    return s ? s : "";
}
