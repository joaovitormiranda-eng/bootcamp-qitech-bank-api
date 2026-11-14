from sqlalchemy import BigInteger, Column, String, UniqueConstraint

from models.base import Base


class ClientType(Base):
    """Tabela de lookup para o tipo de cliente (PF/PJ)."""

    __tablename__ = "client_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False)
    __table_args__ = (UniqueConstraint("enumerator"),)

    INDIVIDUAL = "INDIVIDUAL"
    COMPANY = "COMPANY"
