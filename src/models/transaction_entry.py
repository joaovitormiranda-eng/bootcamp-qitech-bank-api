from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.entry_type import EntryType
from models.transaction_direction import TransactionDirection


class TransactionEntry(Base):
    __tablename__ = "transaction_entry"

    id = Column(BigInteger, primary_key=True)
    entry_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    transaction_id = Column(
        BigInteger,
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id = Column(
        BigInteger,
        ForeignKey("account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    direction_id = Column(
        BigInteger,
        ForeignKey(TransactionDirection.id, ondelete="RESTRICT"),
        nullable=False,
    )
    entry_type_id = Column(
        BigInteger,
        ForeignKey(EntryType.id, ondelete="RESTRICT"),
        nullable=False,
    )
    amount_cents = Column(BigInteger, nullable=False)
    balance_after_cents = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    transaction = relationship(
        "FinancialTransaction",
        back_populates="entries",
    )
    account = relationship("Account", foreign_keys=[account_id])
    direction_ref = relationship(
        "TransactionDirection",
        foreign_keys=[direction_id],
        lazy="selectin",
    )
    entry_type_ref = relationship(
        "EntryType",
        foreign_keys=[entry_type_id],
        lazy="selectin",
    )

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    PRINCIPAL = "PRINCIPAL"
    FEE = "FEE"

    @property
    def direction(self) -> str:
        """Representação textual externa da direção (DEBIT/CREDIT)."""
        return self.direction_ref.enumerator

    @property
    def entry_type(self) -> str:
        """Representação textual externa da natureza (PRINCIPAL/FEE)."""
        return self.entry_type_ref.enumerator
