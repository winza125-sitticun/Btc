# Market worker entrypoint regression

Production rollout verification on 2026-09-13 found that `python -m services.market_worker.app.main` exited successfully without starting the realtime worker because the module-level `__main__` guard had been removed.

The hotfix restores the module entrypoint and adds a regression test that executes the worker file as `__main__` while replacing only `asyncio.run`, proving that realtime mode dispatches to `run_forever()` without making network calls.

Rollout remains `SHADOW`. Do not promote to `PRIMARY` until production scanner persistence, multi-agent evidence, and the absence of multi-agent order intents in SHADOW are verified after deployment.
