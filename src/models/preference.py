from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.models.customer import Customer
    from src.models.service import Service


class CustomerPreference(Base):
    """Customer availability preference for days of week and time of day."""

    __tablename__ = "customer_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0 = Sunday, 1 = Monday, ..., 6 = Saturday
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    # 'MORNING', 'AFTERNOON', 'EVENING'
    time_slot: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="preferences")
    service: Mapped["Service | None"] = relationship("Service", back_populates="preferences")

    def __repr__(self) -> str:
        return (
            f"<CustomerPreference id={self.id} customer_id={self.customer_id} "
            f"day={self.day_of_week} time='{self.time_slot}' service_id={self.service_id}>"
        )
