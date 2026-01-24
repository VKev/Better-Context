"""Authentication service for python-simple fixture.

Imports models to demonstrate cross-module dependency.
"""

from models import User


def authenticate(email: str, password: str) -> User | None:
    """Authenticate a user by email and password.

    Args:
        email: User's email address
        password: User's password

    Returns:
        User object if authenticated, None otherwise
    """
    # Simplified auth - in real code would check database
    if email and password:
        return User(name="Authenticated User", email=email)
    return None


def create_session(user: User) -> str:
    """Create a session token for an authenticated user.

    Args:
        user: Authenticated user

    Returns:
        Session token string
    """
    return f"session_{user.email}_{id(user)}"


def validate_token(token: str) -> bool:
    """Validate a session token.

    Args:
        token: Token to validate

    Returns:
        True if valid, False otherwise
    """
    return token.startswith("session_")
