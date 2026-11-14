from datetime import datetime, timezone
from uuid import UUID

from database import Context
from models import (
    ActorType,
    Client,
    ClientStatus,
    ClientStatusEvent,
    CompanyClient,
    IndividualClient,
)


class ClientAnalysisRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def _actor_type_id(self, enumerator: str) -> int:
        """Resolve o texto do ator para o id da lookup."""
        return (
            self.session.query(ActorType.id)
            .filter(ActorType.enumerator == enumerator)
            .scalar()
        )

    def get_analysis_source(self, client_key: UUID) -> tuple[Client, str] | None:
        """Busca o cliente e seu CPF/CNPJ sem definir formato de transporte."""
        client = (
            self.session.query(Client)
            .filter(Client.client_key == client_key)
            .one_or_none()
        )

        if client is None:
            return None

        if client.client_type == "INDIVIDUAL":
            profile = (
                self.session.query(IndividualClient)
                .filter(IndividualClient.client_id == client.id)
                .one()
            )
            document = profile.cpf
        else:
            profile = (
                self.session.query(CompanyClient)
                .filter(CompanyClient.client_id == client.id)
                .one()
            )
            document = profile.cnpj

        return client, document

    def get_by_client_key_for_update(self, client_key: UUID) -> Client:
        """Relê o cliente adquirindo o lock usado na etapa crítica."""
        return (
            self.session.query(Client)
            .filter(Client.client_key == client_key)
            .with_for_update()
            .one()
        )

    def get_status(self, enumerator: str) -> ClientStatus:
        return (
            self.session.query(ClientStatus)
            .filter(ClientStatus.enumerator == enumerator)
            .one()
        )

    def apply_status_change(
        self,
        client: Client,
        from_status: ClientStatus,
        to_status: ClientStatus,
        actor_type: str,
        reason: str | None,
    ) -> ClientStatusEvent:
        """Altera o status e adiciona seu evento na mesma transação."""
        now = datetime.now(timezone.utc)

        client.status_id = to_status.id
        client.updated_at = now

        # Envia o UPDATE dentro da transação, sem fazer commit. Se a criação
        # do evento falhar depois, o rollback ainda desfaz esta alteração.
        self.session.flush()

        status_event = ClientStatusEvent()
        status_event.client_id = client.id
        status_event.from_status_id = from_status.id
        status_event.to_status_id = to_status.id
        status_event.actor_type_id = self._actor_type_id(actor_type)
        status_event.reason = reason
        status_event.created_at = now

        self.session.add(status_event)

        return status_event
