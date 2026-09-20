"""
Pydantic schemas for the index onboarding module.
"""
from pydantic import BaseModel


class OnboardingStatusResponse(BaseModel):
    """
    State controlling whether one onboarding block should be displayed.
    
    ``show`` requires both the privilege and an empty module. ``has_privilege``
    and ``has_data`` expose the underlying conditions.
    """
    show: bool
    has_privilege: bool
    has_data: bool


class OnboardingOverviewResponse(BaseModel):
    """
    Complete onboarding state for all supported modules.

    ``llm_provider`` is kept as the stable API field name. Its ``has_data``
    flag means that at least one configured chat-capable LLM is backed by an
    active provider, not merely that a provider row exists.

    ``connections`` is likewise stable and specifically represents an active
    connection owned by an enabled messaging bridge.
    """
    llm_provider: OnboardingStatusResponse
    tools: OnboardingStatusResponse
    connections: OnboardingStatusResponse
    agents: OnboardingStatusResponse
    skills: OnboardingStatusResponse
    processes: OnboardingStatusResponse
    # Kept for API compatibility; clients should use the status objects above.
    skills_access: bool
    processes_access: bool
