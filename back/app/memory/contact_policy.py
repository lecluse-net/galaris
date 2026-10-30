"""Keep literal contact coordinates out of personal-memory copies."""

from collections.abc import Sequence

from core.params import runtime_settings
from core.util import RichTextError, country_from_localization, detect_contact_infos, visible_text


CONTACT_COORDINATE_MESSAGE = (
    "Contact coordinates belong in Contacts and cannot be copied into a personal memory. "
    "The conversation's contact-discovery pipeline handles their owner and storage. "
    "For an explicit address-book change, use contact_list/contact_get and contact_create/contact_update when authorized. "
    "For a separate preference or decision, retry with only that fact and the person's name, "
    "without the email, phone, postal address or messaging identifier."
)


def contains_contact_coordinates(*, content: str, title: str = "", keywords: Sequence[str] = ()) -> bool:
    """Use the same offline detector as dispatch, independently of queue timing.

    Scan visible HTML as well as literals so split formatting and mailto/tel links
    cannot turn a coordinate into an ordinary memory. Never rewrite mixed prose.
    """
    country = country_from_localization(runtime_settings.LOCALIZATION) or None
    values = [title, *keywords, content]
    if "<" in content:
        try:
            values.append(visible_text(content))
        except RichTextError:
            pass
    return any(detect_contact_infos(value, default_country=country) for value in values if value)
