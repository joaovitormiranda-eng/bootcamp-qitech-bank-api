from uuid import uuid4

import pytest

from tests.integration.transaction.support import open_funded_account_via_api
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def _open_account_with_status(status: str) -> str:
    account_key = open_funded_account_via_api()
    if status == "ACTIVE":
        return account_key

    transitions = ["CLOSED"] if status == "CLOSED" else ["INACTIVE"]
    for target_status in transitions:
        response = ClientRequisition.send(
            "PATCH",
            f"/account/{account_key}",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
            payload={
                "status": target_status,
                "reason": "Preparação do cenário de teste da R08",
            },
        )
        assert response.response_status == 200, (
            f"R06 PATCH failed: {response.response_status} "
            f"{response.response_content!r}"
        )
    return account_key


def test_empty_account_statement_uses_default_pagination() -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 200
    assert response.response_json == {
        "data": [],
        "pagination": {
            "current_page": 1,
            "next_page": None,
            "rows_per_page": 20,
        },
    }


def test_empty_account_statement_uses_requested_page_and_limit() -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"page": "3", "limit": "10"},
    )

    assert response.response_status == 200
    assert response.response_json == {
        "data": [],
        "pagination": {
            "current_page": 3,
            "next_page": None,
            "rows_per_page": 10,
        },
    }


def test_statement_rejects_malformed_account_key() -> None:
    response = ClientRequisition.send(
        "GET",
        "/account/not-a-uuid/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


def test_statement_returns_account_not_found() -> None:
    response = ClientRequisition.send(
        "GET",
        f"/account/{uuid4()}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 404
    assert response.response_json["code"] == "ACC0001"


@pytest.mark.parametrize("account_status", ["ACTIVE", "INACTIVE", "CLOSED"])
def test_empty_statement_is_available_for_every_account_status(
    account_status: str,
) -> None:
    account_key = _open_account_with_status(account_status)

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 200
    assert response.response_json["data"] == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"INTERNAL-TOKEN": "invalid-token"},
    ],
)
def test_statement_requires_valid_internal_token(
    headers: dict[str, str],
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers=headers,
    )

    assert response.response_status == 403
    assert response.response_json["code"] == "QIT000002"
