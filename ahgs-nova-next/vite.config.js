import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// dev 代理:同源 /api 直达本地 Nova 后端(ws 含 WebSocket),免 CORS 配置。
// 后端不在 127.0.0.1:8000 时,设环境变量 NOVA_DEV_API 覆盖。
const target = process.env.NOVA_DEV_API || "http://127.0.0.1:8000";

export default defineConfig({
    plugins: [vue()],
    base: "./",
    server: {
        port: 8926,
        proxy: {
            "/api": { target, changeOrigin: true, ws: true },
        },
    },
});
