from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_OPENROUTER_MODELS = [
  "anthropic/claude-opus-5.5",
  "anthropic/claude-sonnet-5.5",
  "anthropic/claude-haiku-5.5",
  "openai/gpt-6.2-sol",
  "google/gemini-4-carbon",
  "deepseek/deepseek-v4.1-flash-1017",
]
DEFAULT_ANTHROPIC_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

  pg_dsn: str = ""  # set PG_DSN in .env (see .env.example)
  pg_pool_min: int = 1
  pg_pool_max: int = 5
  pg_statement_timeout_ms: int = 15000

  llm_provider: str = "anthropic"  # anthropic | openrouter
  openrouter_api_key: str = ""
  openrouter_model: str = "anthropic/claude-opus-5.5"
  openrouter_base_url: str = "https://openrouter.ai/api/v1"
  # Optional proxy for OpenRouter traffic only, e.g. http://pve2:8888 or socks5://127.0.0.1:1080
  openrouter_proxy: str = ""

  anthropic_api_key: str = ""
  chat_model: str = "claude-opus-5-5"
  chat_effort: str = "medium"
  chat_fallbacks: str = "default"
  chat_max_tokens: int = 16000
  chat_max_iterations: int = 8
  chat_turn_timeout_s: int = 90
  chat_session_ttl_s: int = 7200
  # Models offered in the chat model picker (comma-separated ids for the active provider). Empty = built-in list.
  chat_models: str = ""

  mcp_tokens: str = ""
  cors_origins: str = "http://localhost:5173"

  # Fiber-score pipeline output (ml/fiber). Relative paths resolve from the backend/ directory.
  ml_out_dir: str = "../ml/out"
  ml_lake_dir: str = "../ml/lake"
  ml_duckdb_threads: int = 4

  # tsdb service (service/tsdb), proxied read-only at /tsdb/api/*. The key is sent as X-API-Key, never to the browser.
  tsdb_url: str = "http://localhost:8080"
  tsdb_api_key: str = ""
  tsdb_timeout_s: float = 30.0

  @property
  def chat_configured(self) -> bool:
    if self.llm_provider == "openrouter":
      return bool(self.openrouter_api_key)
    return bool(self.anthropic_api_key)

  @property
  def active_chat_model(self) -> str:
    return self.openrouter_model if self.llm_provider == "openrouter" else self.chat_model

  @property
  def chat_model_list(self) -> list[str]:
    """Allowed chat models, default model first."""
    ids = [m.strip() for m in self.chat_models.split(",") if m.strip()]
    if not ids:
      ids = DEFAULT_OPENROUTER_MODELS if self.llm_provider == "openrouter" else DEFAULT_ANTHROPIC_MODELS
    default = self.active_chat_model
    return [default, *[m for m in ids if m != default]]

  @property
  def mcp_token_list(self) -> list[str]:
    return [t.strip() for t in self.mcp_tokens.split(",") if t.strip()]

  @property
  def cors_origin_list(self) -> list[str]:
    return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
  return Settings()
