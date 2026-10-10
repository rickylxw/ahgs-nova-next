# AGENTS.md — ahgs-nova-next (monorepo)

Self-hosted NOVA stack: **backend** (`ahgs-nova-be/`, FastAPI, standalone) + **frontend**
(`ahgs-nova-next/`, Vue 3 + Vite + vue-router + pinia). The older frontend editions (vanilla /
vue-runtime / SFC) live separately in the [AHGS_NOVA](https://github.com/rickylxw/AHGS_NOVA) repo.

Detailed guidance per component:

- Backend: `ahgs-nova-be/README.md` — modes, API map, contracts, extension points, pytest suite.
- Frontend: `ahgs-nova-next/AGENTS.md` — architecture, conventions, session model, pitfalls.

## Commands

```bash
# backend (FastAPI, :8000) — own venv + pytest suite
cd ahgs-nova-be
.venv/Scripts/pip install -e ".[dev]"
python serve.py --port 8000
.venv/Scripts/python -m pytest tests/ -q

# frontend (Vite dev server :8926, /api proxied to NOVA_DEV_API, default :8000)
cd ahgs-nova-next
npm install
npm run dev        # npm run build outputs dist/ — the minimum verification bar
```

No CI; verification bar = backend `pytest` + frontend `npm run build` + opening affected routes.

## Cross-cutting facts that bite

- **Shared HTTP contract**: the frontend speaks the backend's compat endpoints plus `/api/v2/*` with
  the same semantics (naive-UTC timestamps — always parse as UTC, never `new Date(iso)`;
  `ascend !== false` means *lower fitness is better*). Error envelope `{"code","message","retryable","detail"}`
  on v2 — dispatch on `code`, never on detail strings.
- **Auth is one session**: v2 JWT + refresh rotation authorizes both endpoint families (same signing
  secret, same users table). Frontend localStorage keys are `next_`-prefixed (`next_nova_access`, …).
- **Arena game spec**: games are specified in root [ARENA_GAMES.md](ARENA_GAMES.md) (single copy;
  backend implements them in `ahgs-nova-be/app/arenas/`, frontend renders replays catalog-driven in
  `ahgs-nova-next/src/views/ArenaView.vue` via `board_shape`/`pieces`/`cell_classes`/`player_marks`/
  `labels`/`starter_code`). New-game checklist lives in that doc.
- **Theme CSS**: `ahgs-nova-next/src/styles/style.css` originated as a verbatim port of the SFC
  edition's stylesheet (still in AHGS_NOVA). It is standalone — do not sync changes back.
- **UI copy is Simplified Chinese**; **commit messages are short Chinese imperatives** (see `git log`).
- Git history note: both directories were never committed inside AHGS_NOVA; this repo's history starts
  from the extraction snapshots (frontend 2026-09-28..10-09 work squashed into `24c4aae` and its
  restructure commit).
