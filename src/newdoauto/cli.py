"""
CLI entry point for NewDoAuto automation runner.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from newdoauto import __version__
from newdoauto.core.engine import AutomationEngine
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext, ExecutionStatus
from newdoauto.models.workflow import Workflow
from newdoauto.models.validation import validate_workflow, ValidationError
from newdoauto.safety.emergency_stop import EmergencyStopListener


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="newdoauto",
        description="NewDoAuto - Personal Desktop Automation Tool for Windows",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a workflow JSON file")
    run_parser.add_argument("workflow_file", help="Path to workflow JSON file")
    run_parser.add_argument("--quiet", action="store_true", help="Suppress non-essential console logs")
    run_parser.add_argument("--no-cleanup", action="store_true", help="Do not terminate spawned child processes on exit")
    run_parser.add_argument("--no-hotkey", action="store_true", help="Disable global emergency stop hotkey")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a workflow JSON file without executing")
    validate_parser.add_argument("workflow_file", help="Path to workflow JSON file")

    # UI command
    subparsers.add_parser("ui", help="Launch the NewDoAuto Windows Desktop GUI")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "validate":
        return _handle_validate(args.workflow_file)

    if args.command == "run":
        return _handle_run(args)

    if args.command == "ui":
        from newdoauto.ui.app import launch_desktop_app
        return launch_desktop_app()

    return 0


def _handle_validate(filepath: str) -> int:
    if not os.path.exists(filepath):
        sys.stderr.write(f"Error: File not found: '{filepath}'\n")
        return 1

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        wf = Workflow.from_dict(data)
        validate_workflow(wf)
        print(f"Workflow '{wf.name}' (version {wf.schema_version}) is VALID ({len(wf.actions)} actions).")
        return 0
    except ValidationError as ve:
        sys.stderr.write(f"Validation failed:\n{ve}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Failed to read or parse workflow: {e}\n")
        return 1


def _handle_run(args) -> int:
    filepath = args.workflow_file
    if not os.path.exists(filepath):
        sys.stderr.write(f"Error: File not found: '{filepath}'\n")
        return 1

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        wf = Workflow.from_dict(data)
    except Exception as e:
        sys.stderr.write(f"Failed to read or parse workflow '{filepath}': {e}\n")
        return 1

    logger = StructuredLogger(quiet=args.quiet)
    context = ExecutionContext()
    engine = AutomationEngine(
        logger=logger,
        cleanup_processes_on_finish=not args.no_cleanup,
    )

    hotkey_listener = None
    if not args.no_hotkey and os.name == "nt":
        hotkey_listener = EmergencyStopListener(context.cancellation_token)
        hotkey_listener.start(logger=logger)

    try:
        engine.execute_workflow(wf, context=context)
    finally:
        if hotkey_listener:
            hotkey_listener.stop()

    if context.status == ExecutionStatus.COMPLETED:
        return 0
    elif context.status == ExecutionStatus.CANCELLED:
        return 130
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
