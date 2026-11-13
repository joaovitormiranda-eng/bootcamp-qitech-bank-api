"""Helpers coesos e locais da rota R06."""

from .base import *


def _create_active_account(engine: Engine, client_type: str = "INDIVIDUAL") -> tuple[str, str]:
    email = f"r06.{client_type.lower()}.{uuid4()}@example.com"
    payload = {
        "client_type": client_type,
        "email": email,
        "timezone": "America/Sao_Paulo",
    }
    if client_type == "INDIVIDUAL":
        payload.update(
            cpf=RandomGenerator.generate_cpf(),
            full_name="Cliente R06",
            birth_date="1990-05-17",
        )
    else:
        payload.update(
            cnpj=RandomGenerator.generate_cnpj(),
            legal_name="Empresa R06 Ltda.",
            trade_name="Empresa R06",
        )

    client_response = ClientRequisition.send(
        "POST", "/client", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
    )
    assert client_response.response_status == 201
    client_key = client_response.response_json["client_key"]

    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT client.id, client.status_id
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                  AND status.enumerator = 'PENDING'
                """
            ),
            {"client_key": client_key},
        ).mappings().one()
        changed_at = datetime.now(timezone.utc)
        assert connection.execute(
            text(
                """
                UPDATE client
                SET status_id = (SELECT id FROM client_status WHERE enumerator = 'ACTIVE'),
                    updated_at = :changed_at
                WHERE id = :client_id AND status_id = :old_status_id
                """
            ),
            {"client_id": client["id"], "old_status_id": client["status_id"], "changed_at": changed_at},
        ).rowcount == 1
        assert connection.execute(
            text(
                """
                INSERT INTO client_status_event
                    (client_id, from_status_id, to_status_id, actor_type_id, reason, created_at)
                SELECT :client_id, :from_status_id, status.id,
                       (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                       NULL, :changed_at
                FROM client_status AS status WHERE status.enumerator = 'ACTIVE'
                """
            ),
            {"client_id": client["id"], "from_status_id": client["status_id"], "changed_at": changed_at},
        ).rowcount == 1

    account_response = ClientRequisition.send(
        "POST", f"/client/{client_key}/account", headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
    )
    assert account_response.response_status == 201
    return client_key, account_response.response_json["account_key"]


def _assert_error(response, status: int, code: str) -> None:
    assert response.response_status == status
    assert set(response.response_json) == {"title", "description", "translation", "code"}
    assert response.response_json["code"] == code


def _patch(account_key: str, status: str, reason: str = "Motivo operacional"):
    return ClientRequisition.send(
        "PATCH",
        f"/account/{account_key}",
        payload={"status": status, "reason": reason},
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )


def _prepare_inactive(account_key: str) -> None:
    response = _patch(account_key, "INACTIVE", "Preparação INACTIVE")
    assert response.response_status == 200


def _create_active_account_for_client_key_test() -> tuple[str, str]:
    email = f"r06.wrong.resource.{uuid4()}@example.com"
    response = ClientRequisition.send(
        "POST",
        "/client",
        payload={
            "client_type": "INDIVIDUAL",
            "email": email,
            "cpf": RandomGenerator.generate_cpf(),
            "full_name": "Cliente Chave R06",
            "birth_date": "1990-05-17",
            "timezone": "America/Sao_Paulo",
        },
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201
    return response.response_json["client_key"], email

__all__ = [name for name in globals() if not name.startswith("__")]
