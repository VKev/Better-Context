"""Data models for the python-simple fixture.

This module has no internal dependencies - it's a leaf node.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """A user in the system."""

    name: str
    email: str
    id: Optional[int] = None


@dataclass
class Product:
    """A product in the catalog."""

    name: str
    price: float
    sku: Optional[str] = None


@dataclass
class Order:
    """An order combining user and products."""

    user: User
    products: list
    total: float = 0.0
