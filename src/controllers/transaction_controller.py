from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg2.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from services.transfer_fee import calculate_transfer_fee_cents
from services.transaction_hash import (
    build_deposit_request_hash,
    build_transfer_request_hash,
)
from dtos import TransactionDTO, TransactionStatementDTO
from errors import (
    AccountNotActive,
    AccountNotFound,
    IdempotencyKeyConflict,
    InsufficientBalance,
    InvalidSchema,
    InvalidTransactionAmount,
    InvalidTransactionDateRange,
    SelfTransferNotAllowed,
)
from models import AccountStatus, FinancialTransaction, TransactionEntry
from repositories import AccountRepository, TransactionRepository


BIGINT_MAX = 9_223_372_036_854_775_807
IDEMPOTENCY_KEY_CONSTRAINT = (
    "financial_transaction_request_control_key_key"
)


class TransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.account_repository = AccountRepository(self.context)
        self.transaction_repository = TransactionRepository(self.context)

    def get_statement(
        self,
        account_key: str,
        page: int,
        limit: int,
        order_by: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        try:
            parsed_account_key = UUID(account_key)
        except (AttributeError, TypeError, ValueError):
            raise InvalidSchema("account_key must be a valid UUID") from None

        parsed_date_from = self._parse_statement_date(date_from, "date_from")
        parsed_date_to = self._parse_statement_date(date_to, "date_to")
        if (
            parsed_date_from is not None
            and parsed_date_to is not None
            and parsed_date_from > parsed_date_to
        ):
            raise InvalidTransactionDateRange()

        account_result = self.account_repository.get_by_key_with_timezone(
            parsed_account_key
        )
        if account_result is None:
            raise AccountNotFound(str(parsed_account_key))

        account, client_timezone_name = account_result
        client_timezone = ZoneInfo(client_timezone_name)
        lower_bound_utc = (
            datetime.combine(
                parsed_date_from,
                time.min,
                tzinfo=client_timezone,
            ).astimezone(timezone.utc)
            if parsed_date_from is not None
            else None
        )
        upper_bound_utc = (
            datetime.combine(
                parsed_date_to + timedelta(days=1),
                time.min,
                tzinfo=client_timezone,
            ).astimezone(timezone.utc)
            if parsed_date_to is not None
            else None
        )
        entries = self.transaction_repository.list_statement_entries(
            account_id=account.id,
            offset=(page - 1) * limit,
            limit=limit + 1,
            order_by=order_by,
            lower_bound_utc=lower_bound_utc,
            upper_bound_utc=upper_bound_utc,
        )
        has_next = len(entries) > limit

        return {
            "data": [
                TransactionStatementDTO.obj_to_response(entry)
                for entry in entries[:limit]
            ],
            "next_page": page + 1 if has_next else None,
        }

    @staticmethod
    def _parse_statement_date(value: str | None, field_name: str) -> date | None:
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise InvalidSchema(f"{field_name} must be a valid date") from None

    def create(
        self,
        account_key: str,
        idempotency_key: str | None,
        transaction_data: dict,
    ) -> dict:
        try:
            parsed_account_key = UUID(account_key)
        except (AttributeError, TypeError, ValueError):
            raise InvalidSchema("account_key must be a valid UUID") from None

        try:
            parsed_idempotency_key = UUID(idempotency_key)
        except (AttributeError, TypeError, ValueError):
            raise InvalidSchema("Idempotency-Key must be a valid UUID") from None

        transaction_type = transaction_data["transaction_type"]
        amount_cents = transaction_data["amount_cents"]
        parsed_target_account_key = None
        if transaction_type == FinancialTransaction.DEPOSIT:
            request_hash = build_deposit_request_hash(
                parsed_account_key,
                amount_cents,
            )
        else:
            try:
                parsed_target_account_key = UUID(
                    transaction_data["target_account_key"]
                )
            except (AttributeError, TypeError, ValueError):
                raise InvalidSchema(
                    "target_account_key must be a valid UUID"
                ) from None
            request_hash = build_transfer_request_hash(
                parsed_account_key,
                parsed_target_account_key,
                amount_cents,
            )

        try:
            existing_response = self._get_existing_response(
                parsed_idempotency_key,
                request_hash,
            )
            if existing_response is not None:
                return existing_response

            if (
                transaction_type == FinancialTransaction.TRANSFER
                and parsed_account_key == parsed_target_account_key
            ):
                raise SelfTransferNotAllowed()

            minimum_amount_cents = (
                1
                if transaction_type == FinancialTransaction.DEPOSIT
                else 1_000
            )
            if (
                amount_cents < minimum_amount_cents
                or amount_cents > BIGINT_MAX
            ):
                raise InvalidTransactionAmount()

            try:
                if transaction_type == FinancialTransaction.DEPOSIT:
                    return self._create_deposit(
                        account_key=parsed_account_key,
                        idempotency_key=parsed_idempotency_key,
                        request_hash=request_hash,
                        amount_cents=amount_cents,
                    )

                return self._create_transfer(
                    source_account_key=parsed_account_key,
                    target_account_key=parsed_target_account_key,
                    idempotency_key=parsed_idempotency_key,
                    request_hash=request_hash,
                    amount_cents=amount_cents,
                )
            except IntegrityError as error:
                if not self._is_idempotency_key_collision(error):
                    raise

                self.session.rollback()
                winner_response = self._get_existing_response(
                    parsed_idempotency_key,
                    request_hash,
                )
                if winner_response is None:
                    raise
                return winner_response
        except Exception:
            self.session.rollback()
            raise

    def _create_deposit(
        self,
        account_key: UUID,
        idempotency_key: UUID,
        request_hash: str,
        amount_cents: int,
    ) -> dict:
        account = self.account_repository.get_by_key_for_update(account_key)
        if account is None:
            raise AccountNotFound(str(account_key))

        replay_response = self._get_existing_response(
            idempotency_key,
            request_hash,
        )
        if replay_response is not None:
            self.session.rollback()
            return replay_response

        if account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(account.status.enumerator)
        if account.balance_cents > BIGINT_MAX - amount_cents:
            raise InvalidTransactionAmount()

        transaction_created_at = datetime.now(timezone.utc)
        transaction_key = uuid4()
        transaction = self.transaction_repository.create_transaction(
            transaction_key=transaction_key,
            request_control_key=idempotency_key,
            request_hash=request_hash,
            transaction_type=FinancialTransaction.DEPOSIT,
            created_at=transaction_created_at,
        )
        balance_after_cents = account.balance_cents + amount_cents
        self.transaction_repository.create_entry(
            transaction_id=transaction.id,
            account_id=account.id,
            direction=TransactionEntry.CREDIT,
            entry_type=TransactionEntry.PRINCIPAL,
            amount_cents=amount_cents,
            balance_after_cents=balance_after_cents,
            created_at=transaction_created_at,
        )
        self.account_repository.update_balance(
            account=account,
            balance_cents=balance_after_cents,
            updated_at=transaction_created_at,
        )

        return self._commit_and_build_response(transaction_key)

    def _create_transfer(
        self,
        source_account_key: UUID,
        target_account_key: UUID,
        idempotency_key: UUID,
        request_hash: str,
        amount_cents: int,
    ) -> dict:
        account_ids_by_key = self.account_repository.get_ids_by_keys(
            (source_account_key, target_account_key)
        )
        if source_account_key not in account_ids_by_key:
            raise AccountNotFound(str(source_account_key))
        if target_account_key not in account_ids_by_key:
            raise AccountNotFound(str(target_account_key))

        locked_accounts = self.account_repository.get_by_ids_for_update(
            sorted(account_ids_by_key.values())
        )
        accounts_by_key = {
            account.account_key: account for account in locked_accounts
        }
        source_account = accounts_by_key[source_account_key]
        target_account = accounts_by_key[target_account_key]

        replay_response = self._get_existing_response(
            idempotency_key,
            request_hash,
        )
        if replay_response is not None:
            self.session.rollback()
            return replay_response

        if source_account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(source_account.status.enumerator)
        if target_account.status.enumerator != AccountStatus.ACTIVE:
            raise AccountNotActive(target_account.status.enumerator)

        source_client_type = self.account_repository.get_client_type(
            source_account.client_id
        )
        fee_cents = calculate_transfer_fee_cents(
            amount_cents,
            source_client_type,
        )
        if amount_cents > BIGINT_MAX - fee_cents:
            raise InvalidTransactionAmount()
        if target_account.balance_cents > BIGINT_MAX - amount_cents:
            raise InvalidTransactionAmount()

        total_debit_cents = amount_cents + fee_cents
        if source_account.balance_cents < total_debit_cents:
            raise InsufficientBalance()

        source_after_principal = source_account.balance_cents - amount_cents
        source_after_fee = source_after_principal - fee_cents
        target_after_principal = target_account.balance_cents + amount_cents
        transaction_created_at = datetime.now(timezone.utc)
        transaction_key = uuid4()
        transaction = self.transaction_repository.create_transaction(
            transaction_key=transaction_key,
            request_control_key=idempotency_key,
            request_hash=request_hash,
            transaction_type=FinancialTransaction.TRANSFER,
            created_at=transaction_created_at,
        )
        self.transaction_repository.create_entry(
            transaction_id=transaction.id,
            account_id=source_account.id,
            direction=TransactionEntry.DEBIT,
            entry_type=TransactionEntry.PRINCIPAL,
            amount_cents=amount_cents,
            balance_after_cents=source_after_principal,
            created_at=transaction_created_at,
        )
        self.transaction_repository.create_entry(
            transaction_id=transaction.id,
            account_id=source_account.id,
            direction=TransactionEntry.DEBIT,
            entry_type=TransactionEntry.FEE,
            amount_cents=fee_cents,
            balance_after_cents=source_after_fee,
            created_at=transaction_created_at,
        )
        self.transaction_repository.create_entry(
            transaction_id=transaction.id,
            account_id=target_account.id,
            direction=TransactionEntry.CREDIT,
            entry_type=TransactionEntry.PRINCIPAL,
            amount_cents=amount_cents,
            balance_after_cents=target_after_principal,
            created_at=transaction_created_at,
        )
        self.account_repository.update_balance(
            account=source_account,
            balance_cents=source_after_fee,
            updated_at=transaction_created_at,
        )
        self.account_repository.update_balance(
            account=target_account,
            balance_cents=target_after_principal,
            updated_at=transaction_created_at,
        )

        return self._commit_and_build_response(transaction_key)

    def _commit_and_build_response(self, transaction_key: UUID) -> dict:
        self.session.commit()
        persisted_transaction = (
            self.transaction_repository.get_by_key_with_entries(
                transaction_key
            )
        )
        return TransactionDTO.obj_to_response(persisted_transaction)

    def _get_existing_response(
        self,
        idempotency_key: UUID,
        request_hash: str,
    ) -> dict | None:
        existing_transaction = (
            self.transaction_repository.get_by_request_control_key_with_entries(
                idempotency_key
            )
        )
        if existing_transaction is None:
            return None
        if existing_transaction.request_hash != request_hash:
            raise IdempotencyKeyConflict()
        return TransactionDTO.obj_to_response(existing_transaction)

    @staticmethod
    def _is_idempotency_key_collision(error: IntegrityError) -> bool:
        return (
            isinstance(error.orig, UniqueViolation)
            and error.orig.diag.constraint_name
            == IDEMPOTENCY_KEY_CONSTRAINT
        )
