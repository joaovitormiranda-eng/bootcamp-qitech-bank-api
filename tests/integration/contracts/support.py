"""Helpers black-box para os testes de contrato transversais (COD-02/03/10).

Tudo aqui conversa com a API exclusivamente por HTTP via
``ClientRequisition.send``. Nada importa de ``src/`` nem toca o banco direto:
o objetivo é provar o contrato publicado em ``docs/ROTAS.md`` pela borda da
rede, como ``tests/integration/test_healthcheck.py`` faz.

Os dados são determinísticos e isolados: e-mails, CPF e CNPJ são gerados com
os geradores existentes em ``tests/utils`` (``RandomGenerator`` + ``uuid4``),
de modo que nenhum documento colide com o de outro teste.
"""

from uuid import uuid4

from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


# Envelope de erro de domínio publicado em ROTAS 2.2: exatamente estes campos.
ERROR_ENVELOPE_FIELDS = {"title", "description", "translation", "code"}


def auth_headers(extra: dict | None = None) -> dict:
    """Headers de uma requisição interna autenticada."""
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
    if extra:
        headers.update(extra)
    return headers


def individual_payload() -> dict:
    """Corpo R01 PF válido e único (e-mail e CPF determinísticos)."""
    from tests.utils import RandomGenerator

    return {
        "client_type": "INDIVIDUAL",
        "email": f"contracts.pf.{uuid4()}@example.com",
        "cpf": RandomGenerator.generate_cpf(),
        "full_name": "Cliente Contrato",
        "birth_date": "1990-01-01",
        "timezone": "America/Sao_Paulo",
    }


def company_payload() -> dict:
    """Corpo R01 PJ válido e único (e-mail e CNPJ determinísticos)."""
    from tests.utils import RandomGenerator

    return {
        "client_type": "COMPANY",
        "email": f"contracts.pj.{uuid4()}@example.com",
        "cnpj": RandomGenerator.generate_cnpj(),
        "legal_name": "Empresa Contrato Ltda.",
        "trade_name": "Empresa Contrato",
        "timezone": "America/Sao_Paulo",
    }


def create_client(payload: dict | None = None):
    """Cria um cliente pela R01 (POST /client) e devolve a resposta HTTP."""
    body = payload if payload is not None else individual_payload()
    return ClientRequisition.send(
        "POST",
        "/client",
        payload=body,
        headers=auth_headers(),
    )
