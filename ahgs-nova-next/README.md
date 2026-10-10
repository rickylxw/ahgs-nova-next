# ahgs-nova-next（前端）

NOVA 前端 Next 版：Vue 3 + Vite + vue-router + pinia。本目录是 monorepo 的一部分，
后端在 [`../ahgs-nova-be`](../ahgs-nova-be)，总览见[仓库根 README](../README.md)，
游戏规格见[仓库根 ARENA_GAMES.md](../ARENA_GAMES.md)。

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

配套后端：[`../ahgs-nova-be`](../ahgs-nova-be)（`python serve.py --port 8000`）。开发模式经 vite
代理同源免 CORS；生产部署在页面 ⚙ 设置里填 API base（localStorage `next_api_base`）。

架构、约定与已知坑见 [AGENTS.md](AGENTS.md)。
