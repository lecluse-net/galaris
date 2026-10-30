"""Resolve an explicit country in the application's free-form location, offline."""

from __future__ import annotations

from app.memory import ContactCoordinates
from core.params import runtime_settings
from core.util import country_from_localization


def default_country() -> str:
    return country_from_localization(runtime_settings.LOCALIZATION)


def apply_country_defaults(coordinates: ContactCoordinates | None) -> ContactCoordinates | None:
    if coordinates is None:
        return None
    country = default_country()
    return ContactCoordinates(
        phone_numbers=[phone.model_copy(update={"country": country})
            if "country" not in phone.model_fields_set else phone for phone in coordinates.phone_numbers],
        postal_addresses=[address.model_copy(update={"country": country})
            if "country" not in address.model_fields_set else address for address in coordinates.postal_addresses],
    )
