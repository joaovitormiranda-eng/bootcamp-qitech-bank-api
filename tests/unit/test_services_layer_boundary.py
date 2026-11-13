"""Guarda a fronteira COD-09: a lógica de fee/hash vive em services.*."""

import importlib

import pytest

import controllers.transaction_controller as transaction_controller
import services.transaction_hash as transaction_hash
import services.transfer_fee as transfer_fee


def test_services_fee_and_hash_modules_import() -> None:
    # COD-09: os módulos puros de fee/hash agora são a casa canônica em
    # services.*, importáveis sem o pacote controllers.
    assert transfer_fee.calculate_transfer_fee_cents is not None
    assert transaction_hash.build_deposit_request_hash is not None
    assert transaction_hash.build_transfer_request_hash is not None


@pytest.mark.parametrize(
    "legacy_module",
    [
        "controllers.transaction_fee",
        "controllers.transaction_hash",
    ],
)
def test_legacy_controller_modules_no_longer_exist(legacy_module: str) -> None:
    # COD-09: os antigos módulos dentro do pacote controllers foram
    # removidos; importá-los deve falhar com ModuleNotFoundError.
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(legacy_module)


def test_transaction_controller_resolves_fee_from_services() -> None:
    # COD-09: o controller orquestra usando a função do pacote services,
    # não uma cópia local dentro de controllers.
    assert (
        transaction_controller.calculate_transfer_fee_cents
        is transfer_fee.calculate_transfer_fee_cents
    )


def test_transaction_controller_resolves_hashes_from_services() -> None:
    # COD-09: idem para as funções de hash de intenção (deposit/transfer).
    assert (
        transaction_controller.build_deposit_request_hash
        is transaction_hash.build_deposit_request_hash
    )
    assert (
        transaction_controller.build_transfer_request_hash
        is transaction_hash.build_transfer_request_hash
    )
