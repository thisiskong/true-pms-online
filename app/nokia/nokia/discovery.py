"""Nokia Altiplano NBI — Device Discovery CLI"""

import argparse
import logging
from pathlib import Path

from .client import AltiplanoClient
from . import ac, ac_device, ac_fiber, pon_sfp, uplink_sfp, assemble, mapper


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(
    description="Nokia Altiplano NBI device discovery",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
  )
  p.add_argument("--server", help="Required unless --phase=normalize")
  p.add_argument("--username", default="adminuser")
  p.add_argument("--password", help="Required unless --phase=normalize")
  p.add_argument("--rel", default="nokia-altiplano", help="Altiplano release name prefix")
  p.add_argument("--no-verify-ssl", action="store_true")
  p.add_argument("--output-dir", default="output", help="Directory to save JSON output files")
  p.add_argument("--debug", action="store_true", help="Enable debug logging (includes request URLs)")
  p.add_argument("--phase", choices=["discover", "normalize", "all"], default="all",
                 help="discover: fetch + save raw/normalized only; "
                      "normalize: rebuild normalized + assemble/mapper outputs from disk, no network; "
                      "all: full pipeline (default)")
  return p


def main():
  parser = build_parser()
  args = parser.parse_args()
  logging.basicConfig(
    level=logging.DEBUG if args.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
  )
  log = logging.getLogger(__name__)

  out = Path(args.output_dir)
  needs_network = args.phase in ("discover", "all")
  if needs_network and (not args.server or not args.password):
    parser.error("--server and --password are required unless --phase=normalize")
    
  ont_counts, ont_names_by_fiber = {}, {}
  ont_info = {}

  if needs_network:
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

    log.info("Listing intents (AC) ...")
    intents = ac.list_intents(client, out)
    # intents = ac.load_intents(out)

    log.info("  intents: %d", len(intents))

    devices, slots = ac_device.run(client, out, intents)
    fibers, fiber_cfg = ac_fiber.run(client, out, devices, intents)
    sfp = pon_sfp.run(client, out, fibers, fiber_cfg)
    uplink = uplink_sfp.run(client, out, devices)
    
    # ont_counts, ont_names_by_fiber = es_ont.run(client, out, fibers)
    # ont_info = ac_ont.run(client, out, ont_names_by_fiber)

    if args.phase == "discover":
      log.info("Phase=discover complete; raw+normalized files in %s", out)
      return

  if args.phase == "normalize":
    log.info("Phase=normalize: rebuilding from disk (no network) ...")
    intents = ac.load_intents(out)
    devices, slots = ac_device.run_normalize(out, intents)
    fibers, fiber_cfg = ac_fiber.run_normalize(out, devices, intents)
    sfp = pon_sfp.run(None, out, fibers, fiber_cfg)
    uplink = uplink_sfp.run_normalize(out, devices)

  log.info("")
  assemble.run(out, devices, slots, fibers, sfp, ont_counts, uplink, ont_names_by_fiber, ont_info)
  mapper.run(out)


if __name__ == "__main__":
  main()
