import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from typing import Any, Dict, Optional

from backend.src.agent.state_store import StateStore, STEP_ORDER
from backend.src.agent.step_router import StepRouter
from backend.src.agent.step_generator import StepGenerator
from backend.src.agent.review_console import ReviewConsole


class AgentOrchestrator:
    """
    End-to-end flow runner (terminal POC):
      - create/load trace
      - resume from state.current_step
      - generate draft per step
      - interactive review loop
      - freeze confirmed artifact
      - support redo/back/quit
    """

    def __init__(
        self,
        store: Optional[StateStore] = None,
        router: Optional[StepRouter] = None,
        generator: Optional[StepGenerator] = None,
        reviewer: Optional[ReviewConsole] = None,
        out_dir: Optional[str] = None,   # ✅ NEW: allow passing output root
    ) -> None:
        # ✅ Priority:
        # 1) if store is provided, use it
        # 2) else construct a default store using out_dir (or default backend/src/output)
        self.store = store or StateStore(out_dir=out_dir)

        self.router = router or StepRouter()
        self.gen = generator or StepGenerator()
        self.review = reviewer or ReviewConsole(max_redo=2)

    # ---------------- Public API ----------------

    def run(
        self,
        trace_id: str,
        epic_title: Optional[str] = None,
        start_step: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the workflow.

        Args:
            trace_id: folder name under output root
            epic_title: only used when creating a new trace
            start_step: optional step to start from (requires prerequisites confirmed)

        Returns:
            Final state dict.
        """
        # 1) load or create
        if self.store.trace_exists(trace_id):
            state = self.store.load_state(trace_id)
            print(f"[ok] loaded trace: {trace_id}")
        else:
            state = self.store.create_trace(trace_id=trace_id, epic_title=epic_title)
            print(f"[ok] created trace: {trace_id}")

        # 2) optional start-from-middle
        if start_step:
            check = self.router.set_start_step(state, start_step)
            if not check.get("ok"):
                print("[warn] cannot start from step:", start_step)
                print("       missing prerequisites:", check.get("missing"))
                # keep resume behavior
            else:
                self.store.save_state(state)
                print(f"[ok] start from step: {start_step}")

        # 3) main loop
        while True:
            step = self.router.decide_current_step(state)

            # stop if everything confirmed
            if self._all_confirmed(state):
                print("\n[done] all steps confirmed.")
                break

            print(f"\n=== Current Step: {step} ===")

            # 3.1 build confirmed context dict for generator (load only what exists)
            confirmed_ctx = self._load_confirmed_context(state)

            # 3.2 special: EPIC can be user-input (optional)
            if step == "EPIC" and "EPIC" not in state.get("confirmed", {}):
                epic = self._input_epic(epic_title)
                out_path = self.store.freeze_confirmed(
                    state, "EPIC", epic, version=self._next_version(state, "EPIC")
                )
                print("[ok] EPIC confirmed ->", out_path)
                continue

            # 3.3 generate draft
            draft = self.gen.generate_step(step, state, confirmed_ctx)

            # 3.4 review loop
            review_out = self.review.review_loop(step=step, draft=draft)

            action = review_out["action"]
            artifact = review_out["artifact"]

            if action == "quit":
                print("[exit] user quit.")
                break

            if action == "back":
                prev_step = self.router.on_back(state)
                if not prev_step:
                    print("[warn] already at first step, cannot back.")
                    continue
                # rollback to prev_step
                self.store.rollback_to(state, prev_step, delete_files=False)
                print(f"[ok] rolled back to {prev_step}")
                continue

            if action == "redo":
                hint = self._input_redo_hint()
                draft = self.gen.generate_step(step, state, confirmed_ctx, redo_hint=hint)
                review_out = self.review.review_loop(step=step, draft=draft)
                action = review_out["action"]
                artifact = review_out["artifact"]
                if action != "confirm":
                    continue

            if action == "confirm":
                out_path = self.store.freeze_confirmed(
                    state,
                    step,
                    artifact,
                    version=self._next_version(state, step),
                )
                print("[ok] confirmed ->", out_path)
                continue

            print("[warn] unknown action:", action)

        return state

    # ---------------- Helpers ----------------

    @staticmethod
    def _all_confirmed(state: Dict[str, Any]) -> bool:
        confirmed = state.get("confirmed", {}) or {}
        return all(s in confirmed for s in STEP_ORDER)

    def _load_confirmed_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        for step in STEP_ORDER:
            v = self.store.get_confirmed(state, step)
            if v is not None:
                ctx[step] = v
        return ctx

    @staticmethod
    def _next_version(state: Dict[str, Any], step: str) -> int:
        confirmed = state.get("confirmed", {}) or {}
        if step not in confirmed:
            return 1
        return 2

    @staticmethod
    def _input_epic(epic_title: Optional[str]) -> Dict[str, Any]:
        print("\nPlease input EPIC / Initiative info.")
        title = epic_title or input("Epic title: ").strip()
        goal = input("Epic goal (one sentence): ").strip()
        scope = input("Scope / notes (optional): ").strip()

        epic = {
            "title": title,
            "goal": goal,
            "scope": scope,
        }
        print("\n[epic] preview:")
        print(json.dumps(epic, ensure_ascii=False, indent=2))
        ok = input("Confirm EPIC? (y/n): ").strip().lower()
        if ok not in ("y", "yes"):
            print("[info] EPIC not confirmed. You can re-enter.")
            return AgentOrchestrator._input_epic(title)
        return epic

    @staticmethod
    def _input_redo_hint() -> str:
        return input("redo hint (optional, e.g., 'more negative cases'): ").strip()
