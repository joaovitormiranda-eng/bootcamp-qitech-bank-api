from sqlalchemy import BigInteger, CHAR, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.transaction_type import TransactionType


class FinancialTransaction(Base):
    __tablename__ = "financial_transaction"

    id = Column(BigInteger, primary_key=True)
    transaction_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_control_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_hash = Column(CHAR(64), nullable=False)
    transaction_type_id = Column(
        BigInteger,
        ForeignKey(TransactionType.id),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False)

    transaction_type_ref = relationship(
        "TransactionType",
        foreign_keys=[transaction_type_id],
        lazy="selectin",
    )

    entries = relationship(
        "TransactionEntry",
        back_populates="transaction",
        order_by="TransactionEntry.id",
    )

    DEPOSIT = "DEPOSIT"
    TRANSFER = "TRANSFER"

    @property
    def transaction_type(self) -> str:
        """Representação textual externa do tipo de operação (DEPOSIT/TRANSFER)."""
        return self.transaction_type_ref.enumerator
