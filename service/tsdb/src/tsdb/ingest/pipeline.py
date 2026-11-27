"""Stream a request body (optionally gzip) through the parser into batched storage writes."""
import time
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..config import Settings
from .parser import LineError, LineParser
from .series import SeriesCache
from .writer import Batch, CollisionError

GZIP_MAGIC = b"\x1f\x8b"


class BodyTooLarge(Exception):
  pass


@dataclass
class IngestResult:
  success: int = 0          # points written to storage
  failed: int = 0           # lines rejected
  errors: list[dict] = field(default_factory=list)


async def gunzip_if_needed(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
  """Pass plain bytes through; decompress gzip (detected by magic bytes, multi-member safe)."""
  it = chunks.__aiter__()
  first = b""
  async for c in it:
    if c:
      first = c
      break
  if not first:
    return
  if not first.startswith(GZIP_MAGIC):
    yield first
    async for c in it:
      yield c
    return

  d = zlib.decompressobj(16 + zlib.MAX_WBITS)

  async def raw():
    yield first
    async for c in it:
      yield c

  async for c in raw():
    while c:
      out = d.decompress(c)
      if out:
        yield out
      if d.eof:            # next gzip member (concatenated .gz files)
        c = d.unused_data
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
      else:
        c = b""
  tail = d.flush()
  if tail:
    yield tail


async def lines(chunks: AsyncIterator[bytes], max_bytes: int) -> AsyncIterator[str]:
  total = 0
  rest = b""
  async for c in chunks:
    total += len(c)
    if total > max_bytes:
      raise BodyTooLarge()
    buf = rest + c
    parts = buf.split(b"\n")
    rest = parts.pop()
    for p in parts:
      yield p.decode("utf-8", errors="replace")
  if rest:
    yield rest.decode("utf-8", errors="replace")


async def ingest_stream(chunks: AsyncIterator[bytes], store, s: Settings,
                        cache: SeriesCache, result: IngestResult) -> IngestResult:
  """Parse and store every line. `result` is filled in place, so the caller still has the counts
  if storage fails or the body turns out too large part-way through."""
  now_ms = int(time.time() * 1000)
  min_ms = now_ms - s.tsdb_max_retention_days * 86_400_000
  max_ms = now_ms + s.tsdb_future_tolerance_s * 1000
  batch = Batch(cache)
  parse = LineParser(min_ms, max_ms, s.tsdb_max_tags)

  def fail(lineno: int, msg: str, text: str) -> None:
    result.failed += 1
    if len(result.errors) < s.tsdb_max_errors:
      result.errors.append({"line": lineno, "error": msg, "text": text[:200]})

  lineno = 0
  async for line in lines(gunzip_if_needed(chunks), s.tsdb_max_body):
    lineno += 1
    line = line.strip()
    if not line or line.startswith("#"):
      continue
    try:
      batch.add(parse(line))
    except (LineError, CollisionError) as e:
      fail(lineno, str(e), line)
      continue
    if len(batch) >= s.tsdb_batch_rows:
      result.success += await batch.flush(store)
  result.success += await batch.flush(store)
  return result
