/* ============ AHGS NOVA Next · 常量 ============ */
import pkg from "../../package.json";

export const APP_VERSION = pkg.version;

/** 留空 = 同源(dev 下经 vite 代理到本地后端);生产可在设置面板填完整地址 */
export const DEFAULT_API = "";

export const LS = {
    api: "next_api_base",
    theme: "next_theme",
    /** 单一 Nova 会话(v2 JWT;refresh 单次轮换) */
    novaAccess: "next_nova_access",
    novaRefresh: "next_nova_refresh",
    novaUser: "next_nova_user",
    remember: "next_remember",
    evoCfg: "next_evo_cfg",
};

/* ---------- 兼容层(官方契约) ---------- */

export const FW_LABEL = {
    eoh_nseh: "EoH(NSEH)",
    calm: "CALM",
    custom: "自定义框架",
};

export const STATUS_LABEL = {
    pending: "排队中",
    running: "运行中",
    paused: "已暂停",
    completed: "已完成",
    stopped: "已停止",
    failed: "失败",
};

export const STATUS_ACTIVE = new Set(["pending", "running", "paused"]);
export const STATUS_DONE = new Set(["completed", "failed", "stopped"]);

/* ---------- Nova v2 ---------- */

export const V2_STATUS_LABEL = {
    queued: "排队中",
    provisioning: "准备中",
    running: "运行中",
    finalizing: "收尾中",
    completed: "已完成",
    failed: "失败",
    canceled: "已取消",
};

export const V2_ROLE_LABEL = { user: "用户", admin: "管理员" };

export const CP_TASK_LABEL = {
    dataset_builder: "数据集构建脚本",
    evaluator: "评估器",
    example_heuristic: "示例启发式",
};

export const EVO_DEFAULTS = {
    population_size: 8,
    num_generations: 10,
    num_mutation: 3,
    num_hybridization: 3,
    num_reflection: 3,
    num_policy_updates: 1,
};

/** 服务器本地模型(OLLAMA 兼容端点;provider 名与后端 NOVA_LLM_PLATFORM_KEYS 注册名一致) */
export const LOCAL_LLM = {
    provider: "ollama",
    model: "gemma3:1b",
    baseUrl: "http://127.0.0.1:11434/v1",
    toggleLabel: "使用服务器本地模型(gemma3:1b · Ollama)",
    hint: "已连接服务器本地 Ollama(gemma3:1b),无需配置 API Key / Base URL / 模型。",
};

/** 内置 LLM 预设(后端 /api/llm-presets 为空时兜底)。
 *  id 即模型名;provider 为空串 = 走后端默认降级链(云 API 需后端 NOVA_LLM_PLATFORM_KEYS 注册后才能用)。 */
export const LLM_PRESETS = [
    { id: "gemma3:1b", name: "gemma3:1b · Ollama 本地(快,首选联调)", provider: "ollama", base_url: "http://127.0.0.1:11434/v1" },
    { id: "qwen3:4b", name: "qwen3:4b · Ollama 本地(代码更强,较慢)", provider: "ollama", base_url: "http://127.0.0.1:11434/v1" },
    { id: "gpt-oss:120b-cloud", name: "gpt-oss:120b-cloud · Ollama 云端转发", provider: "ollama", base_url: "http://127.0.0.1:11434/v1" },
    { id: "deepseek-chat", name: "DeepSeek API(需在后端注册 key)", provider: "", base_url: "https://api.deepseek.com/v1" },
    { id: "glm-4.5-air", name: "智谱 GLM API(需在后端注册 key)", provider: "", base_url: "https://open.bigmodel.cn/api/paas/v4" },
];

export const PALETTE = ["#22d3ee", "#a78bfa", "#f472b6", "#34d399", "#fbbf24", "#60a5fa", "#fb7185", "#4ade80"];

/** 前端仓库地址(反馈入口 / 页脚链接) */
export const REPO_URL = "https://github.com/rickylxw/AHGS_NOVA";
