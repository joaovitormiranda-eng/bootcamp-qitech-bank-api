from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import joinedload, selectinload

from database import Context
from models import (
    EntryType,
    FinancialTransaction,
    TransactionDirection,
    TransactionEntry,
    TransactionType,
)


class TransactionRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def _transaction_type_id(self, enumerator: str) -> int:
        """Resolve o texto do tipo de operação para o id da lookup."""
        return (
            self.session.query(TransactionType.id)
            .filter(TransactionType.enumerator == enumerator)
            .scalar()
        )

    def _direction_id(self, enumerator: str) -> int:
        """Resolve o texto da direção para o id da lookup."""
        return (
            self.session.query(TransactionDirection.id)
            .filter(TransactionDirection.enumerator == enumerator)
            .scalar()
        )

    def _entry_type_id(self, enumerator: str) -> int:
        """Resolve o texto da natureza do lançamento para o id da lookup."""
        return (
            self.session.query(EntryType.id)
            .filter(EntryType.enumerator == enumerator)
            .scalar()
        )

    def create_transaction(
        self,
        transaction_key: UUID,
        request_control_key: UUID,
        request_hash: str,
        transaction_type: str,
        created_at: datetime,
    ) -> FinancialTransaction:
        transaction = FinancialTransaction(
            transaction_key=transaction_key,
            request_control_key=request_control_key,
            request_hash=request_hash,
            transaction_type_id=self._transaction_type_id(transaction_type),
            created_at=created_at,
        )
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def create_entry(
        self,
        transaction_id: int,
        account_id: int,
        direction: str,
        entry_type: str,
        amount_cents: int,
        balance_after_cents: int,
        created_at: datetime,
    ) -> TransactionEntry:
        entry = TransactionEntry(
            entry_key=uuid4(),
            transaction_id=transaction_id,
            account_id=account_id,
            direction_id=self._direction_id(direction),
            entry_type_id=self._entry_type_id(entry_type),
            amount_cents=amount_cents,
            balance_after_cents=balance_after_cents,
            created_at=created_at,
        )
        self.session.add(entry)
        return entry

    def list_statement_entries(
        self,
        account_id: int,
        offset: int,
        limit: int,
        order_by: str,
        lower_bound_utc: datetime | None = None,
        upper_bound_utc: datetime | None = None,
    ) -> list[TransactionEntry]:
        query = (
            self.session.query(TransactionEntry)
            .options(
                joinedload(TransactionEntry.transaction)
                .selectinload(FinancialTransaction.entries)
                .joinedload(TransactionEntry.account)
            )
            .join(
                FinancialTransaction,
                FinancialTransaction.id == TransactionEntry.transaction_id,
            )
            .filter(TransactionEntry.account_id == account_id)
        )

        if lower_bound_utc is not None:
            query = query.filter(
                FinancialTransaction.created_at >= lower_bound_utc
            )
        if upper_bound_utc is not None:
            query = query.filter(
                FinancialTransaction.created_at < upper_bound_utc
            )

        if order_by == "asc":
            query = query.order_by(
                FinancialTransaction.created_at.asc(),
                FinancialTransaction.id.asc(),
                TransactionEntry.id.asc(),
            )
        else:
            query = query.order_by(
                FinancialTransaction.created_at.desc(),
                FinancialTransaction.id.desc(),
                TransactionEntry.id.asc(),
            )

        return query.offset(offset).limit(limit).all()

    def get_by_key_with_entries(
        self,
        transaction_key: UUID,
    ) -> FinancialTransaction:
        return (
            self.session.query(FinancialTransaction)
            .options(
                selectinload(FinancialTransaction.entries).joinedload(
                    TransactionEntry.account
                )
            )
            .filter(FinancialTransaction.transaction_key == transaction_key)
            .one()
        )

    def get_by_request_control_key_with_entries(
        self,
        request_control_key: UUID,
    ) -> FinancialTransaction | None:
        return (
            self.session.query(FinancialTransaction)
            .options(
                selectinload(FinancialTransaction.entries).joinedload(
                    TransactionEntry.account
                )
            )
            .filter(
                FinancialTransaction.request_control_key
                == request_control_key
            )
            .one_or_none()
        )
