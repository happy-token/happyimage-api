from __future__ import annotations

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from services.config import config


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1"),
        ("POST", "/v1"),
        ("HEAD", "/v1"),
        ("TRACE", "/v1"),
        ("CONNECT", "/v1"),
        ("GET", "/v1/models"),
        ("HEAD", "/v1/models"),
        ("TRACE", "/v1/models"),
        ("CONNECT", "/v1/models"),
        ("POST", "/v1/images/generations"),
        ("POST", "/v1/images/edits"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/messages"),
        ("POST", "/v1/responses"),
    ],
)
def test_v1_routes_are_removed(method: str, path: str):
    with TestClient(create_app()) as client:
        response = client.request(method, path)

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/v1/models", "/v1/images/generations"])
@pytest.mark.parametrize(
    ("config_values", "origin"),
    [
        (
            {"public_app_url": "https://app.example", "cors_origins": ["https://app.example"]},
            "https://app.example",
        ),
        (
            {"public_app_url": "https://app.example", "cors_origins": ["https://app.example"]},
            "https://other.example",
        ),
        (
            {"public_app_url": "", "cors_origins": []},
            "https://any.example",
        ),
    ],
)
def test_v1_cors_preflight_routes_are_removed(config_values: dict[str, object], origin: str, path: str):
    with mock.patch.dict(config.data, config_values, clear=False):
        with TestClient(create_app()) as client:
            response = client.options(
                path,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                },
            )

    assert response.status_code == 404
