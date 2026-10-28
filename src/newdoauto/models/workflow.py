"""
Workflow data models for NewDoAuto.
Defines the declarative, versioned JSON data structures for automation workflows.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json
import uuid


@dataclass
class ErrorPolicy:
    """Error handling configuration for an action."""
    policy: str = "stop"  # "stop", "continue", "retry"
    max_retries: int = 0
    retry_delay_seconds: float = 1.0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> ErrorPolicy:
        if not data:
            return cls()
        return cls(
            policy=data.get("policy", "stop"),
            max_retries=int(data.get("max_retries", 0)),
            retry_delay_seconds=float(data.get("retry_delay_seconds", 1.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
        }


@dataclass
class Action:
    """Represents a single executable automation step."""
    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 10.0
    on_error: ErrorPolicy = field(default_factory=ErrorPolicy)
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Action:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            type=data["type"],
            params=data.get("params", {}),
            timeout_seconds=float(data.get("timeout_seconds", 10.0)),
            on_error=ErrorPolicy.from_dict(data.get("on_error")),
            description=data.get("description"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "timeout_seconds": self.timeout_seconds,
            "on_error": self.on_error.to_dict(),
        }
        if self.description:
            result["description"] = self.description
        return result


@dataclass
class Workflow:
    """Declarative workflow specification containing metadata, initial variables, and actions."""
    name: str
    actions: List[Action] = field(default_factory=list)
    schema_version: str = "1.0.0"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Workflow:
        actions_raw = data.get("actions", [])
        actions = [Action.from_dict(act) for act in actions_raw]
        return cls(
            name=data["name"],
            actions=actions,
            schema_version=data.get("schema_version", "1.0.0"),
            id=data.get("id", str(uuid.uuid4())),
            description=data.get("description"),
            variables=data.get("variables", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> Workflow:
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "variables": self.variables,
            "actions": [act.to_dict() for act in self.actions],
        }
        if self.description:
            result["description"] = self.description
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
