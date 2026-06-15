"""Shared HTTP client and auth for Nokia Altiplano NBI."""

import json
import logging
import time
import warnings
from pathlib import Path

log = logging.getLogger(__name__)

import requests
from urllib3.exceptions import InsecureRequestWarning


class AltiplanoClient:
  def __init__(self, server: str, username: str, password: str, verify_ssl: bool = True, rel: str = "nokia-altiplano"):
    self.server = server
    self.username = username
    self.password = password
    self.verify_ssl = verify_ssl
    self.rel = rel
    self.access_token: str | None = None
    self._token_acquired_at: float = 0
    self._expires_in: int = 1800

    if not verify_ssl:
      warnings.filterwarnings("ignore", category=InsecureRequestWarning)

  def _base(self) -> str:
    return f"https://{self.server}"

  def login(self) -> None:
    url = f"{self._base()}/nokia-altiplano-ac/rest/auth/login"
    resp = requests.post(url, auth=(self.username, self.password), verify=self.verify_ssl, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    self.access_token = data["accessToken"]
    self._expires_in = data.get("expiresIn", 1800)
    self._token_acquired_at = time.time()

  def _ensure_token(self) -> None:
    if self.access_token is None or (time.time() - self._token_acquired_at) > (self._expires_in - 60):
      self.login()

  def _headers_json(self) -> dict:
    self._ensure_token()
    return {
      "Authorization": f"Bearer {self.access_token}",
      "Content-Type": "application/yang-data+json",
      "Accept": "application/yang-data+json",
    }

  def _headers_es(self) -> dict:
    self._ensure_token()
    return {
      "Authorization": f"Bearer {self.access_token}",
      "Content-Type": "application/json",
      "Accept": "application/json",
    }

  def get(self, path: str) -> dict:
    url = f"{self._base()}{path}"
    log.debug("GET %s", url)
    resp = requests.get(url, headers=self._headers_json(), verify=self.verify_ssl, timeout=60)
    resp.raise_for_status()
    return resp.json()

  def post(self, path: str, body: dict | None = None, es: bool = False) -> dict:
    url = f"{self._base()}{path}"
    log.debug("POST %s", url)
    headers = self._headers_es() if es else self._headers_json()
    resp = requests.post(url, headers=headers, json=body, verify=self.verify_ssl, timeout=60)
    resp.raise_for_status()
    return resp.json()


def save(output_dir: Path, stem: str, raw: dict, normalized: dict) -> None:
  output_dir.mkdir(parents=True, exist_ok=True)
  (output_dir / f"{stem}_raw.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
  (output_dir / f"{stem}_normalized.json").write_text(json.dumps(normalized, indent=2), encoding="utf-8")
  log.info("  saved: %s_raw.json + %s_normalized.json", stem, stem)
