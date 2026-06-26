from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


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
