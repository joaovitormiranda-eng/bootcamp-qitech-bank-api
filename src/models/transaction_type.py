from sqlalchemy import BigInteger, Column, String, UniqueConstraint

from models.base import Base


class TransactionType(Base):
    """Tabela de lookup para o tipo de operação financeira."""

    __tablename__ = "transaction_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False)
    __table_args__ = (UniqueConstraint("enumerator"),)

    DEPOSIT = "DEPOSIT"
    TRANSFER = "TRANSFER"
