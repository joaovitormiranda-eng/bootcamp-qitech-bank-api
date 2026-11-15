"""Cálculo puro da tarifa cobrada em transferências."""

from typing import NamedTuple


BASIS_POINTS_DIVISOR = 10_000
HALF_UP_INCREMENT = BASIS_POINTS_DIVISOR // 2


class TransferFeeProfile(NamedTuple):
    rate_bps: int
    minimum_fee_cents: int
    maximum_fee_cents: int


TRANSFER_FEE_PROFILES = {
    "INDIVIDUAL": TransferFeeProfile(
        rate_bps=50,
        minimum_fee_cents=50,
        maximum_fee_cents=1_000,
    ),
    "COMPANY": TransferFeeProfile(
        rate_bps=100,
        minimum_fee_cents=100,
        maximum_fee_cents=1_500,
    ),
}


def calculate_transfer_fee_cents(amount_cents: int, client_type: str) -> int:
    """Calcula a fee em cents aplicando HALF_UP, piso e teto do perfil."""
    profile = TRANSFER_FEE_PROFILES[client_type]
    proportional_fee_cents = (
        amount_cents * profile.rate_bps + HALF_UP_INCREMENT
    ) // BASIS_POINTS_DIVISOR

    return min(
        max(proportional_fee_cents, profile.minimum_fee_cents),
        profile.maximum_fee_cents,
    )
