import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from typing import Any, Dict, List, Optional, Tuple


class ReviewConsole:
    """
    Terminal-based review loop for human-in-the-loop confirmation.

    Supports commands (minimal POC set):
      - show
      - confirm
      - redo
      - back
      - keep 1,3,4
      - drop 2
      - rename 1 "New Name"
      - add "New Item Name"
      - help
      - quit
    """

    def __init__(self, max_redo: int = 2) -> None:
        self.max_redo = int(max_redo)

    # ---------------- Public API ----------------

    def review_loop(
        self,
        step: str,
        draft: Any,
        item_key: Optional[str] = None,
        title_key: str = "name",
    ) -> Dict[str, Any]:
        """
        Run an interactive review loop.

        Args:
            step: Step name (FEATURES, STORIES, etc.)
            draft: Draft artifact (usually list[dict] or dict).
            item_key: If draft is dict and items are in draft[item_key], provide that key.
                      If draft is list, keep None.
            title_key: For list items, display this field as the title if present.

        Returns:
            {
              "action": "confirm" | "redo" | "back" | "quit",
              "artifact": <edited_artifact>,
              "redo_count": int
            }
        """
        redo_count = 0
        artifact = self._normalize_artifact(draft, item_key=item_key)

        print(f"\n=== Review: {step} ===")
        self._print_help_brief()
        self._print_artifact(artifact, title_key=title_key)

        while True:
            cmd = input("\nreview> ").strip()

            if not cmd:
                continue

            action = self._parse_action(cmd)

            # --- global actions ---
            if action == "help":
                self._print_help_full()
                continue

            if action == "show":
                self._print_artifact(artifact, title_key=title_key)
                continue

            if action == "confirm":
                return {"action": "confirm", "artifact": artifact, "redo_count": redo_count}

            if action == "back":
                return {"action": "back", "artifact": artifact, "redo_count": redo_count}

            if action == "quit":
                return {"action": "quit", "artifact": artifact, "redo_count": redo_count}

            if action == "redo":
                redo_count += 1
                if redo_count > self.max_redo:
                    print(f"[warn] redo exceeded max_redo={self.max_redo}. Please edit or confirm.")
                    redo_count = self.max_redo
                    continue
                return {"action": "redo", "artifact": artifact, "redo_count": redo_count}

            # --- edit actions (list editing) ---
            if self._is_list_artifact(artifact):
                edited, msg = self._apply_edit_command(artifact, cmd, title_key=title_key)
                if msg:
                    print(msg)
                if edited is not None:
                    artifact = edited
                continue

            # --- dict artifact fallback ---
            print("[warn] This step artifact is not a list. Use 'show' / 'confirm' / 'redo' / 'back'.")

    # ---------------- Normalization & Printing ----------------

    @staticmethod
    def _normalize_artifact(draft: Any, item_key: Optional[str]) -> Any:
        """
        Normalize artifact so edits can be applied.
        - If draft is dict and item_key exists and is a list -> use that list
        - Else keep as-is
        """
        if isinstance(draft, dict) and item_key:
            v = draft.get(item_key)
            if isinstance(v, list):
                return v
        return draft

    @staticmethod
    def _is_list_artifact(artifact: Any) -> bool:
        return isinstance(artifact, list)

    @staticmethod
    def _print_help_brief() -> None:
        print("Commands: show | confirm | redo | back | keep | drop | rename | add | help | quit")

    @staticmethod
    def _print_help_full() -> None:
        print(
            "\nCommands:\n"
            "  show                         - display current draft\n"
            "  confirm                      - accept and freeze this step\n"
            "  redo                         - ask model to regenerate this step (limited)\n"
            "  back                         - rollback to previous step\n"
            "  quit                         - exit the run\n"
            "\nEdits (for list artifacts):\n"
            "  keep 1,3,4                   - keep only these indices (1-based)\n"
            "  drop 2                       - remove an item by index\n"
            "  rename 1 \"New Name\"          - rename an item (uses 'name' or 'title' fields)\n"
            "  add \"New Item\"               - append a new item with name/title\n"
        )

    @staticmethod
    def _print_artifact(artifact: Any, title_key: str = "name") -> None:
        print("\n--- Current Draft ---")
        if isinstance(artifact, list):
            if not artifact:
                print("(empty list)")
                return
            for i, item in enumerate(artifact, start=1):
                if isinstance(item, dict):
                    title = item.get(title_key) or item.get("title") or item.get("id") or f"item-{i}"
                    print(f"{i}. {title}")
                else:
                    print(f"{i}. {str(item)}")
        else:
            # dict or str
            try:
                print(json.dumps(artifact, ensure_ascii=False, indent=2, default=str))
            except Exception:
                print(str(artifact))

    # ---------------- Command Parsing ----------------

    @staticmethod
    def _parse_action(cmd: str) -> str:
        c = cmd.strip().lower()
        if c in ("h", "help", "?"):
            return "help"
        if c in ("s", "show"):
            return "show"
        if c in ("c", "confirm", "ok", "yes"):
            return "confirm"
        if c in ("r", "redo", "regen"):
            return "redo"
        if c in ("b", "back", "rollback"):
            return "back"
        if c in ("q", "quit", "exit"):
            return "quit"
        return "edit"

    # ---------------- Edit Commands ----------------

    def _apply_edit_command(self, items: List[Any], cmd: str, title_key: str) -> Tuple[Optional[List[Any]], str]:
        """
        Apply list-edit commands. Returns (new_items_or_None, message).
        """
        c = cmd.strip()

        # keep 1,2,3
        if c.lower().startswith("keep "):
            idxs = self._parse_indices(c[len("keep "):])
            if not idxs:
                return None, "[warn] keep: invalid indices. Example: keep 1,3,4"
            new_items = []
            for i in idxs:
                if 1 <= i <= len(items):
                    new_items.append(items[i - 1])
            return new_items, f"[ok] kept {len(new_items)} items."

        # drop 2
        if c.lower().startswith("drop "):
            idxs = self._parse_indices(c[len("drop "):])
            if not idxs or len(idxs) != 1:
                return None, "[warn] drop: provide exactly one index. Example: drop 2"
            i = idxs[0]
            if not (1 <= i <= len(items)):
                return None, "[warn] drop: index out of range."
            new_items = items[: i - 1] + items[i:]
            return new_items, "[ok] dropped."

        # rename 1 "New Name"
        if c.lower().startswith("rename "):
            ok, idx, new_name = self._parse_rename(c)
            if not ok:
                return None, "[warn] rename: Example: rename 1 \"New Name\""
            if not (1 <= idx <= len(items)):
                return None, "[warn] rename: index out of range."

            new_items = list(items)
            item = new_items[idx - 1]
            if isinstance(item, dict):
                # prefer title_key; fallback to "title"
                if title_key in item:
                    item[title_key] = new_name
                elif "title" in item:
                    item["title"] = new_name
                else:
                    item["name"] = new_name
                new_items[idx - 1] = item
                return new_items, "[ok] renamed."
            else:
                new_items[idx - 1] = new_name
                return new_items, "[ok] renamed."

        # add "New Item"
        if c.lower().startswith("add "):
            new_name = self._parse_quoted_string(c[len("add "):].strip())
            if not new_name:
                return None, "[warn] add: Example: add \"New Item\""
            new_items = list(items)
            new_items.append({title_key: new_name})
            return new_items, "[ok] added."

        return None, "[warn] unknown edit command. Type 'help'."

    @staticmethod
    def _parse_indices(s: str) -> List[int]:
        """
        Parse '1,3,4' or '2' into [1,3,4].
        """
        out: List[int] = []
        raw = s.replace(" ", "")
        if not raw:
            return out
        parts = raw.split(",")
        for p in parts:
            try:
                out.append(int(p))
            except Exception:
                return []
        return out

    @staticmethod
    def _parse_rename(cmd: str) -> Tuple[bool, int, str]:
        """
        Parse: rename 1 "New Name"
        """
        # split first two tokens then parse quoted
        parts = cmd.split(maxsplit=2)
        if len(parts) < 3:
            return False, 0, ""
        try:
            idx = int(parts[1])
        except Exception:
            return False, 0, ""
        new_name = ReviewConsole._parse_quoted_string(parts[2].strip())
        if not new_name:
            return False, 0, ""
        return True, idx, new_name

    @staticmethod
    def _parse_quoted_string(s: str) -> str:
        """
        Parse a quoted string "xxx" or 'xxx'. Returns "" if invalid.
        """
        s = s.strip()
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        return ""
