"""Request models for POST /api/query (OpenTSDB-compatible subset; unknown fields are ignored)."""
from pydantic import BaseModel, ConfigDict, Field


class FilterIn(BaseModel):
  model_config = ConfigDict(extra="ignore")
  type: str
  tagk: str
  filter: str
  groupBy: bool = False


class SubQueryIn(BaseModel):
  model_config = ConfigDict(extra="ignore")
  metric: str
  aggregator: str
  downsample: str | None = None
  tags: dict[str, str] = Field(default_factory=dict)
  filters: list[FilterIn] = Field(default_factory=list)
  explicitTags: bool = False
  rate: bool = False
  rateOptions: dict | None = None


class QueryIn(BaseModel):
  model_config = ConfigDict(extra="ignore")
  start: int | float | str
  end: int | float | str | None = None
  queries: list[SubQueryIn] = Field(min_length=1)
  msResolution: bool = False
  arrays: bool = False
  showQuery: bool = False
  dedup: bool = True       # extension: false skips duplicate removal on very large scans
