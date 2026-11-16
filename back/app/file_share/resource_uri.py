"""Compatibility surface for the shared canonical resource URI contract."""

from core.util import (
    FUTURE_RESOURCE_SCHEMES as FUTURE_RESOURCE_SCHEMES,
    NATIVE_RESOURCE_SCHEMES as NATIVE_RESOURCE_SCHEMES,
    PROTOCOL_SCHEMES as PROTOCOL_SCHEMES,
    RESERVED_TOOL_CODES as RESERVED_TOOL_CODES,
    RESOURCE_SCHEME_PATTERN as RESOURCE_SCHEME_PATTERN,
    SYSTEM_SERVICE_CODES as SYSTEM_SERVICE_CODES,
    InvalidResourceServiceCodeError as InvalidResourceServiceCodeError,
    ResourceRevisionConflict as ResourceRevisionConflict,
    ResourceUri as ResourceUri,
    ResourceUriError as ResourceUriError,
    ResourceValidationError as ResourceValidationError,
    parse_resource_uri as parse_resource_uri,
    validate_external_service_code as validate_external_service_code,
)
