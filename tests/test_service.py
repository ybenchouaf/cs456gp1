import pytest
import service


@pytest.fixture
def client():
    service.app.config["TESTING"] = True
    service.tickets.clear()
    with service.app.test_client() as c:
        yield c
    service.tickets.clear()


def get_ticket(client):
    response = client.post("/login", json={"username": service.USERNAME, "password": service.PASSWORD})
    return response.get_json()["ticket"]


def test_login_valid(client):
    response = client.post("/login", json={"username": service.USERNAME, "password": service.PASSWORD})
    assert response.status_code == 200
    body = response.get_json()
    assert body["ticket"]
    assert body["expires_in"] == service.TICKET_LIFETIME


def test_login_invalid(client):
    response = client.post("/login", json={"username": "random", "password": "wrong"})
    assert response.status_code == 401
    assert service.tickets == {}


def test_validate_valid(client):
    ticket = get_ticket(client)
    assert client.post("/validate", json={"ticket": ticket}).get_json() == {"valid": True}


def test_validate_invalid(client):
    assert client.post("/validate", json={"ticket": "fake"}).get_json() == {"valid": False}


def test_validate_expired(client):
    ticket = get_ticket(client)
    service.tickets[ticket] = service.time.monotonic() - 1  # force expiry instead of waiting 60s
    assert client.post("/validate", json={"ticket": ticket}).get_json() == {"valid": False}