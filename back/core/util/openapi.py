"""
Utilities for generating and filtering OpenAPI schemas.

Filter OpenAPI schemas by criteria such as public or internal routes.
"""

from typing import Callable, Dict, Any
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


def filter_schema(
    openapi_schema: Dict[str, Any],
    path_predicate: Callable[[str], bool],
    tag_predicate: Callable[[str], bool]
) -> Dict[str, Any]:
    """
    Filter an OpenAPI schema with path and tag predicates.

    Args:
        openapi_schema: OpenAPI schema to filter.
        path_predicate: Return true for paths to retain.
        tag_predicate: Return true for tag names to retain.

    Returns:
        A filtered schema copy.
    """
    filtered_schema = openapi_schema.copy()

    # Filter paths (routes).
    if "paths" in filtered_schema:
        filtered_paths = {}
        for path, methods in filtered_schema["paths"].items():
            if path_predicate(path):
                filtered_paths[path] = methods
        filtered_schema["paths"] = filtered_paths

    # Filter tags.
    if "tags" in filtered_schema:
        filtered_schema["tags"] = [
            tag for tag in filtered_schema["tags"]
            if tag_predicate(tag.get("name", ""))
        ]

    return filtered_schema


def generate_filtered_openapi(
    app: FastAPI,
    title: str,
    version: str,
    description: str,
    path_predicate: Callable[[str], bool],
    tag_predicate: Callable[[str], bool]
) -> Dict[str, Any]:
    """
    Generate a filtered application OpenAPI schema.

    Args:
        app: The FastAPI application.
        title: Schema title.
        version: Schema version.
        description: Schema description.
        path_predicate: Path filter function.
        tag_predicate: Tag filter function.

    Returns:
        The filtered OpenAPI schema.
    """
    openapi_schema = get_openapi(
        title=title,
        version=version,
        description=description,
        routes=app.routes,
    )
    return filter_schema(openapi_schema, path_predicate, tag_predicate)


# Predicates for common cases.

def is_not_internal_path(path: str) -> bool:
    """Return whether the path does not start with /internal."""
    return not path.startswith("/internal")


def is_internal_path(path: str) -> bool:
    """Return whether the path starts with /internal."""
    return path.startswith("/internal")


def is_not_internal_tag(tag_name: str) -> bool:
    """Return whether the tag does not start with ``internal-``."""
    return not tag_name.startswith("internal-")


def is_internal_tag(tag_name: str) -> bool:
    """Return whether the tag starts with ``internal-``."""
    return tag_name.startswith("internal-")
