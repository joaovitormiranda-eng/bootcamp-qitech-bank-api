"""Preparação e inspeção dos cenários de integração da R03."""

import json
from contextlib import contextmanager
from os import environ
from typing import Iterator
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.mockserver import MockServer
from tests.utils.requisition import BaseConnectorResponse, ClientRequisition


ANALYSIS_PROVIDER_TIMEOUT_SECONDS = int(
    environ.get("ANALYSIS_PROVIDER_TIMEOUT", "5")
)
CONCURRENT_PROVIDER_DELAY_MILLISECONDS = 1_000


def provider_request(
    client_key: str,
    client_type: str,
    document: str,
) -> dict:
    """Descreve a chamada exata esperada pelo Analysis Provider."""
    return {
        "method": "POST",
        "path": "/v1/client-analysis",
        "body": {
            "type": "JSON",
            "json": {
                "client_key": client_key,
                "client_type": client_type,
                "document": document,
            },
            "matchType": "STRICT",
        },
    }


def expect_provider_response(
    expected_request: dict,
    response_body: dict | str,
    status_code: int = 200,
    delay_milliseconds: int | None = None,
) -> None:
    """Configura uma resposta determinística do MockServer."""
    serialized_body = (
        json.dumps(response_body)
        if isinstance(response_body, dict)
        else response_body
    )
    http_response = {
        "statusCode": status_code,
        "headers": {"Content-Type": ["application/json"]},
        "body": serialized_body,
    }
    if delay_milliseconds is not None:
        http_response["delay"] = {
            "timeUnit": "MILLISECONDS",
            "value": delay_milliseconds,
        }

    MockServer.expect(
        http_request=expected_request,
        http_response=http_response,
    )


def expect_client_analysis(
    expected_request: dict,
    decision: str,
    reason: str | None,
) -> None:
    """Configura a resposta de negócio mais comum do provider."""
    expect_provider_response(
        expected_request,
        {"decision": decision, "reason": reason},
    )


def analyze_client(client_key: str) -> BaseConnectorResponse:
    """Chama a rota pública da R03 com autenticação válida."""
    return ClientRequisition.send(
        "POST",
        f"/client/{client_key}/analysis",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )


def verify_provider_was_not_called() -> None:
    """Confirma que nenhuma análise externa foi solicitada."""
    MockServer.verify_exactly(
        {
            "method": "POST",
            "path": "/v1/client-analysis",
        },
        count=0,
    )


def assert_client_remains_pending(
    app_db_engine: Engine,
    client_key: str,
) -> None:
    """Confirma que nenhuma nova transição foi persistida."""
    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        persisted = connection.execute(
            text("""
                SELECT status.enumerator AS status,
                       COUNT(event.id) AS event_count
                FROM client AS client
                JOIN client_status AS status ON status.id = client.status_id
                LEFT JOIN client_status_event AS event
                  ON event.client_id = client.id
                WHERE client.client_key = CAST(:client_key AS uuid)
                GROUP BY status.enumerator
            """),
            {"client_key": client_key},
        ).mappings().one()

    assert dict(persisted) == {
        "status": "PENDING",
        "event_count": 1,
    }


def create_pending_individual() -> tuple[str, str]:
    """Cria pela R01 uma pessoa física pronta para análise."""
    cpf = RandomGenerator.generate_cpf()
    response = ClientRequisition.send(
        "POST",
        "/client",
        payload={
            "client_type": "INDIVIDUAL",
            "email": f"r03.client.{uuid4()}@example.com",
            "cpf": cpf,
            "full_name": "Cliente R03",
            "birth_date": "2000-01-01",
            "timezone": "America/Sao_Paulo",
        },
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201

    normalized_cpf = cpf.replace(".", "").replace("-", "")
    return response.response_json["client_key"], normalized_cpf


def create_pending_company() -> tuple[str, str]:
    """Cria pela R01 uma pessoa jurídica pronta para análise."""
    cnpj = RandomGenerator.generate_cnpj()
    response = ClientRequisition.send(
        "POST",
        "/client",
        payload={
            "client_type": "COMPANY",
            "email": f"r03.company.{uuid4()}@example.com",
            "cnpj": cnpj,
            "legal_name": "Cliente R03 Ltda",
            "trade_name": "Cliente R03",
            "timezone": "America/Sao_Paulo",
        },
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201

    normalized_cnpj = (
        cnpj.replace(".", "").replace("/", "").replace("-", "")
    )
    return response.response_json["client_key"], normalized_cnpj


def prepare_client_status(
    app_db_engine: Engine,
    client_key: str,
    status: str,
) -> None:
    """Prepara estado e histórico quando não existe rota pública para isso."""
    status_path = ["ACTIVE", "INACTIVE"] if status == "INACTIVE" else [status]

    with app_db_engine.begin() as connection:
        client = connection.execute(
            text("""
                SELECT client.id, client.status_id
                FROM client
                WHERE client_key = CAST(:client_key AS uuid)
            """),
            {"client_key": client_key},
        ).mappings().one()

        current_status_id = client["status_id"]
        for next_status in status_path:
            next_status_id = connection.execute(
                text("""
                    SELECT id
                    FROM client_status
                    WHERE enumerator = :status
                """),
                {"status": next_status},
            ).scalar_one()
            connection.execute(
                text("""
                    INSERT INTO client_status_event (
                        client_id,
                        from_status_id,
                        to_status_id,
                        actor_type_id,
                        reason,
                        created_at
                    ) VALUES (
                        :client_id,
                        :from_status_id,
                        :to_status_id,
                        (SELECT id FROM actor_type
                         WHERE enumerator = 'INTERNAL'),
                        'Preparação do cenário de teste',
                        NOW()
                    )
                """),
                {
                    "client_id": client["id"],
                    "from_status_id": current_status_id,
                    "to_status_id": next_status_id,
                },
            )
            current_status_id = next_status_id

        connection.execute(
            text("""
                UPDATE client
                SET status_id = :status_id,
                    updated_at = NOW()
                WHERE id = :client_id
            """),
            {
                "client_id": client["id"],
                "status_id": current_status_id,
            },
        )


def get_client_status(app_db_engine: Engine, client_key: str) -> str:
    """Lê somente o status atual de um cliente."""
    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return connection.execute(
            text("""
                SELECT status.enumerator
                FROM client AS client
                JOIN client_status AS status ON status.id = client.status_id
                WHERE client.client_key = CAST(:client_key AS uuid)
            """),
            {"client_key": client_key},
        ).scalar_one()


def get_client_lifecycle_summary(
    app_db_engine: Engine,
    client_key: str,
) -> dict:
    """Resume o status atual e a quantidade total de eventos."""
    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        lifecycle = connection.execute(
            text("""
                SELECT status.enumerator AS status,
                       COUNT(event.id) AS event_count
                FROM client AS client
                JOIN client_status AS status ON status.id = client.status_id
                LEFT JOIN client_status_event AS event
                  ON event.client_id = client.id
                WHERE client.client_key = CAST(:client_key AS uuid)
                GROUP BY status.enumerator
            """),
            {"client_key": client_key},
        ).mappings().one()

    return dict(lifecycle)


@contextmanager
def reject_next_status_event_for_client(
    app_db_engine: Engine,
    client_key: str,
) -> Iterator[None]:
    """Força erro no INSERT do evento e sempre remove o trigger de teste."""
    suffix = uuid4().hex
    function_name = f"r03_fail_event_function_{suffix}"
    trigger_name = f"r03_fail_event_trigger_{suffix}"

    with app_db_engine.begin() as connection:
        client_id = connection.execute(
            text("""
                SELECT id
                FROM client
                WHERE client_key = CAST(:client_key AS uuid)
            """),
            {"client_key": client_key},
        ).scalar_one()

        connection.exec_driver_sql(f"""
            CREATE FUNCTION {function_name}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.client_id = {client_id}
                   AND EXISTS (
                       SELECT 1
                       FROM client
                       JOIN client_status AS status
                         ON status.id = client.status_id
                       WHERE client.id = NEW.client_id
                         AND status.enumerator = 'ACTIVE'
                   ) THEN
                    RAISE EXCEPTION 'Falha controlada no evento da R03';
                END IF;
                RETURN NEW;
            END;
            $$
        """)
        connection.exec_driver_sql(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON client_status_event
            FOR EACH ROW
            EXECUTE FUNCTION {function_name}()
        """)

    try:
        yield
    finally:
        with app_db_engine.begin() as connection:
            connection.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS {trigger_name} "
                "ON client_status_event"
            )
            connection.exec_driver_sql(
                f"DROP FUNCTION IF EXISTS {function_name}()"
            )
