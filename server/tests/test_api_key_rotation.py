"""Tests for API key rotation and revocation flows."""


def _create_project(client, name: str = "rotation-project") -> tuple[str, str]:
    response = client.post("/api/v1/projects/", json={"name": name})
    assert response.status_code == 201
    body = response.json()
    return body["id"], body["api_key"]


def test_new_key_valid_after_rotation(client):
    _, old_key = _create_project(client)

    rotate_response = client.post(
        "/api/v1/projects/me/api-key/rotate",
        json={"grace_period_minutes": 30},
        headers={"X-API-Key": old_key},
    )

    assert rotate_response.status_code == 200
    new_key = rotate_response.json()["api_key"]
    assert new_key != old_key

    me_response = client.get("/api/v1/projects/me", headers={"X-API-Key": new_key})
    assert me_response.status_code == 200


def test_old_key_rejected_after_previous_key_revocation(client):
    _, old_key = _create_project(client, name="rotation-project-revoke")

    rotate_response = client.post(
        "/api/v1/projects/me/api-key/rotate",
        json={"grace_period_minutes": 30},
        headers={"X-API-Key": old_key},
    )
    new_key = rotate_response.json()["api_key"]

    revoke_response = client.post(
        "/api/v1/projects/me/api-key/revoke",
        json={"key_type": "previous"},
        headers={"X-API-Key": new_key},
    )
    assert revoke_response.status_code == 200

    old_key_response = client.get("/api/v1/projects/me", headers={"X-API-Key": old_key})
    assert old_key_response.status_code == 401


def test_unauthorized_key_rejected(client):
    response = client.get("/api/v1/projects/me", headers={"X-API-Key": "vp_invalid_key"})

    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]
