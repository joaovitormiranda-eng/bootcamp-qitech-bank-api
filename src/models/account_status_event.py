from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from models.account import Account
from models.account_status import AccountStatus
from models.actor_type import ActorType
from models.base import Base


class AccountStatusEvent(Base):
    __tablename__ = "account_status_event"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(
        BigInteger,
        ForeignKey(Account.id, ondelete="RESTRICT"),
        nullable=False,
    )
    from_status_id = Column(
        BigInteger,
        ForeignKey(AccountStatus.id, ondelete="RESTRICT"),
    )
    to_status_id = Column(
        BigInteger,
        ForeignKey(AccountStatus.id, ondelete="RESTRICT"),
        nullable=False,
    )
    actor_type_id = Column(
        BigInteger,
        ForeignKey(ActorType.id, ondelete="RESTRICT"),
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
