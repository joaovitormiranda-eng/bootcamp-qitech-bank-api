import hmac

from fastapi import FastAPI, Request

from constants import BYPASS_ENDPOINTS, INTERNAL_TOKEN
from errors.base_error import ForbiddenNotInternal
from errors.handlers import qi_exception_to_response


def register_internal_token_middleware(application: FastAPI) -> None:
    """Deixa passar só quem manda o header INTERNAL-TOKEN com o valor certo.

    O valor certo vem da variável de ambiente INTERNAL_TOKEN, nunca do
    código. As rotas de BYPASS_ENDPOINTS (raiz e health check) são públicas.

    Repare que aqui a gente DEVOLVE a resposta de erro em vez de levantar
    a exceção: dentro de um middleware, ninguém está escutando pra traduzir
    o erro — quem traduz são os exception handlers, que rodam mais pra
    dentro. Levantar aqui viraria um 500.

    A comparação do header usa hmac.compare_digest para não vazar, pelo
    tempo de resposta, quantos caracteres do token o atacante acertou
    (SEC-01). Antes de comparar, exigimos que tanto o header quanto o
    token configurado existam e sejam strings: compare_digest explode com
    None e um header vazio nunca pode casar com um token vazio/ausente,
    senão abriríamos um bypass de autenticação.
    """

    @application.middleware("http")
    async def check_internal_token(request: Request, call_next):
        is_public = request.url.path in BYPASS_ENDPOINTS

        if request.method == "OPTIONS" or is_public:
            return await call_next(request)

        provided_token = request.headers.get("INTERNAL-TOKEN")

        if not _tokens_match(provided_token, INTERNAL_TOKEN):
            error = ForbiddenNotInternal()
            request.state.error_code = error.code
            return qi_exception_to_response(error)

        return await call_next(request)


def _tokens_match(provided: str | None, expected: str | None) -> bool:
    """Compara o token recebido com o esperado em tempo constante.

    Qualquer valor ausente ou vazio (None ou "") reprova de imediato, sem
    chegar ao compare_digest. Isso evita o TypeError de comparar com None e
    garante que um header vazio jamais seja aceito, mesmo que o token
    configurado também estivesse vazio.

    A comparação roda sobre bytes, não str: compare_digest recusa strings
    com caracteres não ASCII, e o Starlette decodifica headers HTTP em
    Latin-1, então um header inválido como "tÿ" explodiria com TypeError e
    viraria um 500 em vez do 403 esperado. Codificamos os dois lados com o
    mesmo Latin-1: ele faz round-trip de qualquer byte decodificado de um
    header e nunca levanta UnicodeEncodeError, mantendo a comparação em
    tempo constante e consistente.
    """
    if not provided or not expected:
        return False

    return hmac.compare_digest(
        provided.encode("latin-1"), expected.encode("latin-1")
    )
