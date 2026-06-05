# ticket — Fault Ticket Clustering

Clusters telecom fault tickets from PostgreSQL using local embeddings (no external API).

## Pipeline

```
load_tickets.py  →  embed_cluster.py  →  export_cluster_map.py
```

### Step 1 — Load tickets from PostgreSQL

```bash
uv run python load_tickets.py
```

Reads tickets within `EXTRACT_START`…`EXTRACT_END` from the configured table and writes one JSON object per line.

Output: `tickets.jsonl`

Each record contains:
- `ticketid`, `tstamp`, `createtime`, `completetime`
- `accessid`, `faulttype`, `faultcause`, `subcategory`
- `faultstatus`, `networkdisp`, `device`, `l1name`, `l2name`

---

### Step 2 — Embed + cluster

```bash
uv run python embed_cluster.py
```

1. Extracts distinct `(faulttype, subcategory, faultcause)` combos
2. Embeds them with `paraphrase-multilingual-mpnet-base-v2` (supports Thai, downloads once to HF cache)
3. Clusters with HDBSCAN — number of clusters is auto-discovered
4. Noise points are assigned to the nearest cluster centroid
5. Each cluster is auto-labelled from its most frequent combo text

Outputs:

| File | Description |
|------|-------------|
| `cluster_mapping.json` | Every distinct combo → `cluster_id`, `cluster_label`, `cluster_size` |
| `tickets_clustered.jsonl` | All tickets with `cluster_id` and `cluster_label` fields added |

`cluster_mapping.json` entry shape:
```json
{
  "faulttype": "...",
  "subcategory": "...",
  "faultcause": "...",
  "cluster_id": 3,
  "cluster_label": "สัญญาณแสงอ่อน | ONT ออฟไลน์",
  "sample_text": "สัญญาณแสงอ่อน | ONT ออฟไลน์ | ขาดแสง",
  "cluster_size": 42
}
```

`tickets_clustered.jsonl` adds two fields to each ticket:
- `cluster_id` — integer cluster number
- `cluster_label` — auto-generated text label from the cluster's most common combo

To rename cluster labels, edit `cluster_label` values directly in `cluster_mapping.json`, then re-run `export_cluster_map.py`.

---

### Step 3 — Export to CSV for review

```bash
uv run python export_cluster_map.py
```

Joins `cluster_mapping.json` with ticket counts from `tickets.jsonl` and writes a CSV for Excel review.
---

## Step 4 — Classify full ticket data with WangchanBERTa v2

```bash
uv run python predict_wangchanberta_v2.py --input tickets.jsonl --output tickets_predicted_v2.jsonl --model-dir wangchanberta_classifier_v2 --batch-size 64
```

This reads raw tickets from `tickets.jsonl`, predicts the merged v2 label for each ticket, and writes one JSON object per line to `tickets_predicted_v2.jsonl`.

Each output ticket includes:
- `predicted_label_id`
- `predicted_label`
- `predicted_score`
- `predicted_super_category`

You can also predict a single ticket from the command line:

```bash
uv run python predict_wangchanberta_v2.py \
  --faulttype "..." \
  --subcategory "..." \
  --faultcause "..."
```
Output: `cluster_faultcode_map.csv`

Columns: `cluster_id | cluster_label | faulttype | subcategory | faultcause | ticket_count`

Sorted by `cluster_id`, then `ticket_count` descending.

---

## Configuration (`.env`)

| Key | Default | Description |
|-----|---------|-------------|
| `PG_HOST` | — | PostgreSQL host |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_DB` | — | Database name |
| `PG_USER` | — | Username |
| `PG_PASSWORD` | — | Password |
| `TABLE_TICKETS` | `ticket` | Source table |
| `EXTRACT_START` | `2024-01-01` | Start date (ISO 8601) |
| `EXTRACT_END` | `2026-06-01` | End date (ISO 8601) |
| `OUTPUT_FILE` | `tickets.jsonl` | Raw ticket output |
| `CLUSTERED_FILE` | `tickets_clustered.jsonl` | Clustered ticket output |
| `EMBED_MODEL` | `paraphrase-multilingual-mpnet-base-v2` | HuggingFace model |
| `HDBSCAN_MIN_CLUSTER_SIZE` | `5` | Minimum tickets per cluster |
| `HF_TOKEN` | — | HuggingFace token (for gated models) |
