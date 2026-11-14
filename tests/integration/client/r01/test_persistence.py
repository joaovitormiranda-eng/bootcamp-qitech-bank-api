"""Efeitos físicos da R01, observados após POST HTTP e COMMIT da API."""

from os import environ
from typing import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Connection, Engine

from tests.utils import DbUtils, INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import BaseConnectorResponse, ClientRequisition


@pytest.fixture(scope="module")
def app_db_engine() -> Iterator[Engine]:
    """Consulta o banco da API, nunca o banco descartável de schema."""
    app_url = make_url(DbUtils.database_url())
    test_database_url = environ.get("TEST_DATABASE_URL")

    if app_url.database != "bootcamp" or app_url.database.endswith("_test"):
        pytest.fail("A verificação da R01 deve consultar o banco bootcamp da API.")
    if test_database_url and app_url == make_url(test_database_url):
        pytest.fail("O banco da API não pode ser TEST_DATABASE_URL.")

    engine = create_engine(app_url)
    try:
        with engine.connect() as connection:
            actual_database = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()
            assert actual_database == app_url.database
        yield engine
    finally:
        engine.dispose()


def _post_client(payload: dict[str, str]) -> BaseConnectorResponse:
    return ClientRequisition.send(
        "POST",
        "/client",
        payload=payload,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )


def _client_by_key(connection: Connection, client_key: str):
    return connection.execute(
        text("""
            SELECT c.id, c.client_key::text AS client_key,
                   client_type.enumerator AS client_type,
                   c.email, c.timezone, s.enumerator AS status
            FROM client AS c
            JOIN client_status AS s ON s.id = c.status_id
            JOIN client_type ON client_type.id = c.client_type_id
            WHERE c.client_key = CAST(:client_key AS uuid)
        """),
        {"client_key": client_key},
    ).mappings().one()


def _assert_initial_event(connection: Connection, client_id: int) -> None:
    events = connection.execute(
        text("""
            SELECT e.from_status_id, s.enumerator AS to_status,
                   actor_type.enumerator AS actor_type, e.reason
            FROM client_status_event AS e
            JOIN client_status AS s ON s.id = e.to_status_id
            JOIN actor_type ON actor_type.id = e.actor_type_id
            WHERE e.client_id = :client_id
        """),
        {"client_id": client_id},
    ).mappings().all()

    assert len(events) == 1
    assert events[0]["from_status_id"] is None
    assert events[0]["to_status"] == "PENDING"
    assert events[0]["actor_type"] == "SYSTEM"
    assert events[0]["reason"] is None


def test_individual_creation_persists_one_profile_and_initial_event(
    app_db_engine: Engine,
) -> None:
    cpf = RandomGenerator.generate_cpf()
    email = f"R01.PF.Persistence.{uuid4()}@Example.COM"
    payload = {
        "client_type": "INDIVIDUAL",
        "email": f"  {email}  ",
        "cpf": cpf,
        "full_name": "  Joao Teste  ",
        "birth_date": "2000-01-01",
        "timezone": "America/Manaus",
    }

    response = _post_client(payload)

    assert response.response_status == 201
    client_key = response.response_json["client_key"]
    assert isinstance(UUID(client_key), UUID)

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        client = _client_by_key(connection, client_key)
        individual_profiles = connection.execute(
            text("""
                SELECT cpf, full_name, birth_date
                FROM individual_client WHERE client_id = :client_id
            """),
            {"client_id": client["id"]},
        ).mappings().all()
        company_count = connection.execute(
            text("SELECT COUNT(*) FROM company_client WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one()
        _assert_initial_event(connection, client["id"])

    assert client["client_key"] == client_key
    assert client["client_type"] == "INDIVIDUAL"
    assert client["email"] == email.lower()
    assert client["timezone"] == payload["timezone"]
    assert client["status"] == "PENDING"
    assert len(individual_profiles) == 1
    assert individual_profiles[0]["cpf"] == cpf.replace(".", "").replace("-", "")
    assert individual_profiles[0]["full_name"] == "Joao Teste"
    assert individual_profiles[0]["birth_date"].isoformat() == payload["birth_date"]
    assert company_count == 0


@pytest.mark.parametrize(
    ("trade_name", "expected_trade_name"),
    [
        (None, None),
        ("", None),
        ("    ", None),
        ("  Empresa  ", "Empresa"),
    ],
    ids=["omitted", "empty", "whitespace", "trimmed"],
)
def test_company_creation_persists_one_profile_and_initial_event(
    app_db_engine: Engine, trade_name: str | None, expected_trade_name: str | None,
) -> None:
    cnpj = RandomGenerator.generate_cnpj()
    email = f"R01.Company.Persistence.{uuid4()}@Example.COM"
    payload = {
        "client_type": "COMPANY",
        "email": f"  {email}  ",
        "cnpj": cnpj,
        "legal_name": "  Empresa Teste Ltda  ",
        "timezone": "America/Recife",
    }
    if trade_name is not None:
        payload["trade_name"] = trade_name

    response = _post_client(payload)

    assert response.response_status == 201
    client_key = response.response_json["client_key"]
    assert isinstance(UUID(client_key), UUID)

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        client = _client_by_key(connection, client_key)
        company_profiles = connection.execute(
            text("""
                SELECT cnpj, legal_name, trade_name
                FROM company_client WHERE client_id = :client_id
            """),
            {"client_id": client["id"]},
        ).mappings().all()
        individual_count = connection.execute(
            text("SELECT COUNT(*) FROM individual_client WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one()
        _assert_initial_event(connection, client["id"])

    assert client["client_key"] == client_key
    assert client["client_type"] == "COMPANY"
    assert client["email"] == email.lower()
    assert client["timezone"] == payload["timezone"]
    assert client["status"] == "PENDING"
    assert individual_count == 0
    assert len(company_profiles) == 1
    assert company_profiles[0]["cnpj"] == (
        cnpj.replace(".", "").replace("/", "").replace("-", "")
    )
    assert company_profiles[0]["legal_name"] == "Empresa Teste Ltda"
    assert company_profiles[0]["trade_name"] == expected_trade_name


def test_duplicate_cpf_rolls_back_new_client(
    app_db_engine: Engine,
) -> None:
    cpf = RandomGenerator.generate_cpf()
    first_payload = {
        "client_type": "INDIVIDUAL",
        "email": f"r01.rollback.pf.first.{uuid4()}@example.com",
        "cpf": cpf,
        "full_name": "Joao Teste",
        "birth_date": "2000-01-01",
        "timezone": "America/Sao_Paulo",
    }
    rejected_email = f"r01.rollback.pf.rejected.{uuid4()}@example.com"
    second_payload = {**first_payload, "email": rejected_email}

    first_response = _post_client(first_payload)
    assert first_response.response_status == 201

    second_response = _post_client(second_payload)
    assert second_response.response_status == 409
    assert second_response.response_json["code"] == "CLI0004"

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        first_client = _client_by_key(
            connection, first_response.response_json["client_key"]
        )
        rejected_client_count = connection.execute(
            text("SELECT COUNT(*) FROM client WHERE email = :email"),
            {"email": rejected_email},
        ).scalar_one()
        document_count = connection.execute(
            text("SELECT COUNT(*) FROM individual_client WHERE cpf = :cpf"),
            {"cpf": cpf.replace(".", "").replace("-", "")},
        ).scalar_one()
        _assert_initial_event(connection, first_client["id"])

    assert rejected_client_count == 0
    assert document_count == 1


def test_duplicate_cnpj_rolls_back_new_client(
    app_db_engine: Engine,
) -> None:
    cnpj = RandomGenerator.generate_cnpj()
    first_payload = {
        "client_type": "COMPANY",
        "email": f"r01.rollback.pj.first.{uuid4()}@example.com",
        "cnpj": cnpj,
        "legal_name": "Empresa Teste Ltda",
        "timezone": "America/Sao_Paulo",
    }
    rejected_email = f"r01.rollback.pj.rejected.{uuid4()}@example.com"
    second_payload = {**first_payload, "email": rejected_email}

    first_response = _post_client(first_payload)
    assert first_response.response_status == 201

    second_response = _post_client(second_payload)
    assert second_response.response_status == 409
    assert second_response.response_json["code"] == "CLI0005"

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        first_client = _client_by_key(
            connection, first_response.response_json["client_key"]
        )
        rejected_client_count = connection.execute(
            text("SELECT COUNT(*) FROM client WHERE email = :email"),
            {"email": rejected_email},
        ).scalar_one()
        document_count = connection.execute(
            text("SELECT COUNT(*) FROM company_client WHERE cnpj = :cnpj"),
            {"cnpj": cnpj.replace(".", "").replace("/", "").replace("-", "")},
        ).scalar_one()
        _assert_initial_event(connection, first_client["id"])

    assert rejected_client_count == 0
    assert document_count == 1
