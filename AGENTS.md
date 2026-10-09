# AGENTS.md — ahgs-nova-next

Next edition of the AHGS NOVA frontend (Vue 3 + Vite + **vue-router** + **pinia**). Split out of the
[AHGS_NOVA](https://github.com/rickylxw/AHGS_NOVA) monorepo on 2026-10-09 (that repo still hosts the
older editions and the backend). It is a full
replacement of the SFC edition (`../AHGS_NOVA/ahgs-nova-sfc`, all 8 compat views ported) and the frontend
for the **standalone** backend (`../AHGS_NOVA/ahgs-nova-be` running `NOVA_MODE=standalone`): a single Nova session
(`/api/v2/auth/*` JWT + refresh rotation) authorizes both the v2 endpoints and the compat layer
(same signing secret, same users table). There is no official-platform session anymore — login,
register, profile and password change all talk to the one backend.

## Commands

```bash
npm install
npm run dev        # dev server on :8926, /api proxied to NOVA_DEV_API (default http://127.0.0.1:8000)
npm run build      # outputs to dist/ — the minimum verification bar
npm run preview    # preview the production build
```

Backend: start `../AHGS_NOVA/ahgs-nova-be` (`python serve.py --port 8000`). In dev the vite proxy makes all
requests same-origin, so no CORS setup is needed. In production set the API base in the ⚙ settings
popover (localStorage `next_api_base`).

## Layout

```
src/
├── main.js               # createApp + pinia + router
├── App.vue               # topbar (dual-session chip, grouped nav) / settings / DrawerHost / toasts
├── router/index.js       # vue-router hash mode; meta.requires ("official"|"nova") + meta.admin guards
├── api/
│   ├── client.js         # api(), ApiError{status,code,retryable,detail}, apiBase/wsBase, token slot
│   ├── compat.js         # compat-layer profile endpoints (PATCH me, password change)
│   └── nova.js           # every /api/v2 endpoint (401 refresh handled centrally in client.js)
├── stores/               # pinia: session.js (single slot), problems.js, ui.js (theme/toasts/drawers)
├── lib/                  # constants.js (LS keys, labels), format.js (parseServerTime, isAscend, …)
├── charts/               # hand-rolled SVG charts ported verbatim from ahgs-nova-sfc
├── components/           # shared UI + drawers/ (DrawerHost, Sub/UserProfile/HeurDetail)
└── views/                # 14 route views (see below)
```

Views: compat ports `DashboardView / LeaderboardView / LiveView / EvolveView / CprobView / CurveView /
CompareView / MineView` + v2 natives `LoginView / SeedsView / DatasetsView / PrescreenView / ArenaView /
AdminView`. The runs console (RunsView / RunDetailView / ws/runChannel.js) was **removed on purpose** —
the local evolution engine workflow is not part of this product's UI; `api/nova.js` no longer carries the
run/harvest/grind/abtest wrappers either (removed as dead code). Arena match progress is followed from the
「对局记录」tab (15s auto-refresh), not from a run-detail page. ArenaView 回放渲染按游戏目录协商
(`board_shape` 定网格尺寸 / `pieces` 定棋子字符 / `cell_classes` 定格子配色 / `labels` 定
reason/outcome 文案 / `starter_code` 一键填入上传框),数组棋盘与 dict 的 `cells` 视图均走网格,
其余 dict 回退 JSON;规格见仓库根 `ARENA_GAMES.md` §8。

Top-level sections (`meta.section` in the router, rendered as a switcher in the topbar):
`evolution`「AI 进化」, `arena`「对战竞技」, `admin`「管理端」(admin-only chip). The evolution section
renders a **left grouped sidebar** (App.vue `SECTIONS[0].sidebar`: 总览 / 榜单 / 进化工作台 / 题目与数据 /
个人) next to the content (`#shell` flex layout); arena and admin are single pages without a sidebar.
On ≤980px the sidebar becomes a hamburger-toggled left drawer. Switching sections navigates to the
section's default route.

## Session model (single Nova session)

- One slot only: `next_nova_access` / `next_nova_refresh` / `next_nova_user` (see `lib/constants.js`).
  Login/register go to `/api/v2/auth/*`; the compat endpoints (`/api/auth/me` PATCH, `/api/auth/me/password`,
  `/api/problems`, `/api/ranking/*`, …) accept the same JWT in standalone mode.
- `api/client.js` owns token refresh centrally: on `401 AUTH_REQUIRED` it calls the handler registered by
  `App.vue` (`setTokenRefreshHandler` → `session.refresh()`), replays the request once, and broadcasts
  `next:session-expired` if the refresh fails (App then clears the session and redirects to `/login`).
  `api/nova.js` is therefore a plain endpoint list with no wrapper.
- Route guards: `meta.requires: "nova"` (all gated views), `meta.admin` (checks `user.role`).
- Passwords are never persisted (only the remembered username, `next_remember`).

## Conventions

- `<script setup>` SFCs, plain JS, no v-html. Template expressions must not use non-whitelisted globals
  (`URLSearchParams`, `Date`, `JSON`, …) — build values in script (the SFC edition's `_ctx.` pitfall applies
  to the Vue compiler regardless of router choice).
- Server time is naive UTC: always `parseServerTime()`, never `new Date(iso)`.
- Optimization direction: `ascend !== false` means lower is better; always via `isAscend(problemKey)`.
- All HTTP through `api()` / the `nova.js` wrappers — never raw `fetch`. v2 errors dispatch on `e.code`
  (`QUEUE_PAUSED`, `AUTH_LOCKED` + `detail.unlock_at`, `QUOTA_EXCEEDED`, `RATE_LIMITED`); messages are
  pre-localized, just display `e.message`.
- UI copy is Simplified Chinese; keep SFC class names for visual continuity (style.css was ported verbatim;
  this file is standalone — do NOT sync changes back to the older editions).
- Passwords are never persisted (the SFC edition's plaintext `ahgs_remember` password storage was
  deliberately dropped; only the username is remembered).

## Verification status (2026-09-30, runs console removed; arena P0+P1 landed)

- `npm run build` passes (14 views).
- Verified against the standalone backend (port 8000, `NOVA_MODE=standalone` in `.env`): v2 login,
  session-gated views, Chinese problem names from `scripts/seed_demo.py`, nav without the runs console.
- Arena: catalog-driven replay rendering (board_shape/pieces/cell_classes/player_marks/labels/
  starter_code) shipped with six backend games (tictactoe / connect4 / gomoku / reversi / tron /
  bomberman, registered in `ahgs-nova-be/app/arenas/`); dict-with-`cells` boards (bomberman) render
  through the same grid, other dicts fall back to JSON. Bomberman supports 2-4-player matches
  (placement-group ELO via `GameRecord.ranking`; 3rd/4th player colors mk-p3/mk-p4). Backend suite
  `pytest` 111 passed incl. per-game referee units + real-subprocess deterministic match flows.
- Engine alignment history: the `evolve_llm` engine parameter panel was removed together with RunsView;
  `gen_stats` / `result.stats` / snapshot normalization knowledge moved to the AGENTS notes below.

## Known backend gaps surfaced while building (not frontend bugs)

- Compat layer lacks the custom-problems long tail (`upload`, `agent/execute|runs|approve`, DELETE) and the
  `developer/*` endpoints — in standalone those views surface the backend's error messages. Matches the
  backend README ("P4 长尾端点待补").
- `runGeneration` 快照与 `best_heuristic` 的字段名在不同执行器间有差异(`feature` vs `features`,
  `code` vs `algorithm`)—— RunDetailView 已做归一化,新增执行器时注意对齐。
