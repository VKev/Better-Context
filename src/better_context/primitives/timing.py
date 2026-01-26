from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")


@dataclass
class Timing:
    elapsed_ms: float = 0.0


def measure(func: Callable[..., T], *args, **kwargs) -> tuple[T, Timing]:
    start = perf_counter()
    result = func(*args, **kwargs)
    elapsed_ms = (perf_counter() - start) * 1000
    return result, Timing(elapsed_ms=elapsed_ms)


@contextmanager
def timer() -> Iterator[Timing]:
    start = perf_counter()
    timing = Timing()
    try:
        yield timing
    finally:
        timing.elapsed_ms = (perf_counter() - start) * 1000
