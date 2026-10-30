"""
Structured logging module for NewDoAuto execution engine.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
import sys
from typing import Any, Callable, Dict, Optional
from newdoauto.core.state import ExecutionContext


class StructuredLogger:
    """Provides structured JSON & human-readable console logging with execution context tracking."""
    def __init__(
        self,
        context: Optional[ExecutionContext] = None,
        quiet: bool = False,
        on_log: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.context = context
        self.quiet = quiet
        self.on_log = on_log

    def log(
        self,
        level: str,
        message: str,
        action_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        current_action = action_id or (self.context.current_action_id if self.context else None)
        entry: Dict[str, Any] = {
            "timestamp": now_iso,
            "level": level.upper(),
            "message": message,
            "action_id": current_action,
        }
        if data:
            entry["data"] = data

        if self.context:
            self.context.logs.append(entry)

        if self.on_log is not None:
            try:
                self.on_log(entry)
            except Exception:
                pass

        if not self.quiet:
            prefix = f"[{level.upper():5s}]"
            act_str = f" [{current_action}]" if current_action else ""
            data_str = f" | {json.dumps(data)}" if data else ""
            out = f"{now_iso[:19]} {prefix}{act_str} {message}{data_str}\n"
            if level.upper() in ("ERROR", "CRITICAL"):
                sys.stderr.write(out)
                sys.stderr.flush()
            else:
                sys.stdout.write(out)
                sys.stdout.flush()

        return entry

    def info(self, message: str, action_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        return self.log("INFO", message, action_id=action_id, data=data)

    def warn(self, message: str, action_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        return self.log("WARN", message, action_id=action_id, data=data)

    def error(self, message: str, action_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        return self.log("ERROR", message, action_id=action_id, data=data)

    def debug(self, message: str, action_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        return self.log("DEBUG", message, action_id=action_id, data=data)
