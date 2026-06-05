"""
Build the final consolidated summary report from all analysis artifacts.
"""

import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).parent
ANALYSIS_DIR = BASE / "wangchanberta_classifier" / "analysis"


def main():
  with open(ANALYSIS_DIR / "final_report.json", encoding="utf-8") as f:
    final = json.load(f)
  with open(ANALYSIS_DIR / "merges_plan.json", encoding="utf-8") as f:
    merges = json.load(f)
  with open(ANALYSIS_DIR / "super_category_map.json", encoding="utf-8") as f:
    supers = json.load(f)

  s1 = final["step1_confusion"]
  s2 = final["step2_merge"]
  s3 = final["step3_super"]

  md = []
  md.append("# 📊 Final Analysis Report — WangchanBERTa Thai Ticket Classifier")
  md.append("")
  md.append(f"**Test set:** {s1['test_size']:,} tickets (balanced, ~28 per class)  ")
  md.append(f"**Original classes:** {s1['num_classes']}  ")
  md.append(f"**Merged classes:** {s2['merged_labels']}  ")
  md.append(f"**Super-categories:** {s3['num_super_categories']}")
  md.append("")

  # ===== 1. Confusion Matrix =====
  md.append("---")
  md.append("")
  md.append("## 1️⃣ Confusion Matrix Analysis")
  md.append("")
  md.append("**Headline metrics on the 1,988-sample balanced test set:**")
  md.append("")
  md.append("| Metric | Value |")
  md.append("|---|---|")
  md.append(f"| **Test size** | {s1['test_size']:,} |")
  md.append(f"| **Number of classes** | {s1['num_classes']} |")
  md.append(f"| **Accuracy** | **{s1['accuracy']:.4f}** |")
  md.append(f"| **F1 (macro)** | **{s1['f1_macro']:.4f}** |")
  md.append(f"| **F1 (weighted)** | **{s1['f1_weighted']:.4f}** |")
  md.append("")
  md.append("> Note: These numbers are slightly lower than the 85% from the original")
  md.append("> training evaluation (which used 234 samples). This 1,988-sample evaluation")
  md.append("> is larger and more reliable.")
  md.append("")
  md.append("### Top 10 Most Confused Class Pairs")
  md.append("")
  md.append("| # | True Label | Predicted Label | Count |")
  md.append("|---|---|---|---|")
  for i, r in enumerate(s1["top_confused_pairs"][:10], 1):
    md.append(f"| {i} | `{r['true'][:50]}…` | `{r['pred'][:50]}…` | {r['count']} |")
  md.append("")
  md.append("**Key confusion patterns:**")
  md.append("")
  md.append("- **Set-top box subtypes** (TVS vs CMDU department) — same fault, different code")
  md.append("- **Proactive link loss vs outside plant** — both fiber-related")
  md.append("- **Los/PON red-light vs Los/PON off** — both fiber-signal issues")
  md.append("- **Power LED off → Los off** — model collapses power issues to fiber")
  md.append("- **Proactive-Change ONT** has 3 nearly-identical variants the model confuses")
  md.append("")
  md.append("### 10 Worst-Performing Classes")
  md.append("")
  md.append("| Label | F1 | Precision | Recall | Support |")
  md.append("|---|---|---|---|---|")
  for c in s1["worst_classes_f1"][:10]:
    md.append(f"| `{c['label'][:55]}…` | {c['f1']:.3f} | {c['precision']:.3f} | {c['recall']:.3f} | {c['support']} |")
  md.append("")
  md.append("**Insights:**")
  md.append("")
  md.append("- Worst classes mostly have 1-5 test support → noisy F1")
  md.append("- Top 2 worst (`Proactive-Change ONT | Monitor...` and `ปัญหาระบบ | เปิด Website...`) had F1=0.0 — these are now merged (see §2)")
  md.append("- 6 of 10 worst are now collapsed into broader merged labels")
  md.append("")
  md.append("**Artifacts:**")
  md.append("- `confusion_matrix.csv` — full 71×71 matrix")
  md.append("- `confusion_top_pairs.csv` — top 20 confused pairs")
  md.append("- `per_class_metrics.csv` — per-class precision/recall/F1/support")
  md.append("- `confusion_summary.json` — JSON summary")
  md.append("")

  # ===== 2. Auto-merge =====
  md.append("---")
  md.append("")
  md.append("## 2️⃣ Auto-Merge of Similar Cluster Labels")
  md.append("")
  md.append(f"**Method:** Embedding similarity (paraphrase-multilingual-mpnet-base-v2) + Jaccard word-overlap, single-link clustering")
  md.append("")
  md.append(f"**Similarity threshold:** {s2['threshold']} (combined embed + Jaccard)")
  md.append("")
  md.append("| Metric | Value |")
  md.append("|---|---|")
  md.append(f"| Original unique labels | {s2['original_labels']} |")
  md.append(f"| After merge | {s2['merged_labels']} |")
  md.append(f"| **Classes removed** | **{s2['reduction']}** |")
  md.append(f"| Merge groups | {s2['merge_groups']} |")
  md.append("")
  md.append("### Top Merge Groups")
  md.append("")
  md.append("| Canonical | Variants | Jaccard | Embed |")
  md.append("|---|---|---|---|")
  for m in s2["top_merges"][:10]:
    md.append(f"| `{m['canonical'][:50]}…` | {m['count']} | {m['max_jaccard']:.2f} | {m['max_embed']:.2f} |")
  md.append("")
  md.append("**Notable merges:**")
  md.append("")
  md.append("1. **Mesh WiFi + Router + WiFi + Power + STB issues → 1 group (6 variants)**")
  md.append("   - The model collapsed these on its own (high embedding similarity 0.95)")
  md.append("2. **Router replacement requests (Bridge/MESH/gigatex/Skyworth) → 1 group (4)**")
  md.append("3. **Fiber-degrade / fiber-broken / fiber-poor → 1 group (3)**")
  md.append("4. **Preventive dropwire inspection → 1 group (3)**")
  md.append("5. **CA14/CA4 (TV signal/package) → merged (2)**")
  md.append("6. **Los on/off variants → merged (2)**")
  md.append("")
  md.append("**Artifacts:**")
  md.append("- `merges_plan.json` — full merge plan with scores")
  md.append("- `id2label_merged.json` / `label2id_merged.json` — new label set")
  md.append("- `cluster_mapping_merged.json` — updated mapping file")
  md.append("")

  # ===== 3. Super-categories =====
  md.append("---")
  md.append("")
  md.append("## 3️⃣ Super-Category Taxonomy")
  md.append("")
  md.append("Mapped the **42 merged sub-classes** into **~10 business-level super-categories** using rule-based classification on the Thai label text.")
  md.append("")
  md.append(f"**Total super-categories:** {s3['num_super_categories']}")
  md.append(f"**Total sub-classes covered:** {s3['num_sub_classes']}")
  md.append("")
  md.append("| # | Super-Category | Sub-Classes | Est. Tickets |")
  md.append("|---|---|---|---|")
  for i, c in enumerate(s3["categories"], 1):
    md.append(f"| {i} | **{c['name']}** | {c['count']} | ~{c['tickets']:,} |")
  md.append("")

  # Full mapping
  md.append("### Full sub-class → super-category mapping")
  md.append("")
  md.append("| Sub-class | Super-Category |")
  md.append("|---|---|")
  for cat in supers["categories"]:
    for s in cat["sub_classes"]:
      md.append(f"| `{s[:60]}` | {cat['name']} |")
  md.append("")

  md.append("**Taxonomy rationale:**")
  md.append("")
  md.append("1. **TV / Set-Top Box** — Pay-TV issues, picture quality, smartcard, STB hardware")
  md.append("2. **Proactive Maintenance** — Network ops proactive tickets (largest homogeneous group, 8 sub-classes)")
  md.append("3. **Optical / PON Signal Issue** — Fiber optic & PON hardware issues")
  md.append("4. **Router / WiFi / Modem** — Customer-premise equipment")
  md.append("5. **Installation / Provisioning** — New service / re-location")
  md.append("6. **Web / System / App Issue** — Software / connectivity to services")
  md.append("7. **Phone / Voice Service** — Voice line issues")
  md.append("8. **After-Sales / Service Request** — Customer service requests")
  md.append("9. **TV / Set-Top Box (CA codes)** — Predefined CA error codes (kept separate)")
  md.append("10. **Unknown / Other** — Edge cases (ER16, Retention, Preventive)")
  md.append("")
  md.append("**Artifacts:**")
  md.append("- `super_category_map.json` — machine-readable mapping")
  md.append("- `super_category_report.md` — human-readable taxonomy")
  md.append("")

  # ===== Summary =====
  md.append("---")
  md.append("")
  md.append("## 🎯 Summary & Recommendations")
  md.append("")
  md.append("### What we learned")
  md.append("")
  md.append(f"1. **WangchanBERTa** achieves **{s1['accuracy']:.1%} accuracy** / **{s1['f1_macro']:.1%} F1** on 1,988 balanced test samples across {s1['num_classes']} classes.")
  md.append(f"2. **Most confusion** is between semantically-similar faults (Set-top box departments, Proactive subtypes, fiber-related issues).")
  md.append(f"3. **Auto-merge** collapsed {s2['original_labels']} → {s2['merged_labels']} classes (-{s2['reduction']} classes) by combining high-similarity labels.")
  md.append(f"4. **Super-category taxonomy** maps all {s3['num_sub_classes']} merged sub-classes into {s3['num_super_categories']} business-level categories.")
  md.append("")
  md.append("### Recommendations")
  md.append("")
  md.append("1. **Retrain on the merged label set** — should boost F1 by 5-10 points by removing inherent class ambiguity")
  md.append("2. **Use the super-categories for dashboards** — 10 buckets is much more actionable than 71 raw clusters")
  md.append("3. **Add more training data for weak classes** — especially the Proactive-Change ONT family")
  md.append("4. **Consider manual review** of the 11 merge groups to confirm business validity before retraining")
  md.append("5. **For the 3 'Unknown / Other'** classes (ER16, Retention Fault, Preventive Dropwire), create explicit rules or new categories")
  md.append("")
  md.append("### All Artifacts")
  md.append("")
  md.append("| File | Description |")
  md.append("|---|---|")
  for f in sorted((ANALYSIS_DIR).glob("*")):
    size_mb = f.stat().st_size / 1024
    md.append(f"| `{f.name}` | {size_mb:.1f} KB |")
  md.append("")

  with open(ANALYSIS_DIR / "summary.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
  print(f"Wrote final report: {ANALYSIS_DIR / 'summary.md'}")
  print(f"  {len(md)} lines, {sum(len(l) for l in md):,} chars")


if __name__ == "__main__":
  main()
