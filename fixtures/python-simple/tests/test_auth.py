"""Tests for authentication service."""

from services.auth import authenticate, create_session, validate_token


def test_authenticate_success():
    """Test successful authentication."""
    user = authenticate("test@example.com", "password123")
    assert user is not None
    assert user.email == "test@example.com"


def test_authenticate_failure():
    """Test failed authentication."""
    user = authenticate("", "")
    assert user is None


def test_create_session():
    """Test session creation."""
    user = authenticate("test@example.com", "password123")
    token = create_session(user)
    assert token.startswith("session_")


def test_validate_token():
    """Test token validation."""
    assert validate_token("session_test@example.com_123")
    assert not validate_token("invalid_token")
