<script setup>
/* ============ AHGS NOVA Next · 登录/注册(单一 Nova 会话) ============
 * 后端独立运行:登录即 /api/v2/auth/login,兼容层端点接受同一套 JWT。
 */
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useSessionStore } from "../stores/session";
import { toast } from "../stores/ui";
import { LS, V2_ROLE_LABEL } from "../lib/constants";
import { fullName, fmtTime } from "../lib/format";
import Avatar from "../components/Avatar.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();

const redirect = typeof route.query.redirect === "string" && route.query.redirect ? route.query.redirect : "/dashboard";
const why = typeof route.query.why === "string" ? route.query.why : "";

/* ---------- 表单(登录 / 注册) ---------- */
const mode = ref("login"); // login | register
const username = ref("");
const password = ref("");
const displayName = ref("");
const remember = ref(true);
const showPw = ref(false);
const err = ref(null); // string | ApiError
const busy = ref(false);

onMounted(() => {
    username.value = readRemember();
});

/** 只存用户名,绝不存密码(旧版 SFC 在同 key 下存过 JSON,读取时兼容) */
function readRemember() {
    try {
        const raw = localStorage.getItem(LS.remember);
        if (!raw) return "";
        try {
            const j = JSON.parse(raw);
            if (j && typeof j === "object" && typeof j.u === "string") return j.u;
        } catch { /* 纯文本用户名 */ }
        return raw;
    } catch { return ""; }
}

function persistRemember() {
    try {
        if (remember.value && username.value.trim()) localStorage.setItem(LS.remember, username.value.trim());
        else localStorage.removeItem(LS.remember);
    } catch { /* ignore */ }
}

/** v2 结构化错误的本地化文案(直接展示 e.message,AUTH_LOCKED / RATE_LIMITED 补充时间) */
function errText(e) {
    if (!e) return "";
    if (typeof e === "string") return e;
    const c = e.code || "";
    if (c === "AUTH_LOCKED") {
        const d = fmtTime(e.detail?.unlock_at);
        return d && d !== "—" ? `失败次数过多,账号已临时锁定,预计 ${d} 自动解锁` : (e.message || "登录失败");
    }
    if (c === "RATE_LIMITED") {
        const ep = Number(e.detail?.retry_after_epoch);
        const at = isFinite(ep) && ep > 0 ? fmtTime(new Date(ep * 1000).toISOString()) : "";
        return at ? `${e.message || "操作过于频繁"}(预计 ${at} 后可重试)` : (e.message || "操作过于频繁");
    }
    return e.message || "请求失败";
}

function goNext() {
    router.push(redirect);
}

function switchMode(m) {
    mode.value = m;
    err.value = null;
}

async function submit() {
    err.value = null;
    if (!username.value.trim() || !password.value) {
        err.value = "请填写用户名和密码";
        return;
    }
    if (mode.value === "register" && password.value.length < 8) {
        err.value = "密码至少 8 位";
        return;
    }
    busy.value = true;
    try {
        if (mode.value === "register") {
            await session.register(username.value.trim(), password.value, displayName.value.trim());
        }
        await session.login(username.value.trim(), password.value);
        persistRemember();
        toast(`欢迎,${fullName(session.user)}`, "ok");
        goNext();
    } catch (e) {
        // 注册冲突(USERNAME_TAKEN)/ 限速锁定(RATE_LIMITED / AUTH_LOCKED)在此直接呈现
        err.value = e;
    } finally {
        busy.value = false;
    }
}
</script>

<template>
    <div class="login-wrap">
        <div class="login-brand">
            <h1>AHGS NOVA Next</h1>
            <p class="hint">登录后使用 Nova 平台的全部能力</p>
        </div>

        <!-- 已登录:展示当前会话 + 继续 -->
        <div class="card" v-if="session.authed">
            <h2>当前会话</h2>
            <div class="login-me">
                <Avatar :user="session.user" :size="36" />
                <div>
                    <div class="u-name">{{ fullName(session.user) }}</div>
                    <div class="u-sub" v-if="session.user">{{ V2_ROLE_LABEL[session.user.role] || session.user.role }}</div>
                </div>
            </div>
            <div class="kv"><span class="k">会话状态</span><span class="v">✓ 已登录</span></div>
            <button class="btn primary login-btn" type="button" @click="goNext">继续</button>
        </div>

        <!-- 跳转原因提示 -->
        <div class="notice" v-if="why && !session.authed">该页面需要登录后才能继续。</div>

        <!-- 主表单 -->
        <div class="card">
            <h2>{{ mode === "register" ? "注册新账号" : "登录" }}</h2>
            <div class="chip-row" role="tablist">
                <button class="chip" :class="{ on: mode === 'login' }" type="button" @click="switchMode('login')">登录</button>
                <button class="chip" :class="{ on: mode === 'register' }" type="button" @click="switchMode('register')">注册</button>
            </div>
            <form @submit.prevent="submit">
                <div class="field">
                    <label>用户名</label>
                    <input v-model="username" autocomplete="username" placeholder="用户名(3-64 位,字母数字_-)" />
                </div>
                <div class="field" v-if="mode === 'register'">
                    <label>昵称(display_name,可选)</label>
                    <input v-model="displayName" autocomplete="nickname" />
                </div>
                <div class="field">
                    <label>密码</label>
                    <div class="pw-wrap"><input v-model="password" :type="showPw ? 'text' : 'password'" autocomplete="current-password" />
                        <button class="pw-toggle" type="button" :aria-label="showPw ? '隐藏密码' : '显示密码'" @click="showPw = !showPw">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
                                <path d="M2.06 12.35a1 1 0 0 1 0-.7C3.4 7.3 7.45 4.5 12 4.5s8.6 2.8 9.94 7.15a1 1 0 0 1 0 .7C20.6 16.7 16.55 19.5 12 19.5s-8.6-2.8-9.94-7.15Z"></path>
                                <circle cx="12" cy="12" r="3"></circle>
                                <line x1="4" y1="20" x2="20" y2="4" v-show="showPw"></line>
                            </svg>
                        </button>
                    </div>
                </div>
                <label class="check-row"><input type="checkbox" v-model="remember" />记住用户名(不保存密码)</label>
                <div class="error-banner" v-if="err">{{ errText(err) }}</div>
                <button class="btn primary login-btn" type="submit" :disabled="busy">{{ busy ? "请稍候…" : (mode === 'register' ? '注册并登录' : '登录') }}</button>
                <p class="hint">注册后自动登录;密码至少 8 位,连续失败 5 次将锁定 15 分钟。</p>
            </form>
        </div>
    </div>
</template>

<style scoped>
.login-wrap {
    max-width: 460px;
    margin: 3vh auto 40px;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.login-brand {
    text-align: center;
}

.login-brand h1 {
    margin: 0;
    font-size: 22px;
    letter-spacing: .04em;
}

.login-btn {
    width: 100%;
    margin-top: 6px;
}

.login-me {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}

.notice {
    background: rgba(34, 211, 238, .08);
    border: 1px solid rgba(34, 211, 238, .35);
    color: var(--accent);
    border-radius: 10px;
    padding: 9px 14px;
    font-size: 13.5px;
}
</style>
