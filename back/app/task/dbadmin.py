"""Task data convergence contributions."""

from core.dbadmin import DbAdminRegistry
from .html_migration import register_html_conversion


def register_dbadmin(registry: DbAdminRegistry) -> None:
    register_html_conversion(registry)
