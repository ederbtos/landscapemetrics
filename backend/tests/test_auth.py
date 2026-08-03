from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register_user(mocker):
    # Mocking the users DB to not hit the real database
    mocker.patch('app.db.users.create_user', return_value=True)
    mocker.patch('app.db.refresh_tokens.store_refresh_token', return_value=None)
    
    response = client.post("/api/auth/register", json={
        "email": "test@test.com",
        "password": "password123",
        "password_confirm": "password123"
    })
    
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "expires_in" in response.json()
    assert "refresh_token" in response.cookies

def test_register_user_passwords_dont_match():
    response = client.post("/api/auth/register", json={
        "email": "test@test.com",
        "password": "password123",
        "password_confirm": "password456"
    })
    
    assert response.status_code == 400
    assert "coincidem" in response.json()["detail"].lower()

def test_login_user(mocker):
    from app.core.security import hash_password
    
    # Mock finding the user and returning the correct hash
    mocker.patch('app.db.users.get_password_hash', return_value=hash_password("password123"))
    mocker.patch('app.db.refresh_tokens.store_refresh_token', return_value=None)
    
    response = client.post("/api/auth/login", json={
        "email": "test@test.com",
        "password": "password123"
    })
    
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert "refresh_token" in response.cookies

def test_login_user_invalid(mocker):
    mocker.patch('app.db.users.get_password_hash', return_value=None)
    
    response = client.post("/api/auth/login", json={
        "email": "test@test.com",
        "password": "wrongpassword"
    })
    
    assert response.status_code == 401
