"""Static guard: no write/DDL SQL anywhere in the application code."""
import re
from pathlib import Path

WRITE_SQL = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+(TABLE|INDEX|VIEW|SCHEMA|DATABASE)|ALTER\s+TABLE|CREATE\s+(TABLE|INDEX|VIEW|SCHEMA)|TRUNCATE\s|GRANT\s|COPY\s+\w+\s+FROM)", re.I)


def test_no_write_sql_in_app():
  root = Path(__file__).resolve().parents[1] / "app"
  hits = []
  for f in root.rglob("*.py"):
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
      if WRITE_SQL.search(line):
        hits.append(f"{f.relative_to(root)}:{n}: {line.strip()}")
  assert not hits, "write SQL found:\n" + "\n".join(hits)
