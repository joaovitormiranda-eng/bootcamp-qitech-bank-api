"""Helpers coesos e locais da rota R09."""

from .base import *


def _create_client(client_type: str = "INDIVIDUAL") -> tuple[str, str]:
    email = f"r09.{client_type.lower()}.{uuid4()}@example.com"
    payload = {
        "client_type": client_type,
        "email": email,
        "timezone": "America/Sao_Paulo",
    }
    if client_type == "INDIVIDUAL":
        payload.update(
            cpf=RandomGenerator.generate_cpf(),
            full_name="Cliente R09",
            birth_date="1990-05-17",
        )
    else:
        payload.update(
            cnpj=RandomGenerator.generate_cnpj(),
            legal_name="Empresa R09 Ltda.",
            trade_name="Empresa R09",
        )

    response = ClientRequisition.send(
        "POST",
        "/client",
        payload=payload,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201
    return response.response_json["client_key"], email


def _transition_client_fixture(
    engine: Engine,
    client_key: str,
    expected_status: str,
    target_status: str,
) -> None:
    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT client.id, client.status_id
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                  AND status.enumerator = :expected_status
                """
            ),
            {"client_key": client_key, "expected_status": expected_status},
        ).mappings().one()
        changed_at = connection.execute(
            text("SELECT clock_timestamp()")
        ).scalar_one()
        updated = connection.execute(
            text(
                """
                UPDATE client
                SET status_id = (
                        SELECT id FROM client_status WHERE enumerator = :target_status
                    ),
                    updated_at = :changed_at
                WHERE id = :client_id AND status_id = :old_status_id
                """
            ),
            {
                "client_id": client["id"],
                "old_status_id": client["status_id"],
                "target_status": target_status,
                "changed_at": changed_at,
            },
        )
        assert updated.rowcount == 1
        inserted = connection.execute(
            text(
                """
                INSERT INTO client_status_event
                    (client_id, from_status_id, to_status_id, actor_type_id, reason, created_at)
                SELECT :client_id, :from_status_id, status.id,
                       (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                       :reason, :changed_at
                FROM client_status AS status
                WHERE status.enumerator = :target_status
                """
            ),
            {
                "client_id": client["id"],
                "from_status_id": client["status_id"],
                "target_status": target_status,
                "reason": f"Fixture {expected_status} para {target_status}",
                "changed_at": changed_at,
            },
        )
        assert inserted.rowcount == 1


def _create_client_in_status(
    engine: Engine,
    status: str,
    client_type: str = "INDIVIDUAL",
) -> tuple[str, str]:
    client_key, email = _create_client(client_type)
    if status in {"ACTIVE", "REJECTED"}:
        _transition_client_fixture(engine, client_key, "PENDING", status)
    elif status == "INACTIVE":
        _transition_client_fixture(engine, client_key, "PENDING", "ACTIVE")
        _transition_client_fixture(engine, client_key, "ACTIVE", "INACTIVE")
    elif status != "PENDING":
        raise AssertionError(f"Unsupported fixture status: {status}")
    return client_key, email


def _open_account(client_key: str, status: str = "ACTIVE") -> str:
    response = ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201
    account_key = response.response_json["account_key"]
    if status != "ACTIVE":
        transition = ClientRequisition.send(
            "PATCH",
            f"/account/{account_key}",
            payload={"status": status, "reason": f"Fixture ACCOUNT {status}"},
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        assert transition.response_status == 200
    return account_key

__all__ = [name for name in globals() if not name.startswith("__")]
