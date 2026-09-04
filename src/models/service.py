from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.business import Business
    from src.models.preference import CustomerPreference
    from src.models.slot import Slot


class Service(Base):
    """Service offered by a business (e.g., Facial, Deep Tissue Massage)."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", back_populates="services")
    slots: Mapped[List["Slot"]] = relationship(
        "Slot",
        back_populates="service",
        cascade="all, delete-orphan",
    )
    preferences: Mapped[List["CustomerPreference"]] = relationship(
        "CustomerPreference",
        back_populates="service",
    )

    def __repr__(self) -> str:
        return f"<Service id={self.id} name='{self.name}' duration={self.duration_minutes}m price={self.price}>"
