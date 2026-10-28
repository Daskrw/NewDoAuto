"""
Application lifecycle actions (launch, close) for NewDoAuto.
"""

from typing import Any
import subprocess
import time
from newdoauto.actions.base import ActionHandler
from newdoauto.core.evaluator import interpolate_variables
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext
from newdoauto.models.workflow import Action


class AppLaunchHandler(ActionHandler):
    """Launches an external application executable."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        command = interpolate_variables(action.params["command"], context)
        args = interpolate_variables(action.params.get("args", []), context)
        track = action.params.get("track_process", True)
        wait_seconds = float(action.params.get("wait_after_launch_seconds", 1.0))

        cmd_list = [command] + (args if isinstance(args, list) else [args])
        logger.info(f"Launching application: {' '.join(cmd_list)}")

        try:
            proc = subprocess.Popen(cmd_list)
        except Exception as e:
            raise RuntimeError(f"Failed to launch application '{command}': {e}") from e

        if track:
            context.track_process(proc)

        # Wait for application initialization while respecting cancellation
        start_wait = time.time()
        while time.time() - start_wait < wait_seconds:
            context.cancellation_token.throw_if_cancelled()
            time.sleep(0.1)

        result = {
            "pid": proc.pid,
            "command": command,
            "is_running": proc.poll() is None,
        }
        logger.info(f"Application launched successfully (PID: {proc.pid})")
        return result


class AppCloseHandler(ActionHandler):
    """Closes an application by process PID or process name."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        pid = action.params.get("pid")
        process_name = action.params.get("process_name")

        if pid:
            pid = int(interpolate_variables(pid, context))
            logger.info(f"Terminating process by PID: {pid}")
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=True)
                return {"closed_pid": pid}
            except Exception as e:
                logger.warn(f"Failed to terminate PID {pid}: {e}")
                return {"error": str(e)}

        if process_name:
            proc_name = str(interpolate_variables(process_name, context))
            logger.info(f"Terminating process by name: {proc_name}")
            try:
                subprocess.run(["taskkill", "/F", "/IM", proc_name], capture_output=True)
                return {"closed_process_name": proc_name}
            except Exception as e:
                logger.warn(f"Failed to terminate process {proc_name}: {e}")
                return {"error": str(e)}

        raise ValueError("AppCloseHandler requires either 'pid' or 'process_name'")
