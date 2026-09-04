from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.customer import Customer
    from src.models.slot import Slot


class BroadcastLog(Base):
    """Log entry recording an alert message sent to a customer about a slot."""

    __tablename__ = "broadcast_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("slots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_sid: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    delivery_status: Mapped[str] = mapped_column(String(50), default="SENT", nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    slot: Mapped["Slot"] = relationship("Slot", back_populates="broadcast_logs")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="broadcast_logs")

    def __repr__(self) -> str:
        return (
            f"<BroadcastLog id={self.id} slot_id={self.slot_id} "
            f"customer_id={self.customer_id} status='{self.delivery_status}'>"
        )
