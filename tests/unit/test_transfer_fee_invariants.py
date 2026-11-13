"""Invariantes de fronteira da tarifa pura de transferência (RFC R07).

Casos adicionais e específicos de borda que NÃO duplicam os parametrizados
de tests/unit/test_transaction_fee.py: cada caso amarra um invariante do
RFC (piso, teto e arredondamento HALF_UP na borda exata de .5 cent).
"""

from services.transfer_fee import (
    TRANSFER_FEE_PROFILES,
    calculate_transfer_fee_cents,
)


def test_individual_charges_floor_just_below_min_fee_threshold() -> None:
    # RFC: PF cobra 0,50% com piso de 50 cents. O limiar em que a parcela
    # proporcional iguala o piso é 10_000 (0,50% de 10_000 = 50). Logo um
    # valor logo abaixo do limiar ainda deve ser elevado ao piso (50).
    profile = TRANSFER_FEE_PROFILES["INDIVIDUAL"]
    just_below_threshold = 9_900

    fee_cents = calculate_transfer_fee_cents(just_below_threshold, "INDIVIDUAL")

    assert fee_cents == profile.minimum_fee_cents == 50


def test_individual_charges_cap_on_large_amount() -> None:
    # RFC: PF tem teto de 1_000 cents. Um valor grande (0,50% >> teto) é
    # limitado ao teto.
    profile = TRANSFER_FEE_PROFILES["INDIVIDUAL"]

    fee_cents = calculate_transfer_fee_cents(5_000_000, "INDIVIDUAL")

    assert fee_cents == profile.maximum_fee_cents == 1_000


def test_company_charges_floor_just_below_min_fee_threshold() -> None:
    # RFC: PJ cobra 1,00% com piso de 100 cents. O limiar é 10_000
    # (1,00% de 10_000 = 100); logo abaixo dele a tarifa é elevada ao piso.
    profile = TRANSFER_FEE_PROFILES["COMPANY"]
    just_below_threshold = 9_900

    fee_cents = calculate_transfer_fee_cents(just_below_threshold, "COMPANY")

    assert fee_cents == profile.minimum_fee_cents == 100


def test_company_charges_cap_on_large_amount() -> None:
    # RFC: PJ tem teto de 1_500 cents. Um valor grande é limitado ao teto.
    profile = TRANSFER_FEE_PROFILES["COMPANY"]

    fee_cents = calculate_transfer_fee_cents(5_000_000, "COMPANY")

    assert fee_cents == profile.maximum_fee_cents == 1_500


def test_individual_rounds_half_up_at_exact_half_cent_boundary() -> None:
    # RFC: arredondamento HALF_UP. Para PF (0,50%), amount=20_300 produz
    # parcela proporcional de 101,5 cents (20_300 * 50 / 10_000), exatamente
    # na borda de .5 cent, que deve ser arredondada PARA CIMA -> 102.
    fee_cents = calculate_transfer_fee_cents(20_300, "INDIVIDUAL")

    assert fee_cents == 102


def test_company_rounds_half_up_at_exact_half_cent_boundary() -> None:
    # RFC: HALF_UP. Para PJ (1,00%), amount=20_150 produz parcela
    # proporcional de 201,5 cents (20_150 * 100 / 10_000), exatamente na
    # borda de .5 cent, arredondada PARA CIMA -> 202.
    fee_cents = calculate_transfer_fee_cents(20_150, "COMPANY")

    assert fee_cents == 202
