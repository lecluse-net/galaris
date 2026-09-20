"""
Resource Rule Provider for RBAC.

Inspired by unicaen-framework's RuleProvider.php and Rule.php.
Manages rules that associate resource types with privileges and assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type, Union

from .assertions import BaseAssertion


@dataclass
class ResourceRule:
    """
    A single authorization rule for a resource type.

    Mirrors PHP's Rule class with: privileges, params, assertion.
    """
    privileges: List[str] = field(default_factory=lambda: [])
    params: Dict[str, Any] = field(default_factory=lambda: {})
    assertion: Optional[Union[Type[BaseAssertion], Callable[..., Any]]] = None


class RuleProvider:
    """
    Registry of resource authorization rules.

    Inspired by unicaen-framework's RuleProvider.php.
    Rules are indexed by resource type (string key, typically the model class name
    or a custom resource identifier).

    Multiple rules can be registered per resource type, allowing different
    privilege/assertion combinations for the same resource.
    """

    def __init__(self) -> None:
        self._rules: Dict[str, List[ResourceRule]] = {}

    def has(self, resource_type: str) -> bool:
        """Check if any rules exist for a resource type."""
        return resource_type in self._rules

    def add(self, resource_type: str, rule: ResourceRule) -> None:
        """
        Add a rule for a resource type.

        Multiple rules can be added for the same resource type.
        """
        if not self.has(resource_type):
            self._rules[resource_type] = []
        self._rules[resource_type].append(rule)

    def get(self, resource_type: str) -> List[ResourceRule]:
        """Get all rules for a resource type."""
        return self._rules.get(resource_type, [])

    def get_all(self) -> Dict[str, List[ResourceRule]]:
        """Get the entire rules registry."""
        return self._rules

    def remove(self, resource_type: str) -> bool:
        """Remove all rules for a resource type. Returns True if removed."""
        if not self.has(resource_type):
            return False
        del self._rules[resource_type]
        return True

    def find_matching_rule(self, resource_type: str, privilege: Optional[str] = None) -> Optional[ResourceRule]:
        """
        Find the first rule matching the resource type and privilege.

        If privilege is None, returns the first rule with no privileges defined.
        If privilege is provided, returns the first rule containing that privilege.

        This mirrors PHP's ruleMatch() logic.
        """
        rules = self.get(resource_type)
        for rule in rules:
            if privilege is None:
                if not rule.privileges:
                    return rule
            else:
                if privilege in rule.privileges:
                    return rule
        return None
