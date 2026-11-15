from sqlalchemy import BigInteger, Column, String, UniqueConstraint

from models.base import Base


class TransactionDirection(Base):
    """Tabela de lookup para a direção do lançamento (débito/crédito)."""

    __tablename__ = "transaction_direction"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(10), nullable=False)
    __table_args__ = (UniqueConstraint("enumerator"),)

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
