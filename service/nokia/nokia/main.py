"""Nokia Altiplano NBI — Authentication CLI"""

import argparse
import json
import sys

import requests


def login(server: str, username: str, password: str, verify_ssl: bool = True) -> dict:
  url = f"https://{server}/nokia-altiplano-ac/rest/auth/login"
  resp = requests.post(
    url,
    auth=(username, password),
    verify=verify_ssl,
    timeout=30,
  )
  resp.raise_for_status()
  return resp.json()


def refresh(server: str, refresh_token: str, verify_ssl: bool = True) -> dict:
  url = f"https://{server}/nokia-altiplano-ac/rest/auth/refreshAccessToken"
  resp = requests.post(
    url,
    headers={
      "Content-Type": "application/json",
      "Authorization": f"Bearer {refresh_token}",
    },
    verify=verify_ssl,
    timeout=30,
  )
  resp.raise_for_status()
  return resp.json()


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Nokia Altiplano NBI authentication",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  parser.add_argument("--server", required=True, help="Altiplano server IP or hostname")
  parser.add_argument("--username", default="adminuser", help="Login username")
  parser.add_argument("--password", required=True, help="Login password")
  parser.add_argument(
    "--no-verify-ssl",
    action="store_true",
    help="Disable TLS certificate verification (use for self-signed certs)",
  )
  parser.add_argument(
    "--refresh-token",
    metavar="TOKEN",
    help="Refresh an existing access token instead of logging in",
  )
  parser.add_argument(
    "--output",
    choices=["json", "token"],
    default="token",
    help="Output format: 'token' prints only the access token, 'json' prints full response",
  )
  return parser


def main():
  parser = build_parser()
  args = parser.parse_args()
  verify_ssl = not args.no_verify_ssl

  try:
    if args.refresh_token:
      data = refresh(args.server, args.refresh_token, verify_ssl=verify_ssl)
    else:
      data = login(args.server, args.username, args.password, verify_ssl=verify_ssl)
  except requests.exceptions.HTTPError as e:
    print(f"HTTP error: {e.response.status_code} {e.response.text}", file=sys.stderr)
    sys.exit(1)
  except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}", file=sys.stderr)
    sys.exit(1)

  if args.output == "json":
    print(json.dumps(data, indent=2))
  else:
    token = data.get("accessToken") or data.get("access_token")
    if not token:
      print(f"No access token in response: {data}", file=sys.stderr)
      sys.exit(1)
    print(token)


if __name__ == "__main__":
  main()
