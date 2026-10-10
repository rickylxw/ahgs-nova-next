# ahgs-nova-next

AHGS（自动启发式算法生成系统）平台增强版 NOVA：**自建后端 + Next 版前端** 的 monorepo。

| 目录 | 说明 |
| --- | --- |
| [`ahgs-nova-be/`](ahgs-nova-be/) | **自建后端**（FastAPI，standalone 模式）：本地进化引擎（LLM 变异→预筛→评测→选择）、官方接口兼容层、榜单、种子库、对战 Arena，不依赖官方平台 |
| [`ahgs-nova-next/`](ahgs-nova-next/) | **Next 版前端**（Vue 3 + Vite + vue-router + pinia）：兼容层 8 视图全量移植 + Nova v2 原生视图（登录/种子库/数据集/预筛/对战竞技/管理端） |

共享文档：[ARENA_GAMES.md](ARENA_GAMES.md)（对战游戏规格，前后端共同契约）·
[BACKEND_PLAN.md](BACKEND_PLAN.md)（后端设计与里程碑）。旧版前端（原生 JS / Vue 运行时 / SFC）
仍在 [AHGS_NOVA](https://github.com/rickylxw/AHGS_NOVA) 仓库。

## 快速开始

```bash
# 后端（:8000）
cd ahgs-nova-be
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
cp .env.example .env                       # 至少改 NOVA_JWT_SECRET
python scripts/seed_demo.py                # 管理员 + 21 题 + 示例 bot
python serve.py --port 8000

# 前端（:8926，/api 代理到 :8000）
cd ahgs-nova-next
npm install
npm run dev
```

各目录的架构、约定与已知坑分别见 `ahgs-nova-be/README.md` 与 `ahgs-nova-next/AGENTS.md`。

## License

GPL-3.0（见 [LICENSE](LICENSE)）
