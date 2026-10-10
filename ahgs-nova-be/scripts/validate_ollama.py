# -*- coding: utf-8 -*-
"""真实 Ollama qwen3:4b × knapsack 契约 × 进化引擎 端到端验证(独立临时库)。"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

TMP = tempfile.mkdtemp(prefix="nova-ollama-val-")
os.environ["NOVA_DATABASE_URL"] = f"sqlite+aiosqlite:///{TMP}/t.db"
os.environ["NOVA_STORAGE_DIR"] = f"{TMP}/storage"
os.environ["NOVA_CORS_ORIGINS"] = ""
os.environ["NOVA_ADMIN_USERNAME"] = "admin"
os.environ["NOVA_ADMIN_PASSWORD"] = "admin-password-1"
# .env 里的 NOVA_LLM_* 保持生效(ollama:qwen3:4b)

import httpx
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

SEED = "def select_item(i, rem, w, v, n):\n    return 1 if w[i] <= rem else 0\n"


def main():
    s = Settings()
    print("fallback chain:", s.llm_fallback_chain)
    app = create_app(s)
    with TestClient(app) as c:
        tok = c.post("/api/auth/login", json={
            "username": "admin", "password": "admin-password-1"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {tok}"}
        from app.contracts.builtin import CONTRACTS
        spec = CONTRACTS["knapsack"]
        r = c.put("/api/v2/admin/problems/knapsack", headers=auth, json={
            "name": spec["name"], "kind": "optimization", "ascend": spec["ascend"],
            "contract": {"description": spec["description"],
                         "evaluate": spec["evaluate"]}})
        assert r.status_code == 200, r.text

        r = c.post("/api/v2/run", headers=auth, json={
            "problem_key": "knapsack",
            "config": {
                "num_generations": 2, "candidates_per_gen": 1,
                "population_size": 4,
                "seed_code": SEED, "seed_concept": "greedy take",
                "llm_model": "gemma3:1b", "llm_provider": "ollama",
                "llm_timeout": 300, "llm_max_tokens": 1024,
                
            }})
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        print(f"run {rid} launched, waiting (CPU, 每次 LLM 调用 2-4 分钟)...", flush=True)

        t0 = time.monotonic()
        status = None
        while time.monotonic() - t0 < 1500:
            d = c.get(f"/api/v2/runs/{rid}", headers=auth).json()
            status = d["status"]
            if status in ("completed", "failed", "canceled"):
                break
            time.sleep(10)
        print(f"final status: {status} ({time.monotonic()-t0:.0f}s)")
        d = c.get(f"/api/v2/runs/{rid}", headers=auth).json()
        if d.get("error_message"):
            print("error:", d["error_code"], d["error_message"][:300])
        result = d.get("result") or {}
        print("best_objective:", result.get("best_objective"))
        stats = result.get("stats") or {}
        print("stats:", {k: stats.get(k) for k in
                         ("llm_calls", "eval_ok", "eval_fail", "population")})
        for f in (stats.get("feedback") or [])[:5]:
            print("feedback:", f[:180])
        gens = c.get(f"/api/v2/runs/{rid}/generations", headers=auth).json()["generations"]
        print("generations:", [(g["generation"], g["best_objective"]) for g in gens])
        hv = c.post(f"/api/v2/harvest/{rid}", headers=auth, json={})
        print("harvest:", hv.json())


if __name__ == "__main__":
    main()
