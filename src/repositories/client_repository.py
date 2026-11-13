from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import lazyload

from database import Context
from models import (
    Account,
    ActorType,
    Client,
    ClientStatus,
    ClientStatusEvent,
    ClientType,
    CompanyClient,
    IndividualClient,
)


class ClientRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def _client_type_id(self, enumerator: str) -> int:
        """Resolve o texto do tipo de cliente para o id da lookup."""
        return (
            self.session.query(ClientType.id)
            .filter(ClientType.enumerator == enumerator)
            .scalar()
        )

    def _actor_type_id(self, enumerator: str) -> int:
        """Resolve o texto do ator para o id da lookup."""
        return (
            self.session.query(ActorType.id)
            .filter(ActorType.enumerator == enumerator)
            .scalar()
        )

    def get_status(self, enumerator: str) -> ClientStatus:
        return (
            self.session.query(ClientStatus)
            .filter(ClientStatus.enumerator == enumerator)
            .one()
        )

    def get_by_email(self, email: str) -> Client | None:
        return (
            self.session.query(Client)
            .filter(Client.email == email)
            .first()
        )

    def get_individual_by_cpf(self, cpf: str) -> IndividualClient | None:
        return (
            self.session.query(IndividualClient)
            .filter(IndividualClient.cpf == cpf)
            .first()
        )

    def get_by_key(self, client_key: UUID) -> Client | None:
        return (
            self.session.query(Client)
            .filter(Client.client_key == client_key)
            .one_or_none()
        )

    def get_by_key_for_update(self, client_key: UUID) -> Client | None:
        return (
            self.session.query(Client)
            .options(lazyload(Client.status))
            .filter(Client.client_key == client_key)
            .populate_existing()
            .with_for_update(of=Client)
            .one_or_none()
        )

    def get_status_by_id(self, status_id: int) -> ClientStatus | None:
        return (
            self.session.query(ClientStatus)
            .filter(ClientStatus.id == status_id)
            .one_or_none()
        )

    def has_account(self, client_id: int) -> bool:
        return (
            self.session.query(Account.id)
            .filter(Account.client_id == client_id)
            .first()
            is not None
        )

    def apply_status_change(
        self,
        client: Client,
        from_status: ClientStatus,
        to_status: ClientStatus,
        reason: str,
    ) -> ClientStatusEvent:
        changed_at = datetime.now(timezone.utc)
        client.status_id = to_status.id
        client.updated_at = changed_at

        event = ClientStatusEvent(
            client_id=client.id,
            from_status_id=from_status.id,
            to_status_id=to_status.id,
            actor_type_id=self._actor_type_id(ClientStatusEvent.INTERNAL),
            reason=reason,
            created_at=changed_at,
        )
        self.session.add(event)
        return event

    def get_individual_by_client_id(
        self, client_id: int
    ) -> IndividualClient | None:
        return (
            self.session.query(IndividualClient)
            .filter(IndividualClient.client_id == client_id)
            .one_or_none()
        )

    def get_company_by_client_id(self, client_id: int) -> CompanyClient | None:
        return (
            self.session.query(CompanyClient)
            .filter(CompanyClient.client_id == client_id)
            .one_or_none()
        )

    def create_client(
        self,
        client_type: str,
        email: str,
        timezone_name: str,
        status: ClientStatus,
    ) -> Client:
        now = datetime.now(timezone.utc)

        client = Client()
        client.client_key = uuid4()
        client.client_type_id = self._client_type_id(client_type)
        client.email = email
        client.timezone = timezone_name
        client.status_id = status.id
        client.created_at = now
        client.updated_at = now

        self.session.add(client)

        # Precisamos do client.id para a especialização e o evento,
        # mas ainda NÃO queremos commit.
        self.session.flush()

        return client

    def create_individual_client(
        self,
        client: Client,
        cpf: str,
        full_name: str,
        birth_date: date,
    ) -> IndividualClient:
        individual_client = IndividualClient()
        individual_client.client_id = client.id
        individual_client.cpf = cpf
        individual_client.full_name = full_name
        individual_client.birth_date = birth_date

        self.session.add(individual_client)

        return individual_client

    def create_company_client(
        self,
        client: Client,
        cnpj: str,
        legal_name: str,
        trade_name: str | None,
    ) -> CompanyClient:
        company_client = CompanyClient()
        company_client.client_id = client.id
        company_client.cnpj = cnpj
        company_client.legal_name = legal_name
        company_client.trade_name = trade_name

        self.session.add(company_client)

        return company_client

    def create_status_event(
        self,
        client: Client,
        to_status: ClientStatus,
        actor_type: str,
    ) -> ClientStatusEvent:
        status_event = ClientStatusEvent()
        status_event.client_id = client.id
        status_event.from_status_id = None
        status_event.to_status_id = to_status.id
        status_event.actor_type_id = self._actor_type_id(actor_type)
        status_event.reason = None
        status_event.created_at = datetime.now(timezone.utc)

        self.session.add(status_event)

        return status_event
