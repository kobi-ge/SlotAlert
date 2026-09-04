from datetime import datetime
from typing import TYPE_CHECKING, List
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.broadcast_log import BroadcastLog
    from src.models.business import Business
    from src.models.preference import CustomerPreference
    from src.models.slot import Slot


class Customer(Base):
    """Customer belonging to a specific business."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("business_id", "phone_number", name="uq_customers_business_phone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", back_populates="customers")
    preferences: Mapped[List["CustomerPreference"]] = relationship(
        "CustomerPreference",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
    claimed_slots: Mapped[List["Slot"]] = relationship(
        "Slot",
        back_populates="claimed_by_customer",
    )
    broadcast_logs: Mapped[List["BroadcastLog"]] = relationship(
        "BroadcastLog",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} name='{self.full_name}' phone='{self.phone_number}'>"
