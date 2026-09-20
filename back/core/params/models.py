from typing import Optional
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base


class Param(Base):
    """Application parameter model.

    HistoryMixin is intentionally omitted because parameter change history is not required.

    Labels and descriptions live in frontend vue-i18n catalogs indexed by name.
    """
    __tablename__ = "params"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Prompt parameters remember the packaged default against which their
    # customization was made.  A NULL value still means "follow the default".
    default_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
