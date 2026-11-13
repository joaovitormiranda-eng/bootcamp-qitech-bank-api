"""Política pura de tarifa para transferências da R07."""

import pytest


from services.transfer_fee import calculate_transfer_fee_cents


@pytest.mark.parametrize(
    ("client_type", "amount_cents", "expected_fee_cents"),
    [
        pytest.param("INDIVIDUAL", 1_000, 50, id="individual-floor"),
        pytest.param("INDIVIDUAL", 50_000, 250, id="individual-percentage"),
        pytest.param("INDIVIDUAL", 1_000_000, 1_000, id="individual-cap"),
        pytest.param("COMPANY", 1_000, 100, id="company-floor"),
        pytest.param("COMPANY", 50_000, 500, id="company-percentage"),
        pytest.param("COMPANY", 1_000_000, 1_500, id="company-cap"),
    ],
)
def test_transfer_fee_applies_profile_rate_floor_and_cap(
    client_type: str,
    amount_cents: int,
    expected_fee_cents: int,
) -> None:
    fee_cents = calculate_transfer_fee_cents(amount_cents, client_type)

    assert type(fee_cents) is int
    assert fee_cents == expected_fee_cents


@pytest.mark.parametrize(
    ("client_type", "amount_cents", "expected_fee_cents"),
    [
        pytest.param("INDIVIDUAL", 20_099, 100, id="individual-below-half"),
        pytest.param("INDIVIDUAL", 20_100, 101, id="individual-exactly-half"),
        pytest.param("INDIVIDUAL", 20_101, 101, id="individual-above-half"),
        pytest.param("COMPANY", 20_049, 200, id="company-below-half"),
        pytest.param("COMPANY", 20_050, 201, id="company-exactly-half"),
        pytest.param("COMPANY", 20_051, 201, id="company-above-half"),
    ],
)
def test_transfer_fee_rounds_proportional_value_half_up(
    client_type: str,
    amount_cents: int,
    expected_fee_cents: int,
) -> None:
    fee_cents = calculate_transfer_fee_cents(amount_cents, client_type)

    assert type(fee_cents) is int
    assert fee_cents == expected_fee_cents
