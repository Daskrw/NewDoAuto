"""
Windows UI Automation (UIA) action handlers for NewDoAuto.
Interacts with native Windows controls via COM UIAutomation interfaces.
"""

from typing import Any, Dict, Optional, Union
import time
import uiautomation as auto
from newdoauto.actions.base import ActionHandler
from newdoauto.core.evaluator import interpolate_variables
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext
from newdoauto.models.workflow import Action


class UIElementNotFoundError(Exception):
    """Raised when a requested Windows UI control cannot be located within the timeout."""
    pass


def resolve_uia_control(
    selector: Union[Dict[str, Any], str],
    timeout_seconds: float = 5.0,
    context: Optional[ExecutionContext] = None,
) -> auto.Control:
    """
    Resolves a target Windows UI element from a declarative selector specification.
    Supports hierarchical resolution: Top-level Window -> Child Control.
    """
    if context:
        selector = interpolate_variables(selector, context)

    start_time = time.time()

    # Parse selector format
    if isinstance(selector, str):
        # Shorthand parsing or single window class/name
        window_spec = {"ClassName": selector}
        control_spec = None
    elif isinstance(selector, dict):
        window_spec = selector.get("window", {})
        control_spec = selector.get("control", {})
    else:
        raise ValueError(f"Invalid selector format: {selector!r}")

    # 1. Locate Top-Level Window
    auto.SetGlobalSearchTimeout(min(timeout_seconds, 2.0))
    window_kwargs: Dict[str, Any] = {"searchDepth": 1}
    if isinstance(window_spec, str):
        window_kwargs["ClassName"] = window_spec
    elif isinstance(window_spec, dict):
        if "ClassName" in window_spec:
            window_kwargs["ClassName"] = window_spec["ClassName"]
        if "Name" in window_spec:
            window_kwargs["Name"] = window_spec["Name"]
        if "AutomationId" in window_spec:
            window_kwargs["AutomationId"] = window_spec["AutomationId"]

    win = auto.WindowControl(**window_kwargs)
    while not win.Exists(maxSearchSeconds=0.5):
        if context and context.cancellation_token.is_cancelled():
            context.cancellation_token.throw_if_cancelled()
        if time.time() - start_time > timeout_seconds:
            raise UIElementNotFoundError(
                f"Top-level window matching {window_spec} was not found after {timeout_seconds:.1f}s"
            )
        time.sleep(0.2)

    # If no child control specified, return the window control itself
    if not control_spec:
        return win

    # 2. Locate Target Child Control within Window
    depth = int(control_spec.get("searchDepth", 4))
    has_props = any(k in control_spec for k in ("ControlTypeName", "ClassName", "AutomationId", "Name"))

    if not has_props:
        # Default/auto-detect standard text document or edit control (Win11 DocumentControl / Win10 EditControl)
        ctrl = win.DocumentControl(searchDepth=depth)
        if not ctrl.Exists(maxSearchSeconds=0.5):
            ctrl = win.EditControl(searchDepth=depth)
    else:
        ctrl_kwargs: Dict[str, Any] = {"searchDepth": depth}
        if "ControlTypeName" in control_spec:
            ctrl_kwargs["ControlTypeName"] = control_spec["ControlTypeName"]
        if "ClassName" in control_spec:
            ctrl_kwargs["ClassName"] = control_spec["ClassName"]
        if "Name" in control_spec:
            ctrl_kwargs["Name"] = control_spec["Name"]
        if "AutomationId" in control_spec:
            ctrl_kwargs["AutomationId"] = control_spec["AutomationId"]
        ctrl = win.Control(**ctrl_kwargs)

    while not ctrl.Exists(maxSearchSeconds=0.5):
        if context and context.cancellation_token.is_cancelled():
            context.cancellation_token.throw_if_cancelled()
        if time.time() - start_time > timeout_seconds:
            raise UIElementNotFoundError(
                f"Child control matching {control_spec} was not found inside window '{win.Name}' after {timeout_seconds:.1f}s"
            )
        time.sleep(0.2)

    return ctrl


class UiaFindHandler(ActionHandler):
    """Finds an element and returns its metadata."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        selector = action.params["selector"]
        timeout = float(action.params.get("timeout_seconds", action.timeout_seconds))

        logger.info(f"Searching for UI element: {selector}")
        ctrl = resolve_uia_control(selector, timeout_seconds=timeout, context=context)

        rect = ctrl.BoundingRectangle
        info = {
            "name": ctrl.Name,
            "control_type": ctrl.ControlTypeName,
            "class_name": ctrl.ClassName,
            "automation_id": ctrl.AutomationId,
            "bounding_box": [rect.left, rect.top, rect.right, rect.bottom] if rect else None,
            "is_enabled": ctrl.IsEnabled,
        }
        logger.info(f"UI element found: '{ctrl.Name}' ({ctrl.ControlTypeName})")
        return info


class UiaGetTextHandler(ActionHandler):
    """Reads text from a Windows UI element (via ValuePattern, TextPattern, or Name)."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        selector = action.params["selector"]
        timeout = float(action.params.get("timeout_seconds", action.timeout_seconds))

        ctrl = resolve_uia_control(selector, timeout_seconds=timeout, context=context)

        # 1. Try ValuePattern
        vp = ctrl.GetValuePattern()
        if vp is not None:
            val = vp.Value
            logger.info(f"Read text via ValuePattern: {val!r}")
            return val

        # 2. Try TextPattern (for rich text/documents like modern Notepad)
        tp = ctrl.GetTextPattern()
        if tp is not None:
            text = tp.DocumentRange.GetText(-1)
            logger.info(f"Read text via TextPattern: {text!r}")
            return text

        # 3. Fallback to control Name
        val = ctrl.Name
        logger.info(f"Read text via Name property: {val!r}")
        return val


class UiaSetTextHandler(ActionHandler):
    """Enters text into a Windows UI element using ValuePattern or simulated keystrokes."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        selector = action.params["selector"]
        text = str(interpolate_variables(action.params["text"], context))
        timeout = float(action.params.get("timeout_seconds", action.timeout_seconds))
        mode = action.params.get("mode", "auto")  # "auto", "value_pattern", "send_keys"

        ctrl = resolve_uia_control(selector, timeout_seconds=timeout, context=context)
        logger.info(f"Setting text on '{ctrl.Name}' ({ctrl.ControlTypeName}): {text!r}")

        # Attempt ValuePattern first if auto or value_pattern
        if mode in ("auto", "value_pattern"):
            vp = ctrl.GetValuePattern()
            if vp is not None:
                vp.SetValue(text)
                logger.info("Successfully set text using ValuePattern")
                return {"mode": "value_pattern", "text": text}

        # Fallback to focusing and sending keystrokes
        ctrl.SetFocus()
        time.sleep(0.1)
        ctrl.SendKeys(text)
        logger.info("Successfully set text using SendKeys")
        return {"mode": "send_keys", "text": text}


class UiaClickHandler(ActionHandler):
    """Clicks a Windows UI element using InvokePattern or physical cursor click."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        selector = action.params["selector"]
        timeout = float(action.params.get("timeout_seconds", action.timeout_seconds))
        mode = action.params.get("mode", "auto")  # "auto", "invoke", "click"

        ctrl = resolve_uia_control(selector, timeout_seconds=timeout, context=context)
        logger.info(f"Clicking element '{ctrl.Name}' ({ctrl.ControlTypeName})")

        if mode in ("auto", "invoke"):
            ip = ctrl.GetInvokePattern()
            if ip is not None:
                ip.Invoke()
                logger.info("Clicked element using InvokePattern")
                return {"mode": "invoke"}

        ctrl.Click(simulateMove=False)
        logger.info("Clicked element using UI Automation Click")
        return {"mode": "click"}
