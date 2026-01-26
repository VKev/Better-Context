"""Base Primitive class and protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from functools import wraps
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def timed(func: Callable[..., T]) -> Callable[..., tuple[T, float]]:
    @wraps(func)
    def wrapper(*args, **kwargs) -> tuple[T, float]:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return result, elapsed_ms

    return wrapper


class PrimitiveError(Exception):
    pass


class FileNotFoundPrimitiveError(PrimitiveError):
    pass


class ParseError(PrimitiveError):
    pass

@dataclass
class Primitive:
    """Base class for all primitives."""
    
    id: str
    type: str
    name: str
    path: str
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "path": self.path,
        }

@runtime_checkable
class PrimitiveFactory(Protocol):
    """Protocol for primitive factories."""
    
    def create(self, *args, **kwargs) -> Primitive:
        ...

class BaseFactory:
    """Abstract base class for factories."""
    
    def create(self, *args, **kwargs) -> Primitive:
        raise NotImplementedError
