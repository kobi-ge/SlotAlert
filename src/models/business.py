from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.customer import Customer
    from src.models.service import Service
    from src.models.slot import Slot


class Business(Base):
    """Business entity representing a clinic, salon, or service provider."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    business_type: Mapped[str] = mapped_column(String(50), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    services: Mapped[List["Service"]] = relationship(
        "Service",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    customers: Mapped[List["Customer"]] = relationship(
        "Customer",
        back_populates="business",
        cascade="all, delete-orphan",
    )
    slots: Mapped[List["Slot"]] = relationship(
        "Slot",
        back_populates="business",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Business id={self.id} name='{self.name}' slug='{self.slug}'>"
