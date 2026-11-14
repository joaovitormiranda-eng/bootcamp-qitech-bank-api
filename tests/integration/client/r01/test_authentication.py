"""Cen?rios da R01 organizados por comportamento."""

from .support import *


class TestCreateClient:
    def test_rejects_missing_internal_token(
        self, individual_payload: dict[str, str]
    ) -> None:
        response = ClientRequisition.send(
            "POST", "/client", payload=individual_payload
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    def test_rejects_invalid_internal_token(
        self, individual_payload: dict[str, str]
    ) -> None:
        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=individual_payload,
            headers={"INTERNAL-TOKEN": f"{INTERNAL_TOKEN}-invalid"},
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    def test_rejects_empty_internal_token(
        self, individual_payload: dict[str, str]
    ) -> None:
        """Header presente porém vazio não pode virar bypass (SEC-01).

        Mesmo que o token configurado fosse vazio, um header vazio precisa
        reprovar: a comparação em tempo constante só roda sobre dois valores
        não vazios.
        """
        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=individual_payload,
            headers={"INTERNAL-TOKEN": ""},
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    def test_rejects_non_ascii_internal_token(
        self, individual_payload: dict[str, str]
    ) -> None:
        """Token inválido com caractere não ASCII -> 403, nunca 500 (SEC-01).

        O Starlette decodifica headers HTTP em Latin-1, então um header como
        "tÿ" vira uma str não ASCII. A comparação em tempo constante precisa
        reprovar esse valor com o mesmo contrato (403 / QIT000002), sem deixar
        vazar um TypeError que viraria 500.
        """
        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=individual_payload,
            headers={"INTERNAL-TOKEN": f"{INTERNAL_TOKEN}-inv\u00ff"},
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    def test_rejects_near_miss_internal_token(
        self, individual_payload: dict[str, str]
    ) -> None:
        """Token quase igual ao válido (só o último caractere troca) -> 403.

        Guarda a comparação em tempo constante: qualquer diferença, por menor
        que seja, reprova com o mesmo código, sem casar por prefixo.
        """
        near_miss = INTERNAL_TOKEN[:-1] + (
            "X" if INTERNAL_TOKEN[-1] != "X" else "Y"
        )

        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=individual_payload,
            headers={"INTERNAL-TOKEN": near_miss},
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"
