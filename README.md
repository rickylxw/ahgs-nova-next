# ahgs-nova-next

AHGS（自动启发式算法生成系统）平台增强前端 **NOVA · Next 版**：Vue 3 + Vite + vue-router + pinia。

2026-10-09 从 [AHGS_NOVA](https://github.com/rickylxw/AHGS_NOVA) 单仓库拆出为独立仓库；
旧版（原生 JS 版 / Vue 运行时版 / SFC 版）与自建后端 `ahgs-nova-be` 仍在 AHGS_NOVA 仓库维护。

## 功能

- 兼容层 8 视图全量移植：总览 / 榜单 / 实时提交流 / 进化工作台 / 自定义问题 / 进化曲线分析 / 双提交对比 / 个人中心
- Nova v2 原生视图：登录 / 种子库 / 数据集 / 预筛 / **对战竞技（Arena 回放）** / 管理端
- 单一会话模型：`/api/v2/auth/*` JWT + 401 集中刷新，兼容层与 v2 端点同令牌通吃
- 14 个路由视图，UI 文案简体中文，深色主题与 SFC 版视觉连续

## 启动

```bash
npm install
npm run dev        # 开发服务器 :8926，/api 代理到 NOVA_DEV_API（默认 http://127.0.0.1:8000）
npm run build      # 产物输出 dist/ —— 最低验证标准
npm run preview    # 预览生产构建
```

配套后端：`AHGS_NOVA/ahgs-nova-be`（`python serve.py --port 8000`）。开发模式经 vite 代理同源免 CORS；
生产部署在页面 ⚙ 设置里填 API base（localStorage `next_api_base`）。

架构、约定与已知坑见 [AGENTS.md](AGENTS.md)；Arena 游戏规格见 [ARENA_GAMES.md](ARENA_GAMES.md)。

## License

GPL-3.0（见 [LICENSE](LICENSE)）
