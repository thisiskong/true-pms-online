"""Tiny async TTL cache for expensive, slowly-changing queries."""
import asyncio
import time
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


def ttl_cache(seconds: int) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
  def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    store: dict[Any, tuple[float, T]] = {}
    locks: dict[Any, asyncio.Lock] = {}

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
      key = (args, tuple(sorted(kwargs.items())))
      hit = store.get(key)
      if hit and hit[0] > time.monotonic():
        return hit[1]
      lock = locks.setdefault(key, asyncio.Lock())
      async with lock:
        hit = store.get(key)
        if hit and hit[0] > time.monotonic():
          return hit[1]
        value = await fn(*args, **kwargs)
        store[key] = (time.monotonic() + seconds, value)
        return value

    wrapper.cache_clear = store.clear  # type: ignore[attr-defined]
    return wrapper

  return deco
