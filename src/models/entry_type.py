from sqlalchemy import BigInteger, Column, String, UniqueConstraint

from models.base import Base


class EntryType(Base):
    """Tabela de lookup para a natureza do lançamento (principal/tarifa)."""

    __tablename__ = "entry_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False)
    __table_args__ = (UniqueConstraint("enumerator"),)

    PRINCIPAL = "PRINCIPAL"
    FEE = "FEE"
