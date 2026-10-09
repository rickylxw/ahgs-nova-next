/* ============ AHGS NOVA Next · 兼容层资料端点(standalone 同库同 JWT) ============
 * 登录/注册已统一走 /api/v2/auth/*(见 nova.js);这里只保留兼容层的
 * 资料维护端点(/api/auth/me PATCH、改密),供"我的"页使用。
 */
import { api } from "./client";

export const patchMe = (body) => api("/api/auth/me", { method: "PATCH", body });

export const changePassword = (old_password, new_password) =>
    api("/api/auth/me/password", { method: "POST", body: { old_password, new_password } });
