# Ticket Clustering Report

**Date:** 2026-06-03  
**Method:** Sentence-transformer embeddings (paraphrase-multilingual-mpnet-base-v2) + HDBSCAN clustering

## Summary

| Metric | Value |
|---|---|
| Total tickets | 1,016,845 |
| Date range | 2024-01-01 to 2026-06-01 |
| Clusters found | 71 |
| Output file | tickets_clustered.jsonl |
| Mapping file | cluster_mapping.json |

## All 71 Clusters by Ticket Count

| Rank | Tickets | Cluster ID | Cluster Label |
|---|---|---|---|
| 1 | 270,725 | 19 | Proactive-Fiber broken |
| 2 | 260,420 | 63 | Los ติด ไฟแดง \| Internet ขาดหายไป |
| 3 | 80,946 | 70 | ปัญหา WiFi \| Internet ช้ามาก \| สายของลูกค้า |
| 4 | 64,874 | 32 | บริการหลังการขาย-สร้าง App Line |
| 5 | 55,091 | 69 | สัญญาณอ่อน \| Internet ขาดหายไป \| Modem แตกหัก |
| 6 | 38,061 | 41 | Proactive ensure Fault สัญญาณอ่อน \| Proactive |
| 7 | 17,883 | 61 | ปัญหาระบบ \| เปิด Website ต่างๆ Web |
| 8 | 15,261 | 1 | Cloud CCTV-ภาพย้อนหลังหาย \| IOT |
| 9 | 12,622 | 54 | ER16: พบปัญหาณ \| TVS-ปัญหาสัญญาณ |
| 10 | 11,797 | 39 | รับชม Live TV ไม่ได้-หน้าจอสนิทไม่แสดงภาพ \| TrueIDTV |
| 11 | 10,691 | 46 | ปัญหาระบบ \| ใช้งาน Program/App ไม่ได้ |
| 12 | 9,666 | 68 | ปัญหา Router \| เปิด Web ไม่ได้ \| ลูกค้าตรวจสอบ |
| 13 | 9,551 | 18 | Proactive-monitor เฝ้าติดตาม Network event |
| 14 | 9,325 | 15 | Retention Fault \| คุณภาพสัญญาณ \| Monitor |
| 15 | 8,582 | 29 | เปลี่ยน Modem หรือ Router gigatex |
| 16 | 8,582 | 53 | ปัญหา WiFi \| Internet ช้ามาก \| Connect WiFi ไม่ได้ |
| 17 | 8,566 | 66 | ไฟ Power ไม่ติด \| Internet ขาดหายไป |
| 18 | 8,557 | 21 | Proactive monitor เฝ้าติดตามภาพ \| คุณภาพสัญญาณ |
| 19 | 7,905 | 20 | ขอใช้บริการเพิ่ม 2 ปี ระยะ 30 วัน \| Internet ใช้ |
| 20 | 7,709 | 30 | บริการหลังการขาย Remote |
| 21 | 6,584 | 12 | Proactive poor experience outside plant |
| 22 | 6,483 | 13 | Proactive - PPPOE ช้ามาก |
| 23 | 6,000 | 52 | เครื่อง Set top box ตั้งค่า \| TVS-ปัญหาอุปกรณ์ \| CONFIG CHANGE |
| 24 | 5,721 | 65 | Los รับ/ส่ง PON เกินพิกัด \| Internet ขาดหายไป |
| 25 | 5,452 | 0 | Proactive poor experience link loss |
| 26 | 5,450 | 62 | สาย/ออกสัญญาณขาดหายบ้าง \| สาย/ออก |
| 27 | 4,581 | 67 | ปัญหา Router \| Internet ช้ามาก \| Ticket อีกการระบบ |
| 28 | 4,249 | 50 | อุปกรณ์ไม่ติด ภาพค้าง \| TrueIDTV-ปัญหาอุปกรณ์ |
| 29 | 3,784 | 64 | Mesh Wifi ไม่ติด \| Internet ขาดหายไป |
| 30 | 3,776 | 23 | Proactive Inspection Dropwire |
| 31 | 3,659 | 59 | ภาพแตก/ภาพค้าง/ภาพว่าง/ภาพดำ \| TVS-ปัญหาสัญญาณ |
| 32 | 3,604 | 55 | หน้าจอฟ้า/หน้าจอสนิท \| TVS-ปัญหาสัญญาณ |
| 33 | 3,552 | 25 | Proactive - Fiber degrade |
| 34 | 2,934 | 22 | Proactive-Change ONT |
| 35 | 2,827 | 43 | ซ่อมทรัพย์สิน / สายอินเทอร์เน็ตภายใน-OSP |
| 36 | 2,786 | 10 | ลากจุด/เดินสายภายในบ้าน ตีเส้นเดินสาย ชุดที่ 1000 |
| 37 | 2,349 | 45 | ปัญหา Router \| Internet ใช้ \| Wi-fi 2.4G ไม่รองรับ Speed |
| 38 | 2,267 | 57 | ไฟ PON ติดสีเขียว ที่ User ไม่ ONLINE \| Internet ขาดหายไป |
| 39 | 2,048 | 42 | ปัญหาไม่ตรงกับการตรวจ Reboot สัญญาณอ่อน \| TrueIDTV |
| 40 | 2,023 | 56 | ปัญหาระบบ \| วงจรปิดบริการ |
| 41 | 1,851 | 60 | ภาพเตะ ทุกช่อง/บางช่อง \| TVS-ปัญหาสัญญาณ |
| 42 | 1,846 | 44 | Proactive ensure Fault สัญญาณอ่อน \| Proactive \| Sync Speed |
| 43 | 1,572 | 17 | ปัญหาระบบ \| เล่น Game Online ไม่ได้ \| CONFIG CHANGE |
| 44 | 1,367 | 5 | เปลี่ยน TrueID Gen2 \| บริการหลังการขาย |
| 45 | 1,340 | 7 | ลูกค้าขอย้ายเปลี่ยน Router ต้องการรับ Bridge Mode |
| 46 | 1,285 | 47 | อุปกรณ์ไม่ติด-Logo Trueid TV/Android TV ค้างหน้าจอ \| TrueIDTV |
| 47 | 1,219 | 37 | CA2: ช่องทีวีที่ลูกค้าต้องการ \| TVS |
| 48 | 1,209 | 4 | Proactive-Change ONT \| Monitor |
| 49 | 1,189 | 24 | Proactive fiber poor after install/repair |
| 50 | 1,139 | 36 | ช่างช่วยซ่อม \| IOT |
| 51 | 635 | 16 | ช่างช่วยติดตั้งกล้อง CCTV \| บริการหลังการขาย |
| 52 | 597 | 51 | Remote Trueid TV หาย / ชำรุด \| บริการหลังการขาย |
| 53 | 539 | 35 | สร้างผลการตั้งขอบเขต/รับมอบ/จัดเจน \| หน่วยงานทีมบริการ |
| 54 | 459 | 58 | เสียงดังผิดปกติ/ไม่มีเสียง/เสียงขาดหายภาพ \| TVS |
| 55 | 419 | 38 | ปัญหา Page โหลดช้า \| เปิด Web ไม่ได้ |
| 56 | 335 | 26 | Preventive Dropwire Connector SC-APC L2 \| คุณภาพสัญญาณ |
| 57 | 323 | 11 | ปัญหาอุปกรณ์ Router รุ่น T3 ST-244F & ST-244Fv2 |
| 58 | 313 | 31 | Set-top box ซ่อม/ชำรุด \| บริการหลังการขาย |
| 59 | 278 | 40 | การออกตรวจสอบสัญญาณ \| ภายใน-ออก \| ลูกค้าตรวจสอบ |
| 60 | 260 | 49 | CA14: เครื่องของท่านไม่สามารถรับสัญญาณ \| TVS |
| 61 | 255 | 27 | Preventive Dropwire ต้นทาง \| คุณภาพสัญญาณ |
| 62 | 238 | 6 | ขอเปลี่ยน Router Converter \| บริการหลังการขาย |
| 63 | 232 | 28 | Proactive-Change ONT \| Wi-fi 2.4G ไม่รองรับ Speed |
| 64 | 214 | 48 | CA4: ต้องการให้มีการรับเนื้อหา \| TVS-ปัญหาสัญญาณ |
| 65 | 163 | 8 | เปลี่ยน Router/MESH T3 หรือ Skyworth \| บริการหลังการขาย |
| 66 | 149 | 3 | เปลี่ยนอุปกรณ์ STB รุ่น 4K \| บริการหลังการขาย |
| 67 | 131 | 33 | ใช้ SCAN/ปัญหาการ Download \| TVS-ปัญหาสัญญาณ |
| 68 | 128 | 34 | ช่างช่วยซ่อม 1-4 อุปกรณ์ ราคาคำบริการ 770 บาท \| IOT |
| 69 | 114 | 2 | Proactive - Change Power Adaptor \| คุณภาพสัญญาณ |
| 70 | 63 | 9 | เครื่อง Set top box ตั้งค่า \| CMDU-ปัญหาอุปกรณ์ \| Remote ไม่ทำงาน |
| 71 | 40 | 14 | ขอเปลี่ยน Mesh (T626PRO) สำหรับรับเฉพาะ AI Package |

## Files

| File | Description |
|---|---|
| `tickets.jsonl` | Raw ticket data from PostgreSQL |
| `cluster_mapping.json` | Combo-to-cluster mappings — edit `cluster_label` to rename |
| `tickets_clustered.jsonl` | All tickets with `cluster_id` and `cluster_label` fields added |
| `cluster_faultcode_map.csv` | Per-combo ticket counts by cluster — open in Excel to review |

## Next Steps

1. Open `cluster_mapping.json` and rename `cluster_label` values to clean English categories
2. Re-run `export_cluster_map.py` after any label edits
3. Analyse category distribution, volume trends, and resolution times
