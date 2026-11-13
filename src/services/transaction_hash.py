from hashlib import sha256
from uuid import UUID


def canonicalize_deposit_request(
    account_key: UUID,
    amount_cents: int,
) -> str:
    return f"DEPOSIT|{str(account_key)}|{amount_cents}"


def build_deposit_request_hash(
    account_key: UUID,
    amount_cents: int,
) -> str:
    canonical_request = canonicalize_deposit_request(
        account_key,
        amount_cents,
    )
    return sha256(canonical_request.encode("utf-8")).hexdigest()


def canonicalize_transfer_request(
    source_account_key: UUID,
    target_account_key: UUID,
    amount_cents: int,
) -> str:
    return (
        f"TRANSFER|{str(source_account_key)}|{str(target_account_key)}|"
        f"{amount_cents}"
    )


def build_transfer_request_hash(
    source_account_key: UUID,
    target_account_key: UUID,
    amount_cents: int,
) -> str:
    canonical_request = canonicalize_transfer_request(
        source_account_key,
        target_account_key,
        amount_cents,
    )
    return sha256(canonical_request.encode("utf-8")).hexdigest()
