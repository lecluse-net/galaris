"""
Onboarding module for configuration-state checks.

Its API determines whether setup guidance should appear on the home page from
the current user's privileges and the presence of data in each module.
"""
from .router import router

__all__ = ["router"]
