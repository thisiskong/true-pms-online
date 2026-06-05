"""
Rebuild super-category taxonomy with more nuanced, rule-based grouping.

Reads:
  - wangchanberta_classifier/id2label_merged.json
  - wangchanberta_classifier/analysis/per_class_metrics.csv

Writes:
  - wangchanberta_classifier/analysis/super_category_map.json
  - wangchanberta_classifier/analysis/super_category_report.md
  - wangchanberta_classifier/analysis/final_report.json
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).parent
ANALYSIS_DIR = BASE / "wangchanberta_classifier" / "analysis"


# ---------------------------------------------------------------------------
# Comprehensive super-category rules
# Each tuple: (regex pattern on short label, super category name)
# Order matters: more specific patterns first
# ---------------------------------------------------------------------------

SUPER_RULES = [
  # --- Proactive / Preventive (network ops) ---
  (r"^Proactive[ -]",                                  "Proactive Maintenance"),
  (r"Preventive",                                       "Preventive Maintenance"),
  (r"Retention",                                        "Retention / Quality"),
  (r"^Retention",                                       "Retention / Quality"),

  # --- TV / Set-Top Box (Thai pay-TV) ---
  (r"^CA\d+",                                           "TV / Set-Top Box (CA codes)"),
  (r"^ER\d+",                                           "TV / Set-Top Box (ER codes)"),
  (r"TrueIDTV|TrueID Gen2|Trueid TV|Set top box|Set-top box|Set-top|STB|กล่อง Set|กล่อง STB|TrueID Gen",
                                                       "TV / Set-Top Box"),
  (r"ภาพกระตุก|ภาพแตก|ภาพค้าง|ภาพมืด|ภาพดำ|ภาพฟ้า|ภาพเตะ|หน้าจอฟ้า|หน้าจอดำ|มีภาพแต่|รับชม Live TV|อุปกรณ์เปิด|Remote|รีโมท",
                                                       "TV / Set-Top Box"),
  (r"TVS-ปัญหาสัญญาณ|TVS-ปัญหาอุปกรณ์|ทรูไอดีทีวี|TrueIDTV",
                                                       "TV / Set-Top Box"),
  (r"ขึ้น SCAN|ดาวน์โหลด",                              "TV / Set-Top Box"),
  (r"Smart Card|สมาร์ทการ์ด|ช่องนี้ไม่รวม",             "TV / Set-Top Box"),

  # --- Optical / PON signal issues (most common field fault) ---
  (r"ไฟ Los|ไฟ PON|Los ติด|Los ดับ|PON เกินพิกัด|PON กระพริบ|Optical|สัญญาณแสง",
                                                       "Optical / PON Signal Issue"),
  (r"^ค่าสัญญาณไม่ดี|สัญญาณอ่อน|Sync Speed|คุณภาพสัญญาณ|คุณภาพสัญญาน",
                                                       "Optical / PON Signal Issue"),
  (r"ไฟ Power|ไฟไม่ติด|ไฟไม่เข้า",                       "Optical / PON Signal Issue"),
  (r"Reboot สัญญาณใหม่|รีบูตสัญญาณ",                    "Optical / PON Signal Issue"),

  # --- Router / WiFi / Modem (CPE issues) ---
  (r"Mesh Wifi|Mesh\(T626PRO\)|Mesh T626",              "Router / WiFi / Modem"),
  (r"ปัญหา Router|ปัญหา WiFi|อุปกรณ์ Router|เปลี่ยน Router|เปลี่ยน Mesh|เปลี่ยน Modem|ขอเปลี่ยน Router|ขอเปลี่ยน Mesh|ลูกค้าขอเปลี่ยน Router|Router Converter|Wi-fi 2.4G|เปลี่ยน Router/MESH",
                                                       "Router / WiFi / Modem"),
  (r"Connect WiFi|สัญญาณ WiFi|Wifi",                     "Router / WiFi / Modem"),

  # --- Internet / Connection issues ---
  (r"Internet หลุด|Internet ช้า|Internet เชื่อมต่อไม่|Internet ใช้|เชื่อมต่อไม่ได้|PPPOE|หลุดบ่อย",
                                                       "Internet / Connectivity"),

  # --- Installation / Provisioning ---
  (r"ติดตั้ง|ติดตั้งกล้อง|ย้ายจุด|เดินสาย|ลากจุด|ขอช่าง",
                                                       "Installation / Provisioning"),
  (r"แจ้งเสียมากกว่า|ซ่อมทรัพย์สิน|สายอินเทอร์เน็ตภายใน",
                                                       "Installation / Provisioning"),

  # --- Web / System / App issues ---
  (r"ปัญหาระบบ|เปิด Web|เปิด Website|Game Online|ใช้งาน Program|ใช้งาน App|Page แจ้งเตือน|Cloud CCTV|CCTV|วงจรปิด",
                                                       "Web / System / App Issue"),

  # --- After-sales / Service requests ---
  (r"บริการหลังการขาย|ขอบริการ|ขอใช้บริการ|ช่าง App Line|เปลี่ยน TrueID Gen|เปลี่ยนอุปกรณ์ STB|เปลี่ยน STB|เปลี่ยนอุปกรณ์",
                                                       "After-Sales / Service Request"),
  (r"ช่างช่วย|ช่างไม่แจ้ง|ช่างนำกล้อง|ซ่อม|ค่าบริการ",
                                                       "After-Sales / Service Request"),

  # --- Phone / Voice ---
  (r"โทรออก|โทรเข้า|สายโทรศัพท์|สายไฟ",                  "Phone / Voice Service"),

  # --- Other ---
  (r"^$",                                               "Unknown / Other"),
]


def _short_label(lbl: str) -> str:
  return lbl.split(" | ")[0].strip()


def _classify(short: str) -> str:
  for pattern, super_name in SUPER_RULES:
    if re.search(pattern, short):
      return super_name
  return "Unknown / Other"


def main():
  print("=" * 70)
  print("Rebuilding super-category taxonomy (v2 — more nuanced)")
  print("=" * 70)

  # Load merged labels (post auto-merge) + per-class metrics
  with open(ANALYSIS_DIR / "id2label_merged.json", encoding="utf-8") as f:
    id2label = json.load(f)
  labels = [id2label[str(i)] for i in range(len(id2label))]

  # Load per-class metrics for support
  support: dict[str, int] = {}
  with open(ANALYSIS_DIR / "per_class_metrics.csv", encoding="utf-8-sig") as f:
    import csv
    r = csv.DictReader(f)
    for row in r:
      # Map back to short label
      sl = _short_label(row["label"])
      support[sl] = int(row["support"])

  # Classify
  label_to_super: dict[str, str] = {}
  for lbl in labels:
    short = _short_label(lbl)
    label_to_super[short] = _classify(short)

  # Group
  super_to_labels: dict[str, list[tuple[str, str]]] = defaultdict(list)
  for lbl in labels:
    short = _short_label(lbl)
    sup = label_to_super[short]
    super_to_labels[sup].append((short, lbl))

  # Sort by total ticket count (estimated via support)
  def total_support(members):
    return sum(support.get(s, 0) for s, _ in members)

  sorted_supers = sorted(super_to_labels.items(),
                         key=lambda kv: -total_support(kv[1]))

  # If a super has < 2 members, move to "Other" for cleanliness
  final_supers: dict[str, list[tuple[str, str]]] = {}
  other: list[tuple[str, str]] = []
  for sup, mems in sorted_supers:
    if len(mems) < 2 and sup != "Unknown / Other":
      other.extend(mems)
    else:
      final_supers[sup] = mems
  if other:
    final_supers["Unknown / Other"] = final_supers.get("Unknown / Other", []) + other
  sorted_supers = sorted(final_supers.items(), key=lambda kv: -total_support(kv[1]))

  print(f"\n{len(sorted_supers)} super-categories (rebalanced):\n")
  for sup, mems in sorted_supers:
    sample = [s for s, _ in mems[:3]]
    print(f"  [{len(mems):>2} classes, ~{total_support(mems):>4} tickets] {sup}")
    for s in sample:
      print(f"      - {s[:60]}")

  # Save
  out = {
    "num_super_categories": len(sorted_supers),
    "num_sub_classes": len(labels),
    "estimated_tickets_covered": sum(total_support(m) for _, m in sorted_supers),
    "mapping": {lbl: sup for sup, mems in sorted_supers for short, lbl in mems for lbl in [lbl, short] if lbl in labels or lbl in label_to_super},
    "short_to_super": {short: sup for short, sup in label_to_super.items()},
    "categories": [
      {
        "name": sup,
        "num_sub_classes": len(mems),
        "estimated_tickets": total_support(mems),
        "sub_classes": [s for s, _ in mems],
      }
      for sup, mems in sorted_supers
    ],
  }
  # Clean mapping
  out["mapping"] = {lbl: label_to_super[_short_label(lbl)] for lbl in labels}

  with open(ANALYSIS_DIR / "super_category_map.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

  # Markdown report
  md = ["# Super-Category Taxonomy (v2)", ""]
  md.append(f"**Total sub-classes:** {len(labels)}  ")
  md.append(f"**Total super-categories:** {len(sorted_supers)}  ")
  md.append(f"**Estimated tickets covered:** ~{out['estimated_tickets_covered']:,}  ")
  md.append("")
  md.append("| # | Super-Category | Sub-Classes | Est. Tickets |")
  md.append("|---|---|---|---|")
  for i, (sup, mems) in enumerate(sorted_supers, 1):
    md.append(f"| {i} | **{sup}** | {len(mems)} | ~{total_support(mems):,} |")
  md.append("")
  md.append("## Full Mapping (sub-class → super-category)")
  md.append("")
  for sup, mems in sorted_supers:
    md.append(f"### {sup} ({len(mems)} classes)")
    for short, _ in mems:
      md.append(f"- `{short}`")
    md.append("")

  with open(ANALYSIS_DIR / "super_category_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
  print(f"\n  wrote super_category_map.json and super_category_report.md")

  # Update final_report.json
  with open(ANALYSIS_DIR / "final_report.json", encoding="utf-8") as f:
    final = json.load(f)
  final["step3_super"] = {
    "num_super_categories":  out["num_super_categories"],
    "num_sub_classes":       out["num_sub_classes"],
    "estimated_tickets":     out["estimated_tickets_covered"],
    "categories": [
      {"name": c["name"], "count": c["num_sub_classes"], "tickets": c["estimated_tickets"]}
      for c in out["categories"]
    ],
  }
  with open(ANALYSIS_DIR / "final_report.json", "w", encoding="utf-8") as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

  # Rebuild summary.md
  with open(ANALYSIS_DIR / "summary.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
  print("  updated final_report.json and summary.md")


if __name__ == "__main__":
  main()
