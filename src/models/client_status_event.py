from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from models.actor_type import ActorType
from models.base import Base
from models.client import Client
from models.client_status import ClientStatus


class ClientStatusEvent(Base):
    __tablename__ = "client_status_event"

    id = Column(BigInteger, primary_key=True)

    client_id = Column(
        BigInteger,
        ForeignKey(Client.id),
        nullable=False,
    )

    from_status_id = Column(
        BigInteger,
        ForeignKey(ClientStatus.id),
    )

    to_status_id = Column(
        BigInteger,
        ForeignKey(ClientStatus.id),
        nullable=False,
    )

    actor_type_id = Column(
        BigInteger,
        ForeignKey(ActorType.id),
        nullable=False,
    )
    reason = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False)

    actor_type_ref = relationship(
        "ActorType",
        foreign_keys=[actor_type_id],
        lazy="selectin",
    )

    SYSTEM = "SYSTEM"
    INTERNAL = "INTERNAL"

    @property
    def actor_type(self) -> str:
        """Representação textual externa do ator (SYSTEM/INTERNAL)."""
        return self.actor_type_ref.enumerator
