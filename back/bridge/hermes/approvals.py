"""Consume historical Hermes interactions without affecting a current runtime call."""

from app.messenger.interactions import ChoiceResolution, PendingChoice, register_choice_handler

HERMES_APPROVAL_INTERACTION = "hermes_approval"


async def _handle_hermes_approval(interaction: PendingChoice, resolution: ChoiceResolution) -> None:
    # Old run-only identities cannot identify the current SDK callback. All options,
    # including denial, are obsolete; app.tools owns current one-action decisions.
    return


register_choice_handler(HERMES_APPROVAL_INTERACTION, _handle_hermes_approval)
