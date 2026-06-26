from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


def test_v1_models_route_is_removed():
    with TestClient(create_app()) as client:
        response = client.get("/v1/models")

    assert response.status_code == 404
