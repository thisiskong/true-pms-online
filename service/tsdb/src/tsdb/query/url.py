"""OpenTSDB URL query syntax for GET /api/query.

m=<aggregator>:[rate[{...}]:][<downsample>:][explicit_tags:]<metric>[{<group-by filters>}][{<other filters>}]

A filter is `tagk=value` (same rules as the JSON `tags` map) or `tagk=type(value)`, e.g.
`intf=literal_or(1|2)`, `host=wildcard(ab*)`, `ip=regexp(^10\\.)`, `ip=not_literal_or(10.0.0.1)`.
"""
import re

from .models import FilterIn, SubQueryIn
from .parse import QueryError

FUNC_RE = re.compile(r"([a-z_]+)\((.*)\)", re.S)


def _split_top(s: str, sep: str) -> list[str]:
  """Split on `sep` outside parentheses and braces (regexps may contain commas/colons)."""
  out, depth, cur = [], 0, []
  for ch in s:
    if ch in "({":
      depth += 1
    elif ch in ")}":
      depth -= 1
    if ch == sep and depth == 0:
      out.append("".join(cur))
      cur = []
    else:
      cur.append(ch)
  out.append("".join(cur))
  return out


def _filters(body: str, group_by: bool, m: str) -> tuple[dict[str, str], list[FilterIn]]:
  tags: dict[str, str] = {}
  filters: list[FilterIn] = []
  if not body.strip():
    return tags, filters
  for part in _split_top(body, ","):
    k, sep, v = part.partition("=")
    k, v = k.strip(), v.strip()
    if not sep or not k or not v:
      raise QueryError(f"invalid tag filter {part!r} in m={m!r}")
    fm = FUNC_RE.fullmatch(v)
    if fm:
      filters.append(FilterIn(type=fm.group(1), tagk=k, filter=fm.group(2), groupBy=group_by))
    elif group_by:
      tags[k] = v
    else:
      typ = "wildcard" if "*" in v else "literal_or"
      filters.append(FilterIn(type=typ, tagk=k, filter=v, groupBy=False))
  return tags, filters


def parse_m(m: str) -> SubQueryIn:
  brace = m.find("{")
  head, braces = (m, "") if brace < 0 else (m[:brace], m[brace:])
  parts = head.split(":")
  if len(parts) < 2 or not parts[0] or not parts[-1]:
    raise QueryError(f"invalid m={m!r}, expected '<aggregator>:[<downsample>:][explicit_tags:]<metric>{{...}}'")
  aggregator, metric, mods = parts[0], parts[-1], parts[1:-1]

  downsample, explicit, rate = None, False, False
  for mod in mods:
    if mod == "explicit_tags":
      explicit = True
    elif mod.startswith("rate"):
      rate = True
    elif downsample is None and "-" in mod:
      downsample = mod
    else:
      raise QueryError(f"invalid option {mod!r} in m={m!r}")

  tags: dict[str, str] = {}
  filters: list[FilterIn] = []
  if braces:
    groups = re.fullmatch(r"\{(.*?)\}(?:\{(.*)\})?", braces, re.S)
    if not groups:
      raise QueryError(f"invalid tag filters in m={m!r}")
    tags, filters = _filters(groups.group(1), True, m)
    if groups.group(2) is not None:
      _, more = _filters(groups.group(2), False, m)
      filters += more

  return SubQueryIn(metric=metric, aggregator=aggregator, downsample=downsample, tags=tags,
                    filters=filters, explicitTags=explicit, rate=rate)
