"""Step 1 of a sub-query: find the series matching the metric and tag filters."""
import re
from collections import defaultdict

from .parse import QueryError, TagFilter


class Params:
  """Collects bound query parameters and returns their `{name:Type}` placeholders."""

  def __init__(self):
    self.values: dict[str, object] = {}

  def add(self, value, ch_type: str) -> str:
    name = f"p{len(self.values)}"
    self.values[name] = value
    return f"{{{name}:{ch_type}}}"


def wildcard_to_like(pattern: str) -> str:
  escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  return escaped.replace("*", "%")


def _value_condition(f: TagFilter, p: Params) -> str | None:
  """Condition on series_tag.tag_value for a positive filter, or None if any value matches."""
  if f.type == "literal_or":
    return f"tag_value IN {p.add(f.values, 'Array(String)')}"
  if f.type == "wildcard":
    if set(f.filter) == {"*"}:
      return None
    return f"tag_value LIKE {p.add(wildcard_to_like(f.filter), 'String')}"
  if f.type == "regexp":
    try:
      re.compile(f.filter)
    except re.error as e:
      raise QueryError(f"invalid regexp {f.filter!r}: {e}") from None
    return f"match(tag_value, {p.add(f.filter, 'String')})"
  return None   # not_literal_or: only the key has to exist here; values are excluded later


def resolve_sql(database: str, metric: str, filters: list[TagFilter], explicit: bool,
                limit: int) -> tuple[str, dict]:
  p = Params()
  m = p.add(metric, "String")
  where = [f"metric = {m}"]

  by_key: dict[str, list[TagFilter]] = defaultdict(list)
  for f in filters:
    by_key[f.tagk].append(f)

  if by_key:
    row_conds = []
    for k, fs in by_key.items():
      conds = [f"tag_key = {p.add(k, 'String')}"]
      conds += [c for f in fs if (c := _value_condition(f, p)) is not None]
      row_conds.append("(" + " AND ".join(conds) + ")")
    n_keys = len(by_key)
    where.append(
      f"series_id IN (SELECT series_id FROM {database}.series_tag WHERE metric = {m} "
      f"AND ({' OR '.join(row_conds)}) GROUP BY series_id HAVING uniqExact(tag_key) = {n_keys})"
    )
    for k, fs in by_key.items():
      for f in fs:
        if f.type == "not_literal_or":
          where.append(f"NOT has({p.add(f.values, 'Array(String)')}, tags[{p.add(k, 'String')}])")
  elif explicit:
    raise QueryError("explicitTags requires at least one tag filter (every series has tags)")

  if explicit:
    where.append(f"length(tags) = {len(by_key)}")

  sql = (
    f"SELECT series_id, any(tags) AS series_tags FROM {database}.series WHERE {' AND '.join(where)} "
    f"GROUP BY series_id ORDER BY series_id LIMIT {int(limit) + 1}"
  )
  return sql, p.values
