import pytest

from tests.integration.transaction.support import open_funded_account_via_api
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


@pytest.mark.parametrize("page", ["0", "-1", "abc", ""])
def test_statement_rejects_invalid_page(
    page: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"page": page},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize("limit", ["0", "-1", "101", "abc", ""])
def test_statement_rejects_invalid_limit(
    limit: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"limit": limit},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize("order_by", ["ASC", "DESC", "foo", ""])
def test_statement_rejects_invalid_order_by(
    order_by: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"order_by": order_by},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


def test_statement_rejects_unknown_query_param() -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"banana": "123"},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize(
    ("param_name", "first_value", "second_value"),
    [
        ("page", "1", "2"),
        ("limit", "10", "20"),
        ("order_by", "asc", "desc"),
        ("date_from", "2026-01-01", "2026-01-02"),
        ("date_to", "2026-01-01", "2026-01-02"),
    ],
)
def test_statement_rejects_repeated_scalar_query_param(
    param_name: str,
    first_value: str,
    second_value: str,
) -> None:
    account_key = open_funded_account_via_api()
    endpoint = (
        f"/account/{account_key}/transactions"
        f"?{param_name}={first_value}&{param_name}={second_value}"
    )

    response = ClientRequisition.send(
        "GET",
        endpoint,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize(
    "param_name",
    ["page", "limit", "order_by", "date_from", "date_to"],
)
def test_statement_rejects_blank_query_param(
    param_name: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={param_name: ""},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize("date_param", ["date_from", "date_to"])
@pytest.mark.parametrize("invalid_date", ["01/10/2026", "2026-2-1", "abc"])
def test_statement_rejects_malformed_date_format(
    date_param: str,
    invalid_date: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={date_param: invalid_date},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


@pytest.mark.parametrize(
    "query_params",
    [
        {"page": "999", "limit": "1", "order_by": "asc"},
        {"page": "1", "limit": "100", "order_by": "desc"},
        {"date_from": "2026-01-01"},
        {"date_to": "2026-01-31"},
    ],
)
def test_statement_accepts_valid_query_params_for_empty_account(
    query_params: dict[str, str],
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params=query_params,
    )

    assert response.response_status == 200
    assert response.response_json["data"] == []
