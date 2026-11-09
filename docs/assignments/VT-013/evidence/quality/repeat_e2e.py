"""Ten fresh disposable runs after Docker readiness is established."""
import json
import os
from pathlib import Path
from run_quality import HERE, module

outcomes = []
first = int(os.environ.get("QUALITY_E2E_FIRST", "1"))
last = int(os.environ.get("QUALITY_E2E_LAST", "10"))
for iteration in range(first, last + 1):
    folder = HERE / f"real-e2e-{iteration:02}"
    folder.mkdir(exist_ok=False)
    m = module(f"vt013_quality_real_{iteration}", HERE.parent / "frontend/run_e2e.py")
    m.HERE = folder
    original = m.command

    def redirected(name, argv, timeout=60, env=None):
        if "--config=playwright.vt013.config.ts" in argv:
            argv = [str(x).replace("--config=playwright.vt013.config.ts", "--config=" + str(HERE / "playwright.quality.config.ts")) for x in argv]
            env = dict(env, QUALITY_E2E_ARTIFACTS=str(folder))
        return original(name, argv, timeout=timeout, env=env)

    m.command = redirected
    code = m.main()
    outcomes.append({"iteration": iteration, "exit_code": code, "result": m.report["result"],
                     "owned_container_removed": m.report.get("owned_container_removed", False)})
    name = "real-e2e-repetitions.json" if first == 1 else f"real-e2e-repetitions-{first}-{last}.json"
    (HERE / name).write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(outcomes[-1]), flush=True)
raise SystemExit(0 if all(x["exit_code"] == 0 for x in outcomes) else 1)
