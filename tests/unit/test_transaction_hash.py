from hashlib import sha256
from uuid import UUID, uuid4

from services.transaction_hash import (
    build_deposit_request_hash,
    build_transfer_request_hash,
    canonicalize_deposit_request,
    canonicalize_transfer_request,
)


def test_deposit_canonical_request_has_exact_format() -> None:
    account_key = UUID("550E8400-E29B-41D4-A716-446655440000")

    canonical_request = canonicalize_deposit_request(account_key, 50_000)

    assert canonical_request == (
        "DEPOSIT|550e8400-e29b-41d4-a716-446655440000|50000"
    )


def test_deposit_hash_is_sha256_lowercase_hex() -> None:
    account_key = UUID("550e8400-e29b-41d4-a716-446655440000")
    canonical_request = (
        "DEPOSIT|550e8400-e29b-41d4-a716-446655440000|50000"
    )

    request_hash = build_deposit_request_hash(account_key, 50_000)

    assert request_hash == sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()
    assert len(request_hash) == 64
    assert request_hash == request_hash.lower()


def test_same_deposit_intention_always_has_same_hash() -> None:
    account_key = uuid4()

    first_hash = build_deposit_request_hash(account_key, 50_000)
    second_hash = build_deposit_request_hash(account_key, 50_000)

    assert first_hash == second_hash


def test_changing_amount_changes_deposit_hash() -> None:
    account_key = uuid4()

    assert build_deposit_request_hash(
        account_key, 50_000
    ) != build_deposit_request_hash(account_key, 60_000)


def test_changing_account_changes_deposit_hash() -> None:
    assert build_deposit_request_hash(
        uuid4(), 50_000
    ) != build_deposit_request_hash(uuid4(), 50_000)


def test_transport_metadata_and_json_representation_do_not_change_hash() -> None:
    account_key = uuid4()
    first_idempotency_key = uuid4()
    second_idempotency_key = uuid4()
    first_payload = {
        "transaction_type": "DEPOSIT",
        "amount_cents": 50_000,
    }
    second_payload = {
        "amount_cents": 50_000,
        "transaction_type": "DEPOSIT",
    }
    historical_fee_cents = 999

    first_hash = build_deposit_request_hash(
        account_key,
        first_payload["amount_cents"],
    )
    second_hash = build_deposit_request_hash(
        account_key,
        second_payload["amount_cents"],
    )

    assert first_idempotency_key != second_idempotency_key
    assert historical_fee_cents != 0
    assert list(first_payload) != list(second_payload)
    assert first_hash == second_hash


def test_transfer_canonical_request_has_exact_format() -> None:
    source_account_key = UUID("550E8400-E29B-41D4-A716-446655440000")
    target_account_key = UUID("6BA7B810-9DAD-41D1-80B4-00C04FD430C8")

    canonical_request = canonicalize_transfer_request(
        source_account_key,
        target_account_key,
        50_000,
    )

    assert canonical_request == (
        "TRANSFER|550e8400-e29b-41d4-a716-446655440000|"
        "6ba7b810-9dad-41d1-80b4-00c04fd430c8|50000"
    )


def test_transfer_hash_is_sha256_lowercase_hex() -> None:
    source_account_key = UUID("550e8400-e29b-41d4-a716-446655440000")
    target_account_key = UUID("6ba7b810-9dad-41d1-80b4-00c04fd430c8")
    canonical_request = (
        "TRANSFER|550e8400-e29b-41d4-a716-446655440000|"
        "6ba7b810-9dad-41d1-80b4-00c04fd430c8|50000"
    )

    request_hash = build_transfer_request_hash(
        source_account_key,
        target_account_key,
        50_000,
    )

    assert request_hash == sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()
    assert len(request_hash) == 64
    assert request_hash == request_hash.lower()


def test_same_transfer_intention_always_has_same_hash() -> None:
    source_account_key = uuid4()
    target_account_key = uuid4()

    first_hash = build_transfer_request_hash(
        source_account_key,
        target_account_key,
        50_000,
    )
    second_hash = build_transfer_request_hash(
        source_account_key,
        target_account_key,
        50_000,
    )

    assert first_hash == second_hash


def test_transfer_hash_changes_with_financial_intention() -> None:
    source_account_key = uuid4()
    target_account_key = uuid4()

    original_hash = build_transfer_request_hash(
        source_account_key,
        target_account_key,
        50_000,
    )

    assert original_hash != build_transfer_request_hash(
        uuid4(),
        target_account_key,
        50_000,
    )
    assert original_hash != build_transfer_request_hash(
        source_account_key,
        uuid4(),
        50_000,
    )
    assert original_hash != build_transfer_request_hash(
        source_account_key,
        target_account_key,
        60_000,
    )
