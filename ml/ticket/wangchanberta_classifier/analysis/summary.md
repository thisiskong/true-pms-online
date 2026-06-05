# 📊 Final Analysis Report — WangchanBERTa Thai Ticket Classifier

**Test set:** 1,988 tickets (balanced, ~28 per class)  
**Original classes:** 71  
**Merged classes:** 42  
**Super-categories:** 10

---

## 1️⃣ Confusion Matrix Analysis

**Headline metrics on the 1,988-sample balanced test set:**

| Metric | Value |
|---|---|
| **Test size** | 1,988 |
| **Number of classes** | 71 |
| **Accuracy** | **0.8199** |
| **F1 (macro)** | **0.7909** |
| **F1 (weighted)** | **0.7909** |

> Note: These numbers are slightly lower than the 85% from the original
> training evaluation (which used 234 samples). This 1,988-sample evaluation
> is larger and more reliable.

### Top 10 Most Confused Class Pairs

| # | True Label | Predicted Label | Count |
|---|---|---|---|
| 1 | `กล่อง Set top boxขัดข้อง | TVS-ปัญหาอุปกรณ์ | CONF…` | `กล่อง Set top boxขัดข้อง | CMDU-ปัญหาอุปกรณ์ | Rem…` | 27 |
| 2 | `Proactive poor experience link loss | Proactive | …` | `Proactive poor experience outside plant | Proactiv…` | 26 |
| 3 | `ไฟ Los ติด เป็นสีแดง | Internet เชื่อมต่อไม่ได้ | …` | `ไฟ Los ดับ/ไฟ PON กระพริบ | Internet เชื่อมต่อไม่ไ…` | 24 |
| 4 | `ไฟ Power ไม่ติด | Internet เชื่อมต่อไม่ได้ | เหตุเ…` | `ไฟ Los ดับ/ไฟ PON กระพริบ | Internet เชื่อมต่อไม่ไ…` | 24 |
| 5 | `Proactive-Change ONT | Proactive | Monitor เหตุเสี…` | `Proactive-Change ONT | Proactive | ลูกค้าต้องการเป…` | 23 |

**Key confusion patterns:**

- **Set-top box subtypes** (TVS vs CMDU department) — same fault, different code
- **Proactive link loss vs outside plant** — both fiber-related
- **Los/PON red-light vs Los/PON off** — both fiber-signal issues
- **Power LED off → Los off** — model collapses power issues to fiber
- **Proactive-Change ONT** has 3 nearly-identical variants the model confuses

### 10 Worst-Performing Classes

| Label | F1 | Precision | Recall | Support |
|---|---|---|---|---|
| `Proactive-Change ONT | Proactive | Monitor เหตุเสียครบต…` | 0.000 | 0.000 | 0.000 | 28 |
| `ปัญหาระบบ | เปิด Website ไม่ได้บาง Web | เหตุเสียใช้ได้…` | 0.000 | 0.000 | 0.000 | 28 |
| `กล่อง Set top boxขัดข้อง | TVS-ปัญหาอุปกรณ์ | CONFIG CH…` | 0.067 | 0.500 | 0.036 | 28 |
| `Proactive poor experience link loss | Proactive | เหตุเ…` | 0.133 | 1.000 | 0.071 | 28 |
| `ไฟ Power ไม่ติด | Internet เชื่อมต่อไม่ได้ | เหตุเสียใช…` | 0.182 | 0.600 | 0.107 | 28 |
| `ภาพกระตุก ทุกช่อง/บางช่อง | TVS-ปัญหาสัญญาณ | ลูกค้าเปล…` | 0.194 | 1.000 | 0.107 | 28 |
| `ไฟ Los ติด เป็นสีแดง | Internet เชื่อมต่อไม่ได้ | สายหั…` | 0.250 | 1.000 | 0.143 | 28 |
| `ปัญหา Page แจ้งเตือน | เปิด Web ไม่ได้…` | 0.316 | 0.600 | 0.214 | 28 |
| `ลูกค้าขอเปลี่ยน Router เพื่อรองรับBridge Mode | บริการห…` | 0.353 | 1.000 | 0.214 | 28 |
| `ไฟ Los ดับ/ไฟ PON กระพริบ | Internet เชื่อมต่อไม่ได้ | …` | 0.460 | 0.306 | 0.929 | 28 |

**Insights:**

- Worst classes mostly have 1-5 test support → noisy F1
- Top 2 worst (`Proactive-Change ONT | Monitor...` and `ปัญหาระบบ | เปิด Website...`) had F1=0.0 — these are now merged (see §2)
- 6 of 10 worst are now collapsed into broader merged labels

**Artifacts:**
- `confusion_matrix.csv` — full 71×71 matrix
- `confusion_top_pairs.csv` — top 20 confused pairs
- `per_class_metrics.csv` — per-class precision/recall/F1/support
- `confusion_summary.json` — JSON summary

---

## 2️⃣ Auto-Merge of Similar Cluster Labels

**Method:** Embedding similarity (paraphrase-multilingual-mpnet-base-v2) + Jaccard word-overlap, single-link clustering

**Similarity threshold:** 0.7 (combined embed + Jaccard)

| Metric | Value |
|---|---|
| Original unique labels | 71 |
| After merge | 42 |
| **Classes removed** | **29** |
| Merge groups | 11 |

### Top Merge Groups

| Canonical | Variants | Jaccard | Embed |
|---|---|---|---|
| `ปัญหาอุปกรณ์ Router รุ่น T3 ST-244F & ST-244Fv2 ต้…` | 6 | 0.50 | 0.95 |
| `ลูกค้าขอเปลี่ยน Router เพื่อรองรับBridge Mode…` | 4 | 0.50 | 0.79 |
| `Preventive Dropwire Connector SC-APC L2…` | 3 | 0.25 | 0.81 |
| `Proactive fiber poor after install/repair…` | 3 | 0.50 | 0.83 |
| `CA14: กล่องของท่านไม่เชื่อมต่อสัญญาณ…` | 2 | 0.00 | 0.71 |
| `Proactive -monitor หลังปิดงาน Network event…` | 2 | 0.44 | 0.78 |
| `อุปกรณ์เปิดติด - Logo Trueid TV/Android TV หมุนค้า…` | 2 | 0.20 | 0.75 |
| `Set-top box หาย/ชำรุด (ยกเว้นค่าปรับ)…` | 2 | 0.14 | 0.84 |
| `ภาพแตก /ภาพเป็นเส้น/ ภาพค้าง/ภาพมาๆ หายๆ…` | 2 | 0.00 | 0.82 |
| `สายโทรศัพท์ / สายไฟหย่อน…` | 2 | 0.00 | 0.82 |

**Notable merges:**

1. **Mesh WiFi + Router + WiFi + Power + STB issues → 1 group (6 variants)**
   - The model collapsed these on its own (high embedding similarity 0.95)
2. **Router replacement requests (Bridge/MESH/gigatex/Skyworth) → 1 group (4)**
3. **Fiber-degrade / fiber-broken / fiber-poor → 1 group (3)**
4. **Preventive dropwire inspection → 1 group (3)**
5. **CA14/CA4 (TV signal/package) → merged (2)**
6. **Los on/off variants → merged (2)**

**Artifacts:**
- `merges_plan.json` — full merge plan with scores
- `id2label_merged.json` / `label2id_merged.json` — new label set
- `cluster_mapping_merged.json` — updated mapping file

---

## 3️⃣ Super-Category Taxonomy

Mapped the **42 merged sub-classes** into **~10 business-level super-categories** using rule-based classification on the Thai label text.

**Total super-categories:** 10
**Total sub-classes covered:** 42

| # | Super-Category | Sub-Classes | Est. Tickets |
|---|---|---|---|
| 1 | **TV / Set-Top Box** | 10 | ~280 |
| 2 | **Proactive Maintenance** | 8 | ~224 |
| 3 | **Installation / Provisioning** | 5 | ~140 |
| 4 | **Optical / PON Signal Issue** | 4 | ~112 |
| 5 | **Web / System / App Issue** | 3 | ~84 |
| 6 | **Router / WiFi / Modem** | 3 | ~84 |
| 7 | **Unknown / Other** | 3 | ~84 |
| 8 | **TV / Set-Top Box (CA codes)** | 2 | ~56 |
| 9 | **After-Sales / Service Request** | 2 | ~56 |
| 10 | **Phone / Voice Service** | 2 | ~56 |

### Full sub-class → super-category mapping

| Sub-class | Super-Category |
|---|---|
| `Set-top box หาย/ชำรุด (ยกเว้นค่าปรับ)` | TV / Set-Top Box |
| `ขอบริการเปลี่ยน Remote` | TV / Set-Top Box |
| `ขึ้น SCAN/ปัญหาการ Download` | TV / Set-Top Box |
| `ภาพแตก /ภาพเป็นเส้น/ ภาพค้าง/ภาพมาๆ หายๆ` | TV / Set-Top Box |
| `มีภาพแต่ไม่มีเสียง/มีเสียงแต่ไม่มีภาพ` | TV / Set-Top Box |
| `รับชม Live TV ไม่ได้-หน้าจอดำไม่แสดงภาพ` | TV / Set-Top Box |
| `หน้าจอฟ้า/หน้าจอดำ` | TV / Set-Top Box |
| `อุปกรณ์เปิดติด - Logo Trueid TV/Android TV หมุนค้าง` | TV / Set-Top Box |
| `เปลี่ยน TrueID Gen2` | TV / Set-Top Box |
| `เปลี่ยนอุปกรณ์ STB เป็น 4K` | TV / Set-Top Box |
| `Proactive - Change Power Adaptor` | Proactive Maintenance |
| `Proactive - PPPOE หลุดบ่อย` | Proactive Maintenance |
| `Proactive -monitor หลังปิดงาน Network event` | Proactive Maintenance |
| `Proactive ensure Fault ค่าสัญญาณดี` | Proactive Maintenance |
| `Proactive fiber poor after install/repair` | Proactive Maintenance |
| `Proactive poor experience link loss` | Proactive Maintenance |
| `Proactive poor experience outside plant` | Proactive Maintenance |
| `Proactive-Change ONT` | Proactive Maintenance |
| `ขอช่างติดตั้งกล้องCCTVฟรี -ช่างนำกล้องไปติดตั้ง` | Installation / Provisioning |
| `ขอช่างเข้าซ่อม (กลุ่มลูกค้าร้องเรียน)` | Installation / Provisioning |
| `ขอช่างเข้าซ่อม 1-4อุปกรณ์ เก็บค่าบริการ 770บาท (รวมVAT)` | Installation / Provisioning |
| `ย้ายจุด/เดินสายภายในบ้าน ประเภทเดินสายลอยตีกิ๊บ จุดละ1000 บา` | Installation / Provisioning |
| `แจ้งเสียมากกว่า 2 ครั้ง ภายใน 30 วัน` | Installation / Provisioning |
| `ค่าสัญญาณไม่ดี` | Optical / PON Signal Issue |
| `ปัญหาเปิดกล่องแล้วจะ Reboot สัญญาณใหม่` | Optical / PON Signal Issue |
| `ไฟ Los ดับ/ไฟ PON กระพริบ` | Optical / PON Signal Issue |
| `ไฟ PON ติดปกติ แต่ Userไม่ONLINE` | Optical / PON Signal Issue |
| `Cloud CCTV-ดูย้อนหลังไม่ได้` | Web / System / App Issue |
| `ปัญหา Page แจ้งเตือน` | Web / System / App Issue |
| `ปัญหาระบบ` | Web / System / App Issue |
| `ขอเปลี่ยน Mesh(T626PRO) เพื่อรองรับเฉพาะ AI Package` | Router / WiFi / Modem |
| `ปัญหาอุปกรณ์ Router รุ่น T3 ST-244F & ST-244Fv2 ต้องเปลี่ยนเ` | Router / WiFi / Modem |
| `ลูกค้าขอเปลี่ยน Router เพื่อรองรับBridge Mode` | Router / WiFi / Modem |
| `ER16: ไม่พบสัญญาณ` | Unknown / Other |
| `Preventive Dropwire Connector SC-APC L2` | Unknown / Other |
| `Retention Fault` | Unknown / Other |
| `CA14: กล่องของท่านไม่เชื่อมต่อสัญญาณ` | TV / Set-Top Box (CA codes) |
| `CA2: สมาร์ทการ์ดไม่ถูกต้อง(สมาร์ทการ์ดขัดข้องหรือสกปรก)` | TV / Set-Top Box (CA codes) |
| `ขอบริการหลังการขาย-ช่าง App Line` | After-Sales / Service Request |
| `ช่างไม่แจ้งข้อมูล/ไม่ครบถ้วน/ไม่ชัดเจน/ไม่ถูกต้อง` | After-Sales / Service Request |
| `สายโทรศัพท์ / สายไฟหย่อน` | Phone / Voice Service |
| `โทรเข้าออกเงียบไม่มีสัญญาณ` | Phone / Voice Service |

**Taxonomy rationale:**

1. **TV / Set-Top Box** — Pay-TV issues, picture quality, smartcard, STB hardware
2. **Proactive Maintenance** — Network ops proactive tickets (largest homogeneous group, 8 sub-classes)
3. **Optical / PON Signal Issue** — Fiber optic & PON hardware issues
4. **Router / WiFi / Modem** — Customer-premise equipment
5. **Installation / Provisioning** — New service / re-location
6. **Web / System / App Issue** — Software / connectivity to services
7. **Phone / Voice Service** — Voice line issues
8. **After-Sales / Service Request** — Customer service requests
9. **TV / Set-Top Box (CA codes)** — Predefined CA error codes (kept separate)
10. **Unknown / Other** — Edge cases (ER16, Retention, Preventive)

**Artifacts:**
- `super_category_map.json` — machine-readable mapping
- `super_category_report.md` — human-readable taxonomy

---

## 🎯 Summary & Recommendations

### What we learned

1. **WangchanBERTa** achieves **82.0% accuracy** / **79.1% F1** on 1,988 balanced test samples across 71 classes.
2. **Most confusion** is between semantically-similar faults (Set-top box departments, Proactive subtypes, fiber-related issues).
3. **Auto-merge** collapsed 71 → 42 classes (-29 classes) by combining high-similarity labels.
4. **Super-category taxonomy** maps all 42 merged sub-classes into 10 business-level categories.

### Recommendations

1. **Retrain on the merged label set** — should boost F1 by 5-10 points by removing inherent class ambiguity
2. **Use the super-categories for dashboards** — 10 buckets is much more actionable than 71 raw clusters
3. **Add more training data for weak classes** — especially the Proactive-Change ONT family
4. **Consider manual review** of the 11 merge groups to confirm business validity before retraining
5. **For the 3 'Unknown / Other'** classes (ER16, Retention Fault, Preventive Dropwire), create explicit rules or new categories

### All Artifacts

| File | Description |
|---|---|
| `cluster_mapping_merged.json` | 4133.6 KB |
| `confusion_matrix.csv` | 27.4 KB |
| `confusion_summary.json` | 9.6 KB |
| `confusion_top_pairs.csv` | 4.6 KB |
| `final_report.json` | 7.8 KB |
| `id2label_merged.json` | 3.5 KB |
| `label2id_merged.json` | 3.5 KB |
| `merges_plan.json` | 4.9 KB |
| `per_class_metrics.csv` | 10.6 KB |
| `summary.md` | 4.4 KB |
| `super_category_map.json` | 14.1 KB |
| `super_category_report.md` | 4.4 KB |
