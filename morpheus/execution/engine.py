import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit.logger import AuditLogger
from execution.plan import build_plan


def run_step(step: dict) -> dict:
    time.sleep(0.1)
    if random.random() < 0.1:
        raise RuntimeError(f"Simulated failure in step '{step['step']}'")
    return {"status": "ok"}


def execute_plan(plan: list[dict], logger: AuditLogger) -> bool:
    for step in plan:
        step_name = step["step"]
        max_retries = step.get("retry", 0)

        logger.log("step_started", {"step": step_name, "type": step["type"]})

        succeeded = False
        for attempt in range(max_retries + 1):
            try:
                result = run_step(step)
                logger.log("step_completed", {"step": step_name, "result": result})
                succeeded = True
                break
            except RuntimeError as e:
                if attempt < max_retries:
                    logger.log("step_retrying", {"step": step_name, "attempt": attempt + 1, "error": str(e)})
                else:
                    logger.log("step_failed", {"step": step_name, "error": str(e)})

        if not succeeded:
            return False

    return True


if __name__ == "__main__":
    logger = AuditLogger()
    plan = build_plan("query_chart")
    logger.log("execution_started", {"action": "query_chart"})
    success = execute_plan(plan, logger)
    logger.log("execution_finished", {"success": success})
    print(logger.to_json())
