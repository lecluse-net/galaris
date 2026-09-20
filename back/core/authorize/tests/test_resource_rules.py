"""
Tests for resource_rules.py - RuleProvider and ResourceRule
"""
import pytest
from unittest.mock import Mock

from core.authorize import RuleProvider, ResourceRule
from core.authorize import BaseAssertion, AssertionContext


class DummyAssertion(BaseAssertion):
    """Dummy assertion for testing."""
    async def assert_(self, context: AssertionContext) -> bool:
        return True


class TestResourceRule:
    """Tests for ResourceRule dataclass."""

    def test_default_initialization(self):
        """Test ResourceRule with default values."""
        rule = ResourceRule()
        
        assert rule.privileges == []
        assert rule.params == {}
        assert rule.assertion is None

    def test_full_initialization(self):
        """Test ResourceRule with all fields."""
        rule = ResourceRule(
            privileges=["READ", "WRITE"],
            params={"key": "value"},
            assertion=DummyAssertion,
        )
        
        assert rule.privileges == ["READ", "WRITE"]
        assert rule.params == {"key": "value"}
        assert rule.assertion == DummyAssertion


class TestRuleProvider:
    """Tests for RuleProvider class."""

    def test_initialization(self):
        """Test RuleProvider initialization."""
        provider = RuleProvider()
        assert provider._rules == {}

    def test_add_and_get(self):
        """Test adding and retrieving rules."""
        provider = RuleProvider()
        rule = ResourceRule(privileges=["READ"])
        
        provider.add("Agent", rule)
        rules = provider.get("Agent")
        
        assert len(rules) == 1
        assert rules[0] == rule

    def test_has_existing(self):
        """Test has() with existing resource type."""
        provider = RuleProvider()
        provider.add("Agent", ResourceRule())
        
        result = provider.has("Agent")
        
        assert result is True

    def test_has_missing(self):
        """Test has() with missing resource type."""
        provider = RuleProvider()
        
        result = provider.has("Missing")
        
        assert result is False

    def test_get_missing(self):
        """Test get() with missing resource type."""
        provider = RuleProvider()
        
        result = provider.get("Missing")
        
        assert result == []

    def test_get_all(self):
        """Test get_all() returns all rules."""
        provider = RuleProvider()
        rule1 = ResourceRule(privileges=["READ"])
        rule2 = ResourceRule(privileges=["WRITE"])
        
        provider.add("Agent", rule1)
        provider.add("Connection", rule2)
        all_rules = provider.get_all()
        
        assert len(all_rules) == 2
        assert "Agent" in all_rules
        assert "Connection" in all_rules

    def test_remove_existing(self):
        """Test remove() with existing resource type."""
        provider = RuleProvider()
        provider.add("Agent", ResourceRule())
        
        result = provider.remove("Agent")
        
        assert result is True
        assert provider.has("Agent") is False

    def test_remove_missing(self):
        """Test remove() with missing resource type."""
        provider = RuleProvider()
        
        result = provider.remove("Missing")
        
        assert result is False

    def test_multiple_rules_per_resource(self):
        """Test adding multiple rules for same resource type."""
        provider = RuleProvider()
        rule1 = ResourceRule(privileges=["READ"])
        rule2 = ResourceRule(privileges=["WRITE"])
        
        provider.add("Agent", rule1)
        provider.add("Agent", rule2)
        rules = provider.get("Agent")
        
        assert len(rules) == 2

    def test_find_matching_rule_with_privilege(self):
        """Test find_matching_rule() with specific privilege."""
        provider = RuleProvider()
        rule1 = ResourceRule(privileges=["READ", "LIST"])
        rule2 = ResourceRule(privileges=["WRITE", "DELETE"])
        
        provider.add("Agent", rule1)
        provider.add("Agent", rule2)
        
        result = provider.find_matching_rule("Agent", "WRITE")
        
        assert result == rule2

    def test_find_matching_rule_no_privilege(self):
        """Test find_matching_rule() with no privilege (finds rule with no privileges)."""
        provider = RuleProvider()
        rule1 = ResourceRule(privileges=["READ"])
        rule2 = ResourceRule(privileges=[])  # No privileges
        
        provider.add("Agent", rule1)
        provider.add("Agent", rule2)
        
        result = provider.find_matching_rule("Agent", None)
        
        assert result == rule2

    def test_find_matching_rule_missing_resource(self):
        """Test find_matching_rule() with missing resource type."""
        provider = RuleProvider()
        
        result = provider.find_matching_rule("Missing", "READ")
        
        assert result is None

    def test_find_matching_rule_no_match(self):
        """Test find_matching_rule() when no rule matches the privilege."""
        provider = RuleProvider()
        rule = ResourceRule(privileges=["READ"])
        
        provider.add("Agent", rule)
        
        result = provider.find_matching_rule("Agent", "WRITE")
        
        assert result is None
