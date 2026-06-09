"""Nokia Altiplano NBI — Device Discovery CLI"""

import argparse
from pathlib import Path

from nokia.client import AltiplanoClient
from nokia import es_device, es_fiber, es_ont, slot_inv, pon_sfp, uplink_sfp, assemble, mapper


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(
    description="Nokia Altiplano NBI device discovery",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  p.add_argument("--server", required=True)
  p.add_argument("--username", default="adminuser")
  p.add_argument("--password", required=True)
  p.add_argument("--rel", default="nokia-altiplano", help="Altiplano release name prefix")
  p.add_argument("--no-verify-ssl", action="store_true")
  p.add_argument("--output-dir", default="output", help="Directory to save JSON output files")
  return p


def main():
  args = build_parser().parse_args()
  out = Path(args.output_dir)
  client = AltiplanoClient(
    server=args.server,
    username=args.username,
    password=args.password,
    verify_ssl=not args.no_verify_ssl,
    rel=args.rel,
  )
  print("Logging in ...")
  client.login()
  print("Login OK\n")

  devices = es_device.run(client, out)
  fibers = es_fiber.run(client, out, devices)
  ont_counts = es_ont.run(client, out, fibers)
  slots = slot_inv.run(client, out, devices)
  sfp = pon_sfp.run(client, out, fibers)
  uplink = uplink_sfp.run(client, out, devices)

  print()
  assemble.run(out, devices, slots, fibers, sfp, ont_counts, uplink)
  mapper.run(out, slots)


if __name__ == "__main__":
  main()
