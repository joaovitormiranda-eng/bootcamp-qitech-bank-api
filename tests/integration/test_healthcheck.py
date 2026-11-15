import asyncio
from pathlib import Path

import pytest

from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


# As frases em português que o cliente lê no campo "translation" das
# respostas de erro. Estão escritas aqui à mão pelo mesmo motivo dos
# cabeçalhos acima: o teste cobra o contrato pela rede, sem importar
# nada de src/.
#
# O que elas defendem é o ACENTO. Até 2026-08-20 o QIException raspava
# todo acento antes de responder ("normalize NFKD" + encode ASCII), e a
# fonte acentuada chegava no cliente sem cedilha nem til. Quem repuser
# aquela linha deixa o teste abaixo vermelho, nomeando o campo.
FORBIDDEN_TRANSLATION = "Requisição precisa ser interna"
NOT_FOUND_TRANSLATION = "O resource solicitado não pode ser encontrado, mas pode estar disponível no futuro. Requests subsequentes do cliente são permitidos."


class TestHealthCheck:
    def test_home(self):
        response = ClientRequisition.send("GET", "/")
        assert response.response_status == 200

    def test_home_identifies_the_service_without_leaking_the_pid(self):
        """SEC-06: a raiz pública diz QUEM é o serviço e nada de runtime.

        O corpo tem apenas ``service``; o antigo campo ``id`` (PID do
        processo via os.getpid()) foi removido por ser detalhe interno sem
        valor para o chamador na superfície pública não autenticada.
        """
        response = ClientRequisition.send("GET", "/")

        assert response.response_status == 200
        body = response.response_json
        assert "service" in body
        assert body["service"]
        assert "id" not in body

    def test_health_check(self):
        response = ClientRequisition.send("GET", "/health_check")
        assert response.response_status == 204

    @pytest.mark.parametrize(
        "token",
        [None, INTERNAL_TOKEN, "not-an-internal-token", ""],
        ids=["absent", "valid", "invalid", "empty"],
    )
    def test_health_check_is_public_and_returns_an_empty_response(self, token):
        headers = {} if token is None else {"INTERNAL-TOKEN": token}

        response = ClientRequisition.send(
            "GET",
            "/health_check",
            headers=headers,
        )

        assert response.response_status == 204
        assert response.response_content == b""
        assert response.response.headers.get("content-length") in (None, "0")

    def test_health_check_is_idempotent(self):
        responses = [
            ClientRequisition.send("GET", "/health_check")
            for _ in range(3)
        ]

        assert [response.response_status for response in responses] == [204, 204, 204]
        assert [response.response_content for response in responses] == [b"", b"", b""]

    def test_health_check_does_not_acquire_a_database_session(self, monkeypatch):
        """O app local deve continuar saudável mesmo se pedir uma sessão falhar.

        A instrumentação é local ao processo do pytest: ela exercita todos os
        middlewares e a rota real sem tocar no PostgreSQL compartilhado.
        """
        source_root = Path(__file__).resolve().parents[2] / "src"
        monkeypatch.syspath_prepend(str(source_root))
        # A aplicação valida as variáveis na importação. A URL aponta para
        # o banco local apenas para permitir criar o Engine; o patch abaixo
        # prova que a rota não chega a solicitar uma sessão ou conexão.
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql+psycopg2://bootcamp:bootcamp@127.0.0.1:5432/bootcamp",
        )
        monkeypatch.setenv("INTERNAL_TOKEN", "default_token")
        monkeypatch.setenv("ANALYSIS_PROVIDER_URL", "http://127.0.0.1:1080")

        from app import create_app
        from database import Context, engine

        def fail_if_session_is_requested(_context):
            raise AssertionError("/health_check must not acquire a database session")

        def fail_if_connection_is_requested(*_args, **_kwargs):
            raise AssertionError("/health_check must not acquire a database connection")

        monkeypatch.setattr(Context, "get_or_create_session", fail_if_session_is_requested)
        monkeypatch.setattr(engine, "connect", fail_if_connection_is_requested)

        async def call_health_check():
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await create_app()(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/health_check",
                    "raw_path": b"/health_check",
                    "query_string": b"",
                    "headers": [(b"internal-token", b"not-an-internal-token")],
                    "client": ("127.0.0.1", 0),
                    "server": ("testserver", 80),
                },
                receive,
                send,
            )
            return messages

        messages = asyncio.run(call_health_check())
        response_start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )

        assert response_start["status"] == 204
        assert response_body == b""

    def test_no_token(self):
        response = ClientRequisition.send("PUT", "/sample")
        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    def test_sink(self):
        response = ClientRequisition.send(
            "PUT",
            "/sample",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        assert response.response_status == 404
        assert response.response_json["code"] == "QIT000404"

    def test_method_not_allowed(self):
        response = ClientRequisition.send("PUT", "/health_check")
        assert response.response_status == 405
        assert response.response_json["code"] == "QIT000405"

    def test_error_translation_keeps_accents(self):
        """O acento da fonte chega no cliente — nas duas portas de erro da API.

        São dois caminhos diferentes, e por isso são duas requisições num
        teste só. O 403 nasce DENTRO do middleware de token, que devolve a
        resposta com a requisição ainda a caminho da rota; o 404 nasce num
        exception handler, bem mais pra dentro. Um só não prova o outro.

        O que se defende aqui é o campo "translation" em português de
        verdade: JSON é UTF-8, o acento cabe nele, e a API não tem por que
        raspar cedilha e til de um texto escrito pra brasileiro ler.
        """
        response = ClientRequisition.send("PUT", "/sample")
        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"
        assert response.response_json["translation"] == FORBIDDEN_TRANSLATION

        response = ClientRequisition.send(
            "PUT",
            "/sample",
            headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        )
        assert response.response_status == 404
        assert response.response_json["code"] == "QIT000404"
        assert response.response_json["translation"] == NOT_FOUND_TRANSLATION
