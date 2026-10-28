"""
Action handler registry for NewDoAuto.
Provides decoupled registration and lookup of action execution implementations.
"""

from typing import Dict
from newdoauto.actions.base import ActionHandler
from newdoauto.actions.app_actions import AppLaunchHandler, AppCloseHandler
from newdoauto.actions.uia_actions import (
    UiaFindHandler,
    UiaGetTextHandler,
    UiaSetTextHandler,
    UiaClickHandler,
)
from newdoauto.actions.flow_actions import (
    FlowWaitHandler,
    FlowSetVariableHandler,
    FlowIfElseHandler,
)
from newdoauto.actions.log_actions import LogWriteHandler


class ActionRegistry:
    """Registry maintaining mappings from action type strings to ActionHandler instances."""

    def __init__(self):
        self._handlers: Dict[str, ActionHandler] = {}
        self.register_defaults()

    def register(self, action_type: str, handler: ActionHandler) -> None:
        self._handlers[action_type] = handler

    def get(self, action_type: str) -> ActionHandler:
        if action_type not in self._handlers:
            raise KeyError(
                f"No handler registered for action type '{action_type}'. "
                f"Available: {sorted(list(self._handlers.keys()))}"
            )
        return self._handlers[action_type]

    def register_defaults(self) -> None:
        """Registers the built-in standard action handlers."""
        self.register("app.launch", AppLaunchHandler())
        self.register("app.close", AppCloseHandler())
        self.register("uia.find", UiaFindHandler())
        self.register("uia.get_text", UiaGetTextHandler())
        self.register("uia.set_text", UiaSetTextHandler())
        self.register("uia.click", UiaClickHandler())
        self.register("flow.wait", FlowWaitHandler())
        self.register("flow.set_variable", FlowSetVariableHandler())
        self.register("flow.if_else", FlowIfElseHandler())
        self.register("log.write", LogWriteHandler())
