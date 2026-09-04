import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.broadcast_log import BroadcastLog
    from src.models.business import Business
    from src.models.customer import Customer
    from src.models.service import Service


class SlotStatus(str, enum.Enum):
    """Enumeration of slot availability statuses."""
    OPEN = "OPEN"
    SENDING = "SENDING"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Slot(Base):
    """Available or cancelled appointment slot to be filled."""

    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    custom_service_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    custom_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[SlotStatus] = mapped_column(
        SAEnum(SlotStatus, name="slot_status", native_enum=True),
        default=SlotStatus.OPEN,
        nullable=False,
        index=True,
    )
    claimed_by_customer_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Optimistic locking version
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    business: Mapped["Business"] = relationship("Business", back_populates="slots")
    service: Mapped["Service | None"] = relationship("Service", back_populates="slots")
    claimed_by_customer: Mapped["Customer | None"] = relationship(
        "Customer",
        back_populates="claimed_slots",
    )
    broadcast_logs: Mapped[List["BroadcastLog"]] = relationship(
        "BroadcastLog",
        back_populates="slot",
        cascade="all, delete-orphan",
    )

    @property
    def effective_service_name(self) -> str:
        """Return custom service name if specified, otherwise the catalog service name."""
        if self.custom_service_name:
            return self.custom_service_name
        if self.service:
            return self.service.name
        return "שירות כללי"

    @property
    def effective_price(self) -> Decimal:
        """Return custom price if specified, otherwise the catalog service price."""
        if self.custom_price is not None:
            return self.custom_price
        if self.service and self.service.price is not None:
            return self.service.price
        return Decimal("0.00")

    def __repr__(self) -> str:
        return (
            f"<Slot id={self.id} business_id={self.business_id} "
            f"status={self.status.value} start={self.start_time} version={self.version}>"
        )
