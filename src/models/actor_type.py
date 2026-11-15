from sqlalchemy import BigInteger, Column, String, UniqueConstraint

from models.base import Base


class ActorType(Base):
    """Tabela de lookup compartilhada para o ator das transições de status."""

    __tablename__ = "actor_type"

    id = Column(BigInteger, primary_key=True)
    enumerator = Column(String(20), nullable=False)
    __table_args__ = (UniqueConstraint("enumerator"),)

    SYSTEM = "SYSTEM"
    INTERNAL = "INTERNAL"
