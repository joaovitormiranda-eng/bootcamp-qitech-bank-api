from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base
from models.client_status import ClientStatus
from models.client_type import ClientType


class Client(Base):
    __tablename__ = "client"
    id = Column(BigInteger, primary_key=True)
    client_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    client_type_id = Column(
        BigInteger,
        ForeignKey(ClientType.id),
        nullable=False,
    )
    email = Column(String(254), nullable=False, unique=True)
    timezone = Column(String(64), nullable=False)

    status_id = Column(
        BigInteger,
        ForeignKey(ClientStatus.id),
        nullable=False,
    )

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    status = relationship(
        "ClientStatus",
        foreign_keys=[status_id],
        lazy="selectin",
    )
    client_type_ref = relationship(
        "ClientType",
        foreign_keys=[client_type_id],
        lazy="selectin",
    )

    @property
    def client_type(self) -> str:
        """Mantém a representação textual externa do tipo de cliente.

        A coluna física é `client_type_id` (FK para a lookup `client_type`),
        mas a API e o domínio continuam lendo/comparando o texto
        (`INDIVIDUAL`/`COMPANY`).
        """
        return self.client_type_ref.enumerator
