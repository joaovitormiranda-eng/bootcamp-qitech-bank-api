"""Operações de controle do MockServer usadas pelos testes de integração."""

from os import environ

import requests


MOCKSERVER_URL = environ.get("MOCKSERVER_URL", "http://127.0.0.1:1080")
MOCKSERVER_CONTROL_TIMEOUT_SECONDS = 5


class MockServer:
    """Pequeno cliente para a API administrativa do MockServer."""

    @staticmethod
    def reset() -> None:
        response = requests.put(
            f"{MOCKSERVER_URL}/mockserver/reset",
            timeout=MOCKSERVER_CONTROL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    @staticmethod
    def expect(
        http_request: dict,
        http_response: dict,
    ) -> None:
        response = requests.put(
            f"{MOCKSERVER_URL}/mockserver/expectation",
            json={
                "httpRequest": http_request,
                "httpResponse": http_response,
            },
            timeout=MOCKSERVER_CONTROL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    @staticmethod
    def verify_exactly(http_request: dict, count: int) -> None:
        response = requests.put(
            f"{MOCKSERVER_URL}/mockserver/verify",
            json={
                "httpRequest": http_request,
                "times": {
                    "atLeast": count,
                    "atMost": count,
                },
            },
            timeout=MOCKSERVER_CONTROL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    @staticmethod
    def retrieve_recorded_requests(http_request: dict) -> list:
        response = requests.put(
            f"{MOCKSERVER_URL}/mockserver/retrieve",
            params={
                "type": "REQUESTS",
                "format": "JSON",
            },
            json=http_request,
            timeout=MOCKSERVER_CONTROL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
