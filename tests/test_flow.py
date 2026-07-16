import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

def clear_modules():
    for name in list(sys.modules.keys()):
        if any(name.startswith(p) for p in ["routes", "models", "core", "db", "schemas", "shared", "main"]):
            del sys.modules[name]

def test_auth_signup_validation():
    clear_modules()
    sys.path.insert(0, os.path.abspath("auth_service"))
    
    from main import app
    client = TestClient(app)
    
    # Missing email/password validation
    response = client.post("/api/v1/auth/signup", json={})
    assert response.status_code == 422
    
    sys.path.remove(os.path.abspath("auth_service"))

def test_ai_generate_request_validation():
    clear_modules()
    sys.path.insert(0, os.path.abspath("ai_service"))
    
    from main import app
    client = TestClient(app)
    
    # Payload model schema validation
    response = client.post("/api/v1/ai/generate", json={"prompt": "Write a post"})
    assert response.status_code == 400 # Requires X-Account-Id header
    
    sys.path.remove(os.path.abspath("ai_service"))

def test_auth_login_validation():
    clear_modules()
    sys.path.insert(0, os.path.abspath("auth_service"))
    
    from main import app
    client = TestClient(app)
    
    response = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "123"})
    assert response.status_code == 422 # Invalid email format pydantic validation
    
    sys.path.remove(os.path.abspath("auth_service"))
