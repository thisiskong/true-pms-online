"""Nokia Altiplano NBI — Device Discovery CLI"""

import argparse
import logging
from pathlib import Path

from nokia.client import AltiplanoClient
from nokia import es_device, es_fiber, slot_inv, pon_sfp, uplink_sfp, assemble, mapper


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
  p.add_argument("--debug", action="store_true", help="Enable debug logging (includes request URLs)")
  return p


def main():
  args = build_parser().parse_args()
  logging.basicConfig(
    level=logging.DEBUG if args.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
  )
  log = logging.getLogger(__name__)

  out = Path(args.output_dir)
  client = AltiplanoClient(
    server=args.server,
    username=args.username,
    password=args.password,
    verify_ssl=not args.no_verify_ssl,
    rel=args.rel,
  )
  log.info("Logging in ...")
  client.login()
  log.info("Login OK")

  devices = es_device.run(client, out)
  fibers = es_fiber.run(client, out, devices)
  # ont_counts, ont_names_by_fiber = es_ont.run(client, out, fibers)
  ont_counts, ont_names_by_fiber = {}, {}
  slots = slot_inv.run(client, out, devices)
  sfp = pon_sfp.run(client, out, fibers)
  uplink = uplink_sfp.run(client, out, devices)
  # ont_info = ac_ont.run(client, out, ont_names_by_fiber)
  ont_info = {}

  log.info("")
  assemble.run(out, devices, slots, fibers, sfp, ont_counts, uplink, ont_names_by_fiber, ont_info)
  mapper.run(out, slots)


if __name__ == "__main__":
  main()
