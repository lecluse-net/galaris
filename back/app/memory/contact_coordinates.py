"""Typed contact coordinates stored with their canonical private Memory item."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContactPhoneNumber(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(default="", max_length=80)
    number: str = Field(min_length=3, max_length=80)
    country: str = Field(default="", max_length=100)


class ContactPostalAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(default="", max_length=80)
    street: str = Field(default="", max_length=1000)
    postal_code: str = Field(default="", max_length=50)
    city: str = Field(default="", max_length=200)
    region: str = Field(default="", max_length=200)
    country: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def require_address(self) -> ContactPostalAddress:
        if not any((self.street, self.postal_code, self.city, self.region)):
            raise ValueError("A postal address requires a street, postal code, city or region.")
        return self


class ContactCoordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_numbers: list[ContactPhoneNumber] = Field(default_factory=list[ContactPhoneNumber], max_length=50)
    postal_addresses: list[ContactPostalAddress] = Field(default_factory=list[ContactPostalAddress], max_length=50)

    def merged_with(self, other: ContactCoordinates) -> ContactCoordinates:
        """Retain distinct entries from both contacts, including their human labels."""
        return ContactCoordinates(
            phone_numbers=list({phone.model_dump_json(): phone for phone in (*self.phone_numbers, *other.phone_numbers)}.values()),
            postal_addresses=list({address.model_dump_json(): address for address in (*self.postal_addresses, *other.postal_addresses)}.values()),
        )


__all__ = ["ContactCoordinates", "ContactPhoneNumber", "ContactPostalAddress"]
