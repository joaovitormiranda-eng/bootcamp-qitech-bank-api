from fastapi import Response, status
from fastapi.responses import JSONResponse

from constants import SERVICE_NAME


class HealthCheckResource:
    """As duas rotas que respondem sem token: quem é este serviço, e se ele está vivo."""

    def on_get_home(self) -> JSONResponse:
        # A raiz é pública (sem INTERNAL-TOKEN) e serve só para dizer QUEM
        # é este serviço. Não expõe detalhe de runtime: o PID do processo
        # (os.getpid()) foi removido por ser informação interna sem valor
        # para o chamador e desnecessária na superfície pública (SEC-06 da
        # auditoria P2-A). Nenhum contrato/consumidor depende do campo "id".
        home = {"service": SERVICE_NAME}

        return JSONResponse(content=home, status_code=status.HTTP_200_OK)

    def on_get_health_check(self) -> Response:
        # 204 quer dizer "deu tudo certo e não tenho nada a dizer".
        # Por isso a resposta não tem corpo nenhum: é um `Response`
        # pelado, e não um JSONResponse.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
