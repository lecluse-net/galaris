"""
Tests for model_scanner.py - Model scanning functionality
"""
import pytest
from unittest.mock import Mock, patch

from core.authorize import scan_models, _get_all_subclasses
from core.authorize import RuleProvider, ResourceRule


class TestGetAllSubclasses:
    """Tests for _get_all_subclasses helper function."""

    def test_single_level(self):
        """Test getting subclasses one level deep."""
        
        class Parent:
            pass
        
        class Child1(Parent):
            pass
        
        class Child2(Parent):
            pass
        
        result = _get_all_subclasses(Parent)
        
        assert len(result) == 2
        assert Child1 in result
        assert Child2 in result

    def test_multi_level(self):
        """Test getting subclasses multiple levels deep."""
        
        class GrandParent:
            pass
        
        class Parent(GrandParent):
            pass
        
        class Child(Parent):
            pass
        
        result = _get_all_subclasses(GrandParent)
        
        assert len(result) == 2
        assert Parent in result
        assert Child in result

    def test_no_subclasses(self):
        """Test class with no subclasses."""
        
        class Lonely:
            pass
        
        result = _get_all_subclasses(Lonely)
        
        assert result == []


class TestScanModels:
    """Tests for scan_models function."""

    def test_scan_no_models_with_rules(self):
        """Test scanning when no models have _authorize_rules."""
        provider = RuleProvider()
        
        # Mock Base to have no subclasses with rules
        with patch('core.authorize.model_scanner._get_all_subclasses', return_value=[]):
            count = scan_models(provider)
        
        assert count == 0
        assert len(provider.get_all()) == 0

    def test_scan_models_with_rules(self):
        """Test scanning models with _authorize_rules attribute."""
        provider = RuleProvider()
        
        # Create a mock model class (not a real SQLAlchemy model)
        class MockModel:
            __name__ = "MockModel"
            _authorize_rules = [
                ResourceRule(privileges=["READ"]),
                ResourceRule(privileges=["WRITE"]),
            ]
        
        # Mock _get_all_subclasses to return our mock model
        with patch('core.authorize.model_scanner._get_all_subclasses', return_value=[MockModel]):
            count = scan_models(provider)
        
        assert count == 2
        assert provider.has("MockModel")
        rules = provider.get("MockModel")
        assert len(rules) == 2

    def test_scan_skips_models_without_rules(self):
        """Test that models without _authorize_rules are skipped."""
        provider = RuleProvider()
        
        # Create a mock model class without _authorize_rules
        class MockModelNoRules:
            __name__ = "MockModelNoRules"
        
        with patch('core.authorize.model_scanner._get_all_subclasses', return_value=[MockModelNoRules]):
            count = scan_models(provider)
        
        assert count == 0
        assert not provider.has("MockModelNoRules")

    def test_scan_empty_rules_list(self):
        """Test that models with empty _authorize_rules list are skipped."""
        provider = RuleProvider()
        
        class MockModelEmptyRules:
            __name__ = "MockModelEmptyRules"
            _authorize_rules = []
        
        with patch('core.authorize.model_scanner._get_all_subclasses', return_value=[MockModelEmptyRules]):
            count = scan_models(provider)
        
        assert count == 0

    def test_scan_multiple_models(self):
        """Test scanning multiple models."""
        provider = RuleProvider()
        
        class Model1:
            __name__ = "Model1"
            _authorize_rules = [ResourceRule(privileges=["READ"])]
        
        class Model2:
            __name__ = "Model2"
            _authorize_rules = [ResourceRule(privileges=["WRITE"])]
        
        class Model3:
            __name__ = "Model3"
            # No rules
        
        with patch('core.authorize.model_scanner._get_all_subclasses', return_value=[Model1, Model2, Model3]):
            count = scan_models(provider)
        
        assert count == 2
        assert provider.has("Model1")
        assert provider.has("Model2")
        assert not provider.has("Model3")
