from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import joinedload, lazyload

from database import Context
from models import (
    Account,
    AccountStatus,
    AccountStatusEvent,
    ActorType,
    Client,
    ClientStatus,
    ClientStatusEvent,
    ClientType,
)


class AccountRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def _actor_type_id(self, enumerator: str) -> int:
        """Resolve o texto do ator para o id da lookup."""
        return (
            self.session.query(ActorType.id)
            .filter(ActorType.enumerator == enumerator)
            .scalar()
        )

    def get_client_by_key_for_update(self, client_key: UUID) -> Client | None:
        return (
            self.session.query(Client)
            .options(lazyload(Client.status))
            .filter(Client.client_key == client_key)
            .populate_existing()
            .with_for_update(of=Client)
            .one_or_none()
        )

    def get_account_status(self, enumerator: str) -> AccountStatus | None:
        return (
            self.session.query(AccountStatus)
            .filter(AccountStatus.enumerator == enumerator)
            .one_or_none()
        )

    def get_by_client_id(self, client_id: int) -> Account | None:
        return (
            self.session.query(Account)
            .filter(Account.client_id == client_id)
            .one_or_none()
        )

    def get_by_key(self, account_key: UUID) -> tuple[Account, UUID] | None:
        return (
            self.session.query(Account, Client.client_key)
            .join(Client, Client.id == Account.client_id)
            .options(joinedload(Account.status))
            .filter(Account.account_key == account_key)
            .one_or_none()
        )

    def get_by_key_with_timezone(
        self,
        account_key: UUID,
    ) -> tuple[Account, str] | None:
        return (
            self.session.query(Account, Client.timezone)
            .join(Client, Client.id == Account.client_id)
            .filter(Account.account_key == account_key)
            .one_or_none()
        )

    def get_by_key_for_update(self, account_key: UUID) -> Account | None:
        return (
            self.session.query(Account)
            .options(joinedload(Account.status))
            .filter(Account.account_key == account_key)
            .populate_existing()
            .with_for_update(of=Account)
            .one_or_none()
        )

    def get_ids_by_keys(
        self,
        account_keys: tuple[UUID, UUID],
    ) -> dict[UUID, int]:
        rows = (
            self.session.query(Account.account_key, Account.id)
            .filter(Account.account_key.in_(account_keys))
            .all()
        )
        return {row.account_key: row.id for row in rows}

    def get_by_ids_for_update(
        self,
        account_ids: list[int],
    ) -> list[Account]:
        return (
            self.session.query(Account)
            .options(joinedload(Account.status))
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id)
            .populate_existing()
            .with_for_update(of=Account)
            .all()
        )

    def get_client_type(self, client_id: int) -> str | None:
        return (
            self.session.query(ClientType.enumerator)
            .join(Client, Client.client_type_id == ClientType.id)
            .filter(Client.id == client_id)
            .scalar()
        )

    def get_owner_id_by_key(self, account_key: UUID) -> int | None:
        return (
            self.session.query(Account.client_id)
            .filter(Account.account_key == account_key)
            .scalar()
        )

    def get_client_by_id_for_update(self, client_id: int) -> Client | None:
        return (
            self.session.query(Client)
            .options(lazyload(Client.status))
            .filter(Client.id == client_id)
            .populate_existing()
            .with_for_update(of=Client)
            .one_or_none()
        )

    def get_account_by_key_for_update(
        self,
        account_key: UUID,
        client_id: int,
    ) -> Account | None:
        return (
            self.session.query(Account)
            .options(lazyload(Account.status))
            .filter(
                Account.account_key == account_key,
                Account.client_id == client_id,
            )
            .populate_existing()
            .with_for_update(of=Account)
            .one_or_none()
        )

    def update_balance(
        self,
        account: Account,
        balance_cents: int,
        updated_at: datetime,
    ) -> None:
        account.balance_cents = balance_cents
        account.updated_at = updated_at

    def get_client_status(self, enumerator: str) -> ClientStatus | None:
        return (
            self.session.query(ClientStatus)
            .filter(ClientStatus.enumerator == enumerator)
            .one_or_none()
        )

    def get_account_status_by_id(self, status_id: int) -> AccountStatus | None:
        return (
            self.session.query(AccountStatus)
            .filter(AccountStatus.id == status_id)
            .one_or_none()
        )

    def get_client_status_by_id(self, status_id: int) -> ClientStatus | None:
        return (
            self.session.query(ClientStatus)
            .filter(ClientStatus.id == status_id)
            .one_or_none()
        )

    def create_account_status_event(
        self,
        account_id: int,
        from_status_id: int,
        to_status_id: int,
        reason: str,
        created_at: datetime,
    ) -> None:
        self.session.add(
            AccountStatusEvent(
                account_id=account_id,
                from_status_id=from_status_id,
                to_status_id=to_status_id,
                actor_type_id=self._actor_type_id(AccountStatusEvent.INTERNAL),
                reason=reason,
                created_at=created_at,
            )
        )

    def create_client_status_event(
        self,
        client_id: int,
        from_status_id: int,
        to_status_id: int,
        reason: str,
        created_at: datetime,
    ) -> None:
        self.session.add(
            ClientStatusEvent(
                client_id=client_id,
                from_status_id=from_status_id,
                to_status_id=to_status_id,
                actor_type_id=self._actor_type_id(ClientStatusEvent.INTERNAL),
                reason=reason,
                created_at=created_at,
            )
        )

    def create_account(self, client_id: int, status: AccountStatus) -> Account:
        now = datetime.now(timezone.utc)
        account = Account(
            account_key=uuid4(),
            client_id=client_id,
            status_id=status.id,
            balance_cents=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(account)
        self.session.flush()
        return account

    def create_initial_status_event(
        self,
        account_id: int,
        status: AccountStatus,
    ) -> AccountStatusEvent:
        event = AccountStatusEvent(
            account_id=account_id,
            from_status_id=None,
            to_status_id=status.id,
            actor_type_id=self._actor_type_id(AccountStatusEvent.SYSTEM),
            reason=None,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(event)
        return event
