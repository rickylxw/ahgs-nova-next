/* ============ AHGS NOVA Next · HTTP 客户端 ============ */
import { DEFAULT_API, LS } from "../lib/constants";

export function apiBase() {
    return (localStorage.getItem(LS.api) || DEFAULT_API).replace(/\/+$/, "");
}

/** WebSocket 基地址(http→ws);留空时按当前页面同源 */
export function wsBase() {
    return (apiBase() || window.location.origin).replace(/^http/, "ws");
}

/** 当前会话令牌(单一 Nova 会话) */
export function token() {
    return localStorage.getItem(LS.novaAccess) || "";
}

/** 由 session store 注册的刷新回调(避免 client ↔ store 循环依赖) */
let refreshHandler = null;
export function setTokenRefreshHandler(fn) {
    refreshHandler = fn;
}

export class ApiError extends Error {
    /**
     * @param {number} status
     * @param {string} message  已本地化的消息,直接展示
     * @param {{code?: string, retryable?: boolean, detail?: any}} [shape] v2 结构化信封
     */
    constructor(status, message, { code = "", retryable = false, detail = null } = {}) {
        super(message);
        this.status = status;
        this.code = code; // v2 结构化错误码;官方契约端点为空串
        this.retryable = retryable;
        this.detail = detail;
    }
}

/**
 * 统一请求入口。session: "nova"(默认,带会话令牌)| null(匿名)。
 * v2 错误按 {code,message,retryable,detail} 信封解析;官方契约端点退回 detail/message。
 * body 传 FormData 时不设 Content-Type(浏览器自动带 boundary)。
 * 401(AUTH_REQUIRED)时先经刷新回调续期并重放一次;最终失败广播 next:session-expired。
 */
export async function api(path, { method = "GET", body, session = "nova", token: tok, headers, _retried } = {}) {
    const t = tok ?? (session === "nova" ? token() : "");
    const h = { ...(headers || {}) };
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;
    if (body !== undefined && !isForm) h["Content-Type"] = "application/json";
    if (t) h.Authorization = `Bearer ${t}`;
    let resp;
    try {
        resp = await fetch(apiBase() + path, {
            method,
            headers: h,
            body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
        });
    } catch {
        throw new ApiError(0, "网络错误:无法连接到 " + (apiBase() || "当前同源后端") + "(可在右上角设置里检查接口地址)");
    }
    if (!resp.ok) {
        const err = await parseError(resp);
        if (resp.status === 401 && t && !_retried && err.code === "AUTH_REQUIRED" && refreshHandler) {
            const ok = await refreshHandler();
            if (ok) return api(path, { method, body, session, token: tok, headers, _retried: true });
        }
        if (resp.status === 401 && t) {
            try {
                window.dispatchEvent(new CustomEvent("next:session-expired", { detail: err }));
            } catch { /* ignore */ }
        }
        throw err;
    }
    if (resp.status === 204) return null;
    const ct = resp.headers.get("content-type") || "";
    if (!ct.includes("application/json")) return resp; // 文件流(数据集下载等)
    return resp.json();
}

async function parseError(resp) {
    let message = resp.statusText || String(resp.status);
    let code = "";
    let retryable = false;
    let detail = null;
    try {
        const j = await resp.json();
        if (j && typeof j === "object" && typeof j.code === "string" && typeof j.message === "string") {
            code = j.code;
            message = j.message;
            retryable = !!j.retryable;
            detail = j.detail ?? null;
        } else if (j && typeof j === "object") {
            message = j.detail || j.message || JSON.stringify(j);
        } else {
            message = String(j);
        }
    } catch { /* 保留 statusText */ }
    return new ApiError(resp.status, message, { code, retryable, detail });
}
