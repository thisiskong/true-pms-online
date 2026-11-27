"""PON optic class normalisation (app/queries/optics.py); no database needed."""
import pytest

from app.queries.optics import COMBO, GPON, Optic, build_pn_table, classify, parse_moduleclass


@pytest.mark.parametrize("mc, cls, tech", [
  # every vendor spelling seen in ponport.moduleclass
  ("gpon-classbplus", "B+", GPON), ("GPON/B+", "B+", GPON), ("classbplus", "B+", GPON),
  ("GPON CLASS B+ SFP OLT", "B+", GPON), ("bPlusI", "B+", GPON), ("gponepon-classbPlusAndPx20Plus", "B+", GPON),
  ("classcplus (C+)", "C+", GPON), ("gpon-classcplus", "C+", GPON), ("GPON/C+", "C+", GPON), ("GPON/EC+", "C+", GPON),
  ("gpon-classcplusplus", "C++", GPON), ("classcplusplus", "C++", GPON), ("GPON/C++", "C++", GPON),
  ("Class D", "D", GPON), ("GPON/D", "D", GPON),
  ("GPON&XGS-PON_COMBO/MPM_C+/EC++C+", "C+", COMBO), ("GPON&XGS-PON_COMBO/EC++C+", "C+", COMBO),
  ("GPON&XGS-PON_COMBO/MPM_C+", "C+", COMBO), ("GPON&XGS-PON_COMBO/MPM_D", "D", COMBO),
  ("GPON&XGS-PON_COMBO/MPM_B+", "B+", COMBO), ("XGS-PON&GPON_COMBO/D-D", "D", COMBO),
  ("gponandxgspon-invalid", None, COMBO), ("GPON/XGS-PON (combo)", None, COMBO),
  ("gpon-unknown", None, GPON), ("absent", "absent", None),
  (None, None, None), ("", None, None), ("N/A", None, None), ("invalid-invalid", None, None), ("Unknown", None, None),
  ("0", None, None), ("54", None, None), ("10Gbase-SR", None, None), ("BASE-PX", None, None),
])
def test_parse_moduleclass(mc, cls, tech):
  o = parse_moduleclass(mc)
  assert (o.cls, o.tech) == (cls, tech)
  assert o.source == ("moduleclass" if cls else None)


def test_vendorpn_fills_missing_class_by_majority():
  table = build_pn_table([
    ("gpon-classbplus", "PTB38J0-6538E-SC", 47903), ("classcplus (C+)", "PTB38J0-6538E-SC", 341),
    ("GPON&XGS-PON_COMBO/MPM_C+/EC++C+", "Z04042000-Q318", 10),
    ("N/A", "SPS4348HHPCDEDM2", 5), ("GPON/B+", "SPS4348HHPCDEDM2", 31),
  ])
  assert table == {"PTB38J0-6538E-SC": ("B+", GPON), "Z04042000-Q318": ("C+", COMBO), "SPS4348HHPCDEDM2": ("B+", GPON)}
  assert classify(None, "SPS4348HHPCDEDM2", table) == Optic("B+", GPON, "vendorpn")
  assert classify("invalid-invalid", " sps4348hhpcdedm2 ", table) == Optic("B+", GPON, "vendorpn")
  # moduleclass wins over the table, even against the majority
  assert classify("classcplus (C+)", "PTB38J0-6538E-SC", table) == Optic("C+", GPON, "moduleclass")
  # a combo port is not given a plain-GPON part's class
  assert classify("gponandxgspon-invalid", "PTB38J0-6538E-SC", table) == Optic(None, COMBO, None)
  assert classify("gponandxgspon-invalid", "Z04042000-Q318", table) == Optic("C+", COMBO, "vendorpn")
  # no optic stays "absent", unknown part stays unknown
  assert classify("absent", "PTB38J0-6538E-SC", table).cls == "absent"
  assert classify(None, "NOPE", table) == Optic(None, None, None)
