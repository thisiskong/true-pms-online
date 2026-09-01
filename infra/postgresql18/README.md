# PostgreSQL 18 + PostGIS + TimescaleDB + pgvector (CloudNativePG)

CNPG-managed Postgres 18 cluster with PostGIS, TimescaleDB, pgvector, and
pg_stat_statements, on Longhorn storage. Kustomize-only, no GitOps — deploy manually
via `kubectl apply -k`.

Two environments, one cluster:

| Env  | Namespace              | Instances | Storage class     | Storage size | External NodePort |
|------|-------------------------|-----------|--------------------|--------------|--------------------|
| dev  | `pmsonline-dev-pg18`   | 1         | `longhorn`          | 20Gi         | 30432              |
| prod | `pmsonline-prd-pg18`   | 3 (HA)    | `longhorn-pg-ha`    | 100Gi each   | 30532              |

## 1. One-time cluster setup

Install the CloudNativePG operator (cluster-scoped — shared by both envs, not part of
this repo's kustomize tree on purpose, since it installs CRDs + cluster RBAC):

```
# Check https://github.com/cloudnative-pg/cloudnative-pg/releases for the current
# version before running — don't blindly reuse an old tag from this README.
kubectl apply --server-side -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.29/releases/cnpg-1.29.1.yaml
```

Install the `kubectl cnpg` plugin (used in the verification steps below):

```
kubectl krew install cnpg
# or download the binary directly from the same releases page
```

## 2. Build & push the image

No prebuilt image combines PG18 + PostGIS + TimescaleDB + pgvector yet, so build your own from
[`Dockerfile`](./Dockerfile):

```
docker build -t <REGISTRY>/pg18-postgis-tsdb:18 .
docker push <REGISTRY>/pg18-postgis-tsdb:18
```

Then replace `<REGISTRY_PLACEHOLDER>` with `<REGISTRY>` in:
- `overlays/dev/cluster-patch.yaml`
- `overlays/prd/cluster-patch.yaml`

If `<REGISTRY>` is a private registry, you'll also need to add
`spec.imagePullSecrets` to the `Cluster` (not configured here — add a pull secret
and reference it once you know which registry you're using).

## 3. Deploy dev

```
kubectl apply -k overlays/dev
```

The dev credentials Secret is committed as-is (`overlays/dev/secret-pmsonline-credentials.yaml`)
— the dev password is already effectively shared/public across this repo's other dev
configs (`poller/uptime/config.yaml`, `poller/snmptk/disc.yml`), so nothing extra to do.

## 4. Deploy prod

Prod's credentials Secret is **never committed**. Create it manually first:

```
kubectl create secret generic pmsonline-credentials \
  --namespace pmsonline-prd-pg18 \
  --type kubernetes.io/basic-auth \
  --from-literal=username=pmsonline \
  --from-literal=password='pmsonline#2022'
```

(Password matches this repo's existing prod convention — see `app/pgadm/run.ps1`.
See `overlays/prd/secret-pmsonline-credentials.yaml.example` for the template.)

Then:

```
kubectl apply -k overlays/prd
```

**Before first apply**, double check `overlays/prd/storageclass-longhorn-pg-ha.yaml`
against the cluster's real default `longhorn` StorageClass
(`kubectl get sc longhorn -o yaml`) — copy over any parameters (`fsType`,
`dataLocality`, etc.) so the new class differs *only* in `numberOfReplicas`.

## 5. Verification runbook

```
kubectl get pods -n cnpg-system                                    # operator healthy

kubectl get cluster -n pmsonline-dev-pg18
kubectl cnpg status pg18-pms -n pmsonline-dev-pg18
kubectl cnpg psql pg18-pms -n pmsonline-dev-pg18 -- -d pmsonline -c \
  "SELECT extname, extversion FROM pg_extension;"                  # postgis, timescaledb, vector, pg_stat_statements
kubectl cnpg psql pg18-pms -n pmsonline-dev-pg18 -- -d pmsonline -c \
  "SHOW shared_preload_libraries;"

# from OUTSIDE the cluster (e.g. from a poller VM):
psql "postgresql://pmsonline:pmsonline@<any-node-ip>:30432/pmsonline?sslmode=disable" -c "SELECT 1;"

# prod, after creating the secret and applying:
kubectl cnpg status pg18-pms -n pmsonline-prd-pg18                  # expect 1 primary + 2 replicas
kubectl get pods -n pmsonline-prd-pg18 -o wide                       # confirm spread across nodes
```

## Known gaps / deliberate omissions

- **No backups configured.** No S3/MinIO object storage is available yet, so
  `.spec.backup` is omitted entirely from `base/cluster.yaml`. **There is currently
  no automated disaster recovery for this cluster.** Once object storage exists,
  add:
  ```yaml
  spec:
    backup:
      barmanObjectStore:
        destinationPath: s3://<bucket>/pg18-prd
        s3Credentials: ...
      retentionPolicy: "30d"
  ```

- **NodePort exposes port 5432 on every node's external IP**, password-auth only —
  CNPG's default `pg_hba` doesn't restrict by source network. Once the k8s
  environment's actual network layout is confirmed, restrict access via a
  `NetworkPolicy` or an explicit `pg_hba` entry (the existing bare-VM tools connect
  from the `10.50.238.x` range per `poller/snmptk/disc.yml` — that's a reasonable
  starting point for a source-IP restriction, but confirm it still applies once
  these tools run against the k8s-hosted DB).

- **Longhorn `numberOfReplicas: 1` for prod is intentional**, not an oversight —
  CNPG's own 3-instance streaming replication already provides HA. If a node
  hosting one replica's PVC goes down, that Postgres instance's disk is
  unavailable until the node returns (no Longhorn-level redundancy backing it) —
  but the cluster as a whole stays up via the other 2 CNPG instances. Stacking
  Longhorn's own default replication on top would triple storage for no added
  safety (see plan rationale).

- **LoadBalancer swap**: if MetalLB (or similar) becomes available, change
  `overlays/*/service-external-patch.yaml`'s `spec.type` from `NodePort` to
  `LoadBalancer` and drop the `nodePort` field — that's the only change needed.

- **Migration is not automated here.** Existing tools (`poller/uptime`,
  `poller/snmptk`, `app/pgadm`) still point at bare-VM hosts (`dv01`/`db01`).
  Cutting over means updating their DSNs/config to the new NodePort host:port —
  out of scope for this infra change itself.

- **`pg_partman` was considered and deliberately excluded** — it overlaps with
  TimescaleDB's native hypertable partitioning. Easy to add later (one apt
  package in the Dockerfile + one `CREATE EXTENSION` line) if a non-hypertable
  partitioning need shows up.

- **Monitoring**: CNPG exposes Prometheus metrics on port 9187 and supports
  `spec.monitoring.enablePodMonitor: true` if prometheus-operator is present.
  Not wired up here, but `poller/uptime/config.yaml`'s existing `pushgateway_url`
  suggests Prometheus is already in play elsewhere in this environment — worth
  connecting later.

- **Dev is a single instance** — CNPG blocks node drains on single-instance
  clusters by default (would otherwise mean data loss) unless
  `nodeMaintenanceWindow.inProgress` is set. Worth remembering before routine
  node maintenance on whichever node hosts the dev pod.

- **`enableSuperuserAccess`** is left at CNPG's default (`false`) — deliberate;
  `kubectl cnpg psql` covers normal admin work without a floating superuser
  credential.
