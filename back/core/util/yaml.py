"""
Utilities for reading and validating YAML files.

This module can load YAML with environment substitution, clean values, validate
against JSON Schema, and load environment variables from .env files.

Example:
    >>> from core.util import load_yaml_file, validate_schema
    >>> data = load_yaml_file("config.yaml", env_file=".env")
    >>> validate_schema(data, schema)
"""

import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from dotenv import load_dotenv

# jsonschema is optional and untyped; only some modules use validation. Keep it
# as Any so strict checking remains useful elsewhere.
try:
    import jsonschema as _jsonschema  # type: ignore[import-untyped]
except ImportError:
    _jsonschema = None

jsonschema: Any = _jsonschema
JSONSCHEMA_AVAILABLE = jsonschema is not None


class YAMLValidationError(Exception):
    """Raised when YAML validation fails."""
    pass


class YAMLProcessingError(Exception):
    """Raised when YAML processing fails."""
    pass


class YAMLProcessor:
    """
    YAML processor with environment substitution and value cleaning.
    
    Load YAML files and apply environment substitution and cleanup transformations.
    
    Environment syntax:
        - ${VAR}: use VAR's value.
        - ${VAR:default}: use VAR or "default".
    
    Attributes:
        env_file: Optional .env file to load.
        clean_values: Trim and normalize strings when true.
        exclude_keys: Keys whose values must remain untouched.
    """
    
    def __init__(
        self,
        env_file: Optional[Union[str, Path]] = None,
        clean_values: bool = True,
        exclude_keys: Optional[List[str]] = None
    ):
        """
        Initialize the YAML processor.
        
        Args:
            env_file: Optional .env file.
            clean_values: Whether to clean values.
            exclude_keys: Keys to exclude, for example ``['instructions']``.
        """
        self.clean_values = clean_values
        self.exclude_keys = exclude_keys or []
        self._env_loaded = False
        
        if env_file:
            self._load_env_file(env_file)
    
    def _load_env_file(self, env_file: Union[str, Path]) -> None:
        """
        Load a .env file.
        
        Args:
            env_file: Path to the .env file.
        """
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(dotenv_path=str(env_path), override=False)
            self._env_loaded = True
    
    def substitute_env_vars(self, value: Union[str, Any]) -> Union[str, Any]:
        """
        Replace environment variables in a value.
        
        Supported formats:
            - ${VAR}: use VAR or an empty string.
            - ${VAR:default}: use VAR or "default".
        
        Args:
            value: String or other value to process.
            
        Returns:
            Value with substitutions applied.
        """
        if not isinstance(value, str):
            return value
        
        # Match ${VAR} or ${VAR:default}.
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match: re.Match[str]) -> str:
            var_expr = match.group(1)
            if ':' in var_expr:
                var_name, default_value = var_expr.split(':', 1)
                return os.getenv(var_name, default_value)
            else:
                return os.getenv(var_expr, '')
        
        return re.sub(pattern, replace_var, value)
    
    def clean_value(self, value: Any) -> Any:
        """
        Clean a value by trimming whitespace, trailing commas, and surrounding quotes.
        
        Args:
            value: Value to clean.
            
        Returns:
            Cleaned value.
        """
        if not isinstance(value, str):
            return value

        # Trim whitespace.
        value = value.strip()
        
        # Remove trailing commas.
        value = value.rstrip(',')
        
        # Remove surrounding quotes.
        if len(value) >= 2:
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
        
        return value.strip()
    
    def process_value(self, value: Any) -> Any:
        """
        Process one value with substitution and cleanup.
        
        Args:
            value: Value to process.
            
        Returns:
            Processed value.
        """
        if isinstance(value, str):
            # Substitute variables.
            value = self.substitute_env_vars(value)
            # Clean when enabled.
            if self.clean_values:
                value = self.clean_value(value)
            return value
        elif isinstance(value, dict):
            return self.process_dict(cast(Dict[str, Any], value))
        elif isinstance(value, list):
            return self.process_list(cast(List[Any], value))
        else:
            return value
    
    def process_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively process every dictionary value.
        
        Values under ``exclude_keys`` pass through without substitution or cleanup.
        
        Args:
            data: Dictionary to process.
            
        Returns:
            Processed dictionary.
        """
        result: Dict[str, Any] = {}
        for key, value in data.items():
            # Preserve excluded values exactly.
            if key in self.exclude_keys:
                result[key] = value
            else:
                result[key] = self.process_value(value)
        return result
    
    def process_list(self, data: List[Any]) -> List[Any]:
        """
        Recursively process every list item.
        
        Args:
            data: List to process.
            
        Returns:
            Processed list.
        """
        return [self.process_value(item) for item in data]
    
    def load_file(self, file_path: Union[str, Path]) -> Any:
        """
        Load and process a YAML file.
        
        Args:
            file_path: YAML file path.
            
        Returns:
            Processed YAML data.
            
        Raises:
            YAMLProcessingError: When the file cannot be loaded.
        """
        path = Path(file_path)
        
        if not path.exists():
            raise YAMLProcessingError(f"File not found: {file_path}")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise YAMLProcessingError(f"YAML parsing failed: {e}")
        except Exception as e:
            raise YAMLProcessingError(f"YAML loading failed: {e}")
        
        if data is None:
            return None
        
        return self.process_value(data)


def deep_merge(base: Dict[str, Any], diff: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in diff.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(
                cast(Dict[str, Any], result[key]), cast(Dict[str, Any], value)
            )
        else:
            result[key] = value
    return result


def yaml_update(original: str, diff: Dict[str, Any]) -> str:
    """Merge ``diff`` into the original YAML and return updated YAML.

    Keys absent from ``diff`` remain intact, nested dictionaries merge recursively,
    ``None`` deletes a key, and lists are replaced as a whole.
    """
    base = cast(Dict[str, Any], yaml.safe_load(original) or {})  # type: ignore[reportUnknownMemberType]
    merged = deep_merge(base, diff)
    return cast(str, yaml.dump(merged, allow_unicode=True, sort_keys=False))  # type: ignore[reportUnknownMemberType]


def load_yaml_file(
    file_path: Union[str, Path],
    env_file: Optional[Union[str, Path]] = None,
    clean_values: bool = True
) -> Any:
    """
    Load YAML with environment substitution and cleanup.
    
    This is a convenience wrapper around YAMLProcessor.
    
    Args:
        file_path: YAML file path.
        env_file: Optional .env file path.
        clean_values: Whether to clean values.
        
    Returns:
        Processed YAML data.
        
    Example:
        >>> data = load_yaml_file("config.yaml", env_file=".env")
    """
    processor = YAMLProcessor(env_file=env_file, clean_values=clean_values)
    return processor.load_file(file_path)


def validate_schema(data: Any, schema: Dict[str, Any]) -> None:
    """
    Validate data against JSON Schema.
    
    Args:
        data: Data to validate.
        schema: JSON Schema.
        
    Raises:
        YAMLValidationError: When validation fails.
        ImportError: When jsonschema is not installed.
        
    Example:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "name": {"type": "string"}
        ...     },
        ...     "required": ["name"]
        ... }
        >>> validate_schema(data, schema)
    """
    if jsonschema is None:
        raise ImportError(
            "The 'jsonschema' library is required for validation. "
            "Install it with: pip install jsonschema"
        )

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        message = cast(str, e.message)
        path = cast("list[str | int]", list(e.path))
        raise YAMLValidationError(
            f"Validation failed: {message} (path: {path})"
        ) from e


def load_and_validate(
    file_path: Union[str, Path],
    schema: Dict[str, Any],
    env_file: Optional[Union[str, Path]] = None,
    clean_values: bool = True,
    exclude_keys: Optional[List[str]] = None
) -> Any:
    """
    Load a YAML file and validate it against a schema.
    
    This combines ``load_yaml_file`` and ``validate_schema``.
    
    Args:
        file_path: YAML file path.
        schema: JSON Schema.
        env_file: Optional .env file path.
        clean_values: Whether to clean values.
        exclude_keys: Keys to exclude from processing.
        
    Returns:
        Validated YAML data.
        
    Raises:
        YAMLProcessingError: When loading fails.
        YAMLValidationError: When validation fails.
        
    Example:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "name": {"type": "string"}
        ...     },
        ...     "required": ["name"]
        ... }
        >>> data = load_and_validate("config.yaml", schema, env_file=".env")
    """
    processor = YAMLProcessor(env_file=env_file, clean_values=clean_values, exclude_keys=exclude_keys)
    data = processor.load_file(file_path)
    validate_schema(data, schema)
    return data
