import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
from backend.src.agent.orchestrator import AgentOrchestrator


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="AI-Driven Test Process Automation (Terminal POC)"
    )
    p.add_argument(
        "--trace_id",
        type=str,
        required=True,
        help="Trace id (folder name under output root). Example: demo-login",
    )
    p.add_argument(
        "--epic_title",
        type=str,
        default=None,
        help="Optional Epic title (if creating a new trace).",
    )
    p.add_argument(
        "--start_step",
        type=str,
        default=None,
        help="Optional start step (e.g., FEATURES/STORIES/TEST_PLAN/TEST_CASES/AUTOMATED_TESTS). "
             "Prerequisites must be confirmed.",
    )
    p.add_argument(
        "--out_dir",
        type=str,
        default=None,
        help="Optional output root directory. "
             "Default: <repo>/backend/src/output. "
             "If a relative path is provided, it will be resolved under <repo>/backend/src.",
    )
    return p


def main():
    args = build_parser().parse_args()

    orch = AgentOrchestrator(out_dir=args.out_dir)
    final_state = orch.run(
        trace_id=args.trace_id,
        epic_title=args.epic_title,
        start_step=args.start_step,
    )

    print("\n=== Final State Saved ===")
    print(f"trace_id: {final_state.get('trace_id')}")
    print(f"current_step: {final_state.get('current_step')}")
    print("confirmed steps:", list((final_state.get("confirmed") or {}).keys()))


if __name__ == "__main__":
    main()
