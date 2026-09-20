"""Comprehensive unit tests for ``core.util.yaml`` and YAMLProcessor behavior."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.util import (
    YAMLProcessor,
    YAMLValidationError,
    YAMLProcessingError,
    load_yaml_file,
    validate_schema,
    load_and_validate,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def processor():
    """Provide a basic YAMLProcessor."""
    return YAMLProcessor(clean_values=True)


@pytest.fixture
def processor_no_clean():
    """Provide a YAMLProcessor with cleaning disabled."""
    return YAMLProcessor(clean_values=False)


@pytest.fixture
def temp_yaml_file():
    """Provide a factory for temporary YAML files."""
    def _create(content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(content)
            return Path(f.name)
    return _create


@pytest.fixture
def temp_env_file():
    """Provide a factory for temporary .env files."""
    def _create(content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False, encoding='utf-8') as f:
            f.write(content)
            return Path(f.name)
    return _create


# =============================================================================
# Environment-variable substitution tests.
# =============================================================================

class TestEnvVarSubstitution:
    """Tests for environment-variable substitution."""
    
    def test_substitute_simple_var(self, processor):
        """Test substitution of one variable."""
        with patch.dict(os.environ, {'TEST_VAR': 'test_value'}):
            result = processor.substitute_env_vars('${TEST_VAR}')
            assert result == 'test_value'
    
    def test_substitute_var_with_default(self, processor):
        """Test substitution with a default value."""
        result = processor.substitute_env_vars('${NON_EXISTENT:default_value}')
        assert result == 'default_value'
    
    def test_substitute_var_without_default(self, processor):
        """Test an undefined variable without a default value."""
        # Ensure the variable does not exist.
        if 'NON_EXISTENT_VAR' in os.environ:
            del os.environ['NON_EXISTENT_VAR']
        result = processor.substitute_env_vars('${NON_EXISTENT_VAR}')
        assert result == ''
    
    def test_substitute_multiple_vars(self, processor):
        """Test substitution of multiple variables."""
        with patch.dict(os.environ, {'VAR1': 'value1', 'VAR2': 'value2'}):
            result = processor.substitute_env_vars('${VAR1} and ${VAR2}')
            assert result == 'value1 and value2'
    
    def test_substitute_mixed_vars_and_text(self, processor):
        """Test substitution mixed with text."""
        with patch.dict(os.environ, {'NAME': 'World'}):
            result = processor.substitute_env_vars('Hello ${NAME}!')
            assert result == 'Hello World!'
    
    def test_substitute_var_in_middle(self, processor):
        """Test substitution in the middle of a string."""
        with patch.dict(os.environ, {'MIDDLE': 'inserted'}):
            result = processor.substitute_env_vars('before${MIDDLE}after')
            assert result == 'beforeinsertedafter'
    
    def test_substitute_empty_var(self, processor):
        """Test substitution of an empty variable."""
        with patch.dict(os.environ, {'EMPTY': ''}):
            result = processor.substitute_env_vars('${EMPTY}')
            assert result == ''
    
    def test_substitute_special_chars_in_default(self, processor):
        """Test special characters in a default value."""
        result = processor.substitute_env_vars('${VAR:http://example.com}')
        assert result == 'http://example.com'
    
    def test_substitute_non_string_returns_unchanged(self, processor):
        """Test that non-string values are returned unchanged."""
        assert processor.substitute_env_vars(123) == 123
        assert processor.substitute_env_vars(None) is None
        assert processor.substitute_env_vars(['list']) == ['list']
        assert processor.substitute_env_vars({'key': 'value'}) == {'key': 'value'}
    
    def test_substitute_no_var_pattern(self, processor):
        """Test a string without a variable pattern."""
        result = processor.substitute_env_vars('no variables here')
        assert result == 'no variables here'
    
    def test_substitute_incomplete_var(self, processor):
        """Test an incomplete pattern without a closing brace."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            result = processor.substitute_env_vars('${VAR')
            # The pattern does not match, so the string remains unchanged.
            assert result == '${VAR'


# =============================================================================
# Value-cleaning tests.
# =============================================================================

class TestValueCleaning:
    """Tests for value cleaning."""
    
    def test_clean_trim_spaces(self, processor):
        """Test trimming leading and trailing spaces."""
        result = processor.clean_value('  value  ')
        assert result == 'value'
    
    def test_clean_remove_trailing_comma(self, processor):
        """Test removing a trailing comma."""
        result = processor.clean_value('value,')
        assert result == 'value'
    
    def test_clean_remove_trailing_comma_with_spaces(self, processor):
        """Test removing a trailing comma surrounded by spaces."""
        result = processor.clean_value('value , ')
        assert result == 'value'
    
    def test_clean_remove_double_quotes(self, processor):
        """Test removing double quotes."""
        result = processor.clean_value('"value"')
        assert result == 'value'
    
    def test_clean_remove_single_quotes(self, processor):
        """Test removing single quotes."""
        result = processor.clean_value("'value'")
        assert result == 'value'
    
    def test_clean_combined(self, processor):
        """Test combined space, comma, and quote cleaning."""
        result = processor.clean_value('  "value",  ')
        assert result == 'value'
    
    def test_clean_no_cleaning_needed(self, processor):
        """Test an already clean value."""
        result = processor.clean_value('value')
        assert result == 'value'
    
    def test_clean_empty_string(self, processor):
        """Test an empty string."""
        result = processor.clean_value('')
        assert result == ''
    
    def test_clean_only_quotes(self, processor):
        """Test a string containing only quotes."""
        result = processor.clean_value('""')
        assert result == ''
    
    def test_clean_non_string_returns_unchanged(self, processor):
        """Test that non-string values are returned unchanged."""
        assert processor.clean_value(123) == 123
        assert processor.clean_value(None) is None
        assert processor.clean_value(['list']) == ['list']
    
    def test_clean_no_cleaning_when_disabled(self, processor_no_clean):
        """Test that clean_values=False disables cleaning."""
        result = processor_no_clean.process_value('  "value",  ')
        # Substitution still runs but makes no change here.
        assert result == '  "value",  '


# =============================================================================
# Key-exclusion tests.
# =============================================================================

class TestKeyExclusion:
    """Tests for excluding keys from processing."""
    
    def test_exclude_single_key(self):
        """Test excluding one key."""
        processor = YAMLProcessor(exclude_keys=['instructions'])
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = {
                'name': '${VAR}',
                'instructions': '${VAR}'
            }
            result = processor.process_dict(data)
            
            assert result['name'] == 'replaced'
            assert result['instructions'] == '${VAR}'  # Preserved.
    
    def test_exclude_multiple_keys(self):
        """Test excluding multiple keys."""
        processor = YAMLProcessor(exclude_keys=['instructions', 'description'])
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = {
                'name': '${VAR}',
                'instructions': '${VAR}',
                'description': '${VAR}',
                'other': '${VAR}'
            }
            result = processor.process_dict(data)
            
            assert result['name'] == 'replaced'
            assert result['instructions'] == '${VAR}'  # Preserved.
            assert result['description'] == '${VAR}'   # Preserved.
            assert result['other'] == 'replaced'
    
    def test_exclude_nested_dict(self):
        """Test exclusion in a nested dictionary."""
        processor = YAMLProcessor(exclude_keys=['instructions'])
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = {
                'config': {
                    'name': '${VAR}',
                    'instructions': '${VAR}'
                }
            }
            result = processor.process_dict(data)
            
            assert result['config']['name'] == 'replaced'
            assert result['config']['instructions'] == '${VAR}'  # Preserved.
    
    def test_exclude_in_list(self):
        """Test exclusion in a list of dictionaries."""
        processor = YAMLProcessor(exclude_keys=['instructions'])
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = [
                {'name': '${VAR}', 'instructions': '${VAR}'},
                {'name': '${VAR}', 'instructions': '${VAR}'}
            ]
            result = processor.process_list(data)
            
            assert result[0]['name'] == 'replaced'
            assert result[0]['instructions'] == '${VAR}'  # Preserved.
            assert result[1]['name'] == 'replaced'
            assert result[1]['instructions'] == '${VAR}'  # Preserved.
    
    def test_no_exclusion_when_empty_list(self):
        """Test that an empty list excludes nothing."""
        processor = YAMLProcessor(exclude_keys=[])
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = {'instructions': '${VAR}'}
            result = processor.process_dict(data)
            
            assert result['instructions'] == 'replaced'
    
    def test_no_exclusion_when_none(self):
        """Test that None excludes nothing."""
        processor = YAMLProcessor(exclude_keys=None)
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            data = {'instructions': '${VAR}'}
            result = processor.process_dict(data)
            
            assert result['instructions'] == 'replaced'


# =============================================================================
# Recursive-processing tests.
# =============================================================================

class TestRecursiveProcessing:
    """Tests for recursive structure processing."""
    
    def test_process_nested_dict(self, processor):
        """Test processing a nested dictionary."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            data = {
                'level1': {
                    'level2': {
                        'value': '${VAR}'
                    }
                }
            }
            result = processor.process_dict(data)
            assert result['level1']['level2']['value'] == 'value'
    
    def test_process_list_in_dict(self, processor):
        """Test processing a list in a dictionary."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            data = {
                'items': ['${VAR}', '${VAR}']
            }
            result = processor.process_dict(data)
            assert result['items'] == ['value', 'value']
    
    def test_process_dict_in_list(self, processor):
        """Test processing a dictionary in a list."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            data = [
                {'name': '${VAR}'},
                {'name': '${VAR}'}
            ]
            result = processor.process_list(data)
            assert result[0]['name'] == 'value'
            assert result[1]['name'] == 'value'
    
    def test_process_deeply_nested(self, processor):
        """Test deeply nested processing."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            data = {
                'level1': [
                    {
                        'level2': [
                            {'level3': '${VAR}'}
                        ]
                    }
                ]
            }
            result = processor.process_value(data)
            assert result['level1'][0]['level2'][0]['level3'] == 'value'
    
    def test_process_mixed_types(self, processor):
        """Test processing mixed types."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            data = {
                'string': '${VAR}',
                'integer': 42,
                'boolean': True,
                'null': None,
                'list': [1, 2, 3],
                'dict': {'nested': '${VAR}'}
            }
            result = processor.process_dict(data)
            assert result['string'] == 'value'
            assert result['integer'] == 42
            assert result['boolean'] is True
            assert result['null'] is None
            assert result['list'] == [1, 2, 3]
            assert result['dict']['nested'] == 'value'


# =============================================================================
# File-loading tests.
# =============================================================================

class TestFileLoading:
    """Tests for loading YAML files."""
    
    def test_load_simple_file(self, temp_yaml_file, processor):
        """Test loading a basic YAML file."""
        content = """
name: test
value: 123
"""
        file_path = temp_yaml_file(content)
        result = processor.load_file(file_path)
        
        assert result['name'] == 'test'
        assert result['value'] == 123
        
        # Cleanup.
        file_path.unlink()
    
    def test_load_file_with_env_vars(self, temp_yaml_file):
        """Test loading with environment variables."""
        content = """
url: ${TEST_URL}
token: ${TEST_TOKEN:default}
"""
        file_path = temp_yaml_file(content)
        
        with patch.dict(os.environ, {'TEST_URL': 'http://example.com'}):
            processor = YAMLProcessor()
            result = processor.load_file(file_path)
            
            assert result['url'] == 'http://example.com'
            assert result['token'] == 'default'
        
        file_path.unlink()
    
    def test_load_file_not_found(self, processor):
        """Test the error for a missing file."""
        with pytest.raises(YAMLProcessingError) as exc_info:
            processor.load_file('/non/existent/file.yaml')
        
        assert 'not found' in str(exc_info.value).lower()
    
    def test_load_invalid_yaml(self, temp_yaml_file, processor):
        """Test the error for invalid YAML."""
        content = """
invalid: yaml: content: [
"""
        file_path = temp_yaml_file(content)
        
        with pytest.raises(YAMLProcessingError) as exc_info:
            processor.load_file(file_path)
        
        assert 'parsing' in str(exc_info.value).lower() or 'error' in str(exc_info.value).lower()
        
        file_path.unlink()
    
    def test_load_empty_file(self, temp_yaml_file, processor):
        """Test loading an empty file."""
        file_path = temp_yaml_file('')
        result = processor.load_file(file_path)
        
        assert result is None
        
        file_path.unlink()
    
    def test_load_file_with_excluded_keys(self, temp_yaml_file):
        """Test loading with excluded keys."""
        content = """
name: ${VAR}
instructions: ${VAR}
"""
        file_path = temp_yaml_file(content)
        
        with patch.dict(os.environ, {'VAR': 'replaced'}):
            processor = YAMLProcessor(exclude_keys=['instructions'])
            result = processor.load_file(file_path)
            
            assert result['name'] == 'replaced'
            assert result['instructions'] == '${VAR}'  # Preserved.
        
        file_path.unlink()


# =============================================================================
# .env file tests.
# =============================================================================

class TestEnvFileLoading:
    """Tests for loading .env files."""
    
    def test_load_with_env_file(self, temp_yaml_file, temp_env_file):
        """Test loading with a .env file."""
        yaml_content = """
url: ${API_URL}
"""
        env_content = """
API_URL=http://api.example.com
"""
        yaml_path = temp_yaml_file(yaml_content)
        env_path = temp_env_file(env_content)
        
        # Clean the environment so the value comes from the .env file.
        if 'API_URL' in os.environ:
            del os.environ['API_URL']
        
        processor = YAMLProcessor(env_file=env_path)
        result = processor.load_file(yaml_path)
        
        assert result['url'] == 'http://api.example.com'
        
        yaml_path.unlink()
        env_path.unlink()
    
    def test_env_file_override_existing(self, temp_yaml_file, temp_env_file):
        """Test that .env does not replace existing variables."""
        yaml_content = """
url: ${API_URL}
"""
        env_content = """
API_URL=http://from-env.com
"""
        yaml_path = temp_yaml_file(yaml_content)
        env_path = temp_env_file(env_content)
        
        # The variable already exists in the environment.
        with patch.dict(os.environ, {'API_URL': 'http://from-os.com'}):
            processor = YAMLProcessor(env_file=env_path)
            result = processor.load_file(yaml_path)
            
            # The operating-system environment value takes precedence.
            assert result['url'] == 'http://from-os.com'
        
        yaml_path.unlink()
        env_path.unlink()


# =============================================================================
# Schema-validation tests.
# =============================================================================

class TestSchemaValidation:
    """Tests for JSON schema validation."""
    
    def test_validate_valid_data(self):
        """Test validation of valid data."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
        data = {"name": "test"}
        
        # Must not raise.
        validate_schema(data, schema)
    
    def test_validate_invalid_data(self):
        """Test validation of invalid data."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
        data = {}  # Missing the required field.
        
        with pytest.raises(YAMLValidationError):
            validate_schema(data, schema)
    
    def test_validate_wrong_type(self):
        """Test validation with an invalid type."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"}
            }
        }
        data = {"count": "not an integer"}
        
        with pytest.raises(YAMLValidationError):
            validate_schema(data, schema)


# =============================================================================
# Utility-function tests.
# =============================================================================

class TestUtilityFunctions:
    """Tests for utility functions."""
    
    def test_load_yaml_file_function(self, temp_yaml_file):
        """Test load_yaml_file."""
        content = """
key: ${VAR}
"""
        file_path = temp_yaml_file(content)
        
        with patch.dict(os.environ, {'VAR': 'value'}):
            result = load_yaml_file(file_path)
            assert result['key'] == 'value'
        
        file_path.unlink()
    
    def test_load_and_validate_function(self, temp_yaml_file):
        """Test load_and_validate."""
        content = """
name: test
"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
        file_path = temp_yaml_file(content)
        
        result = load_and_validate(file_path, schema)
        assert result['name'] == 'test'
        
        file_path.unlink()
    
    def test_load_and_validate_with_invalid_data(self, temp_yaml_file):
        """Test load_and_validate with invalid data."""
        content = """
name: 123
"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }
        file_path = temp_yaml_file(content)
        
        with pytest.raises(YAMLValidationError):
            load_and_validate(file_path, schema)
        
        file_path.unlink()


# =============================================================================
# Edge-case tests.
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_var_with_colon_in_value(self, processor):
        """Test a variable with a colon in its value."""
        with patch.dict(os.environ, {'URL': 'http://example.com:8080'}):
            result = processor.substitute_env_vars('${URL}')
            assert result == 'http://example.com:8080'
    
    def test_var_with_special_chars_in_default(self, processor):
        """Test special characters in a default value."""
        result = processor.substitute_env_vars('${VAR:hello world!}')
        assert result == 'hello world!'
    
    def test_multiple_vars_same_string(self, processor):
        """Test multiple variables in one string."""
        with patch.dict(os.environ, {'A': '1', 'B': '2', 'C': '3'}):
            result = processor.substitute_env_vars('${A}-${B}-${C}')
            assert result == '1-2-3'
    
    def test_var_adjacent_to_text(self, processor):
        """Test a variable adjacent to text."""
        with patch.dict(os.environ, {'VAR': 'value'}):
            result = processor.substitute_env_vars('prefix${VAR}suffix')
            assert result == 'prefixvaluesuffix'
    
    def test_yaml_with_only_comments(self, temp_yaml_file, processor):
        """Test YAML containing comments only."""
        content = """
# This is a comment
# Another comment
"""
        file_path = temp_yaml_file(content)
        result = processor.load_file(file_path)
        assert result is None
        file_path.unlink()
    
    def test_very_long_value(self, processor):
        """Test a very long value."""
        long_value = 'x' * 10000
        with patch.dict(os.environ, {'LONG': long_value}):
            result = processor.substitute_env_vars('${LONG}')
            assert result == long_value
    
    def test_unicode_in_value(self, processor):
        """Test Unicode characters."""
        with patch.dict(os.environ, {'EMOJI': '🎉'}):
            result = processor.substitute_env_vars('${EMOJI}')
            assert result == '🎉'
    
    def test_newlines_in_value(self, processor):
        """Test newlines in a value."""
        with patch.dict(os.environ, {'MULTI': 'line1\nline2'}):
            result = processor.substitute_env_vars('${MULTI}')
            assert result == 'line1\nline2'


# =============================================================================
# Integration tests.
# =============================================================================

class TestIntegration:
    """End-to-end integration tests."""
    
    def test_full_workflow(self, temp_yaml_file, temp_env_file):
        """Test a complete workflow with .env loading and validation."""
        yaml_content = """
app:
  name: ${APP_NAME}
  url: ${APP_URL:http://localhost}
  instructions: |
    Connect to ${user_id}
"""
        env_content = """
APP_NAME=MyApp
"""
        schema = {
            "type": "object",
            "properties": {
                "app": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "instructions": {"type": "string"}
                    },
                    "required": ["name", "url"]
                }
            },
            "required": ["app"]
        }
        
        yaml_path = temp_yaml_file(yaml_content)
        env_path = temp_env_file(env_content)
        
        # Clean up.
        if 'APP_NAME' in os.environ:
            del os.environ['APP_NAME']
        
        # Load and validate.
        result = load_and_validate(
            yaml_path,
            schema,
            env_file=env_path,
            exclude_keys=['instructions']
        )
        
        assert result['app']['name'] == 'MyApp'
        assert result['app']['url'] == 'http://localhost'
        assert '${user_id}' in result['app']['instructions']  # Preserved.
        
        yaml_path.unlink()
        env_path.unlink()
