# Backend.AI Helm Chart (Tier 2)

Deploys the Backend.AI **control plane** as Deployments and the **agent** as a
privileged DaemonSet on GPU nodes. This is Tier 2 of the deployment model
(Tier 1 = docker-compose for dev/single-node; see `docs/deploy/ARCHITECTURE.md`).

The agent creates compute containers via the host **Docker API** (sibling
containers), not as Kubernetes pods — Kubernetes manages only the agent process,
while Backend.AI keeps full control of fractional-GPU scheduling.

## Prerequisites

- Kubernetes 1.27+ (tested with k3s) and Helm 3.
- GPU nodes with Docker + nvidia-container-toolkit on the host, labelled:
  `kubectl label node <node> backendai.io/gpu=true`
- Container images built with the `BA_*` env config support
  (`ghcr.io/lablup/backend-ai-*`); set `global.image.repository`/`tag`.

## Quick start (k3s)

```bash
helm install bai charts/backend-ai \
  --namespace backendai --create-namespace \
  --set config.mode=dev
```

Use `config.mode=dev` to auto-resolve the advertised host; for `prod` set
`config.advertisedHost=<external-host>`.

## Configuration

All configuration flows through `BA_*` environment variables (same system as
Tier 1). The chart renders them into a ConfigMap (`*-env`) and Secret, and
mounts the bundled `${BA_*}`-templated TOMLs from `files/` via a ConfigMap.

| Key | Default | Description |
|-----|---------|-------------|
| `global.image.repository` | `ghcr.io/lablup/backend-ai` | Image repo prefix |
| `global.image.tag` | `""` (→ appVersion) | Image tag |
| `config.mode` | `prod` | `BA_MODE` (dev/prod) |
| `config.advertisedHost` | `""` | `BA_ADVERTISED_HOST` (required in prod) |
| `config.db/redis/etcd.host` | `""` (→ bundled svc) | External infra host override |
| `secrets.dbPassword` | `develove` | `BA_DB_PASSWORD` |
| `secrets.adminPassword` | `changeme` | bootstrap admin password |
| `secrets.existingSecret` | `""` | use an existing Secret instead |
| `postgresql.enabled` | `true` | bundle PostgreSQL (disable for external) |
| `redis.enabled` | `true` | bundle Redis |
| `etcd.enabled` | `true` | bundle etcd |
| `agent.enabled` | `true` | deploy agent DaemonSet |
| `agent.nodeSelector` | `backendai.io/gpu: "true"` | which nodes run the agent |
| `gateway.enabled` | `false` | GraphQL Hive gateway (needs `existingConfigMap`) |
| `init.enabled` | `true` | run the bootstrap hook Job |

### External infrastructure

Disable a bundled component and point at the managed instance:

```bash
helm install bai charts/backend-ai \
  --set postgresql.enabled=false \
  --set config.db.host=my-postgres.rds.amazonaws.com \
  --set config.db.port=5432 \
  --set secrets.dbPassword=...   # or secrets.existingSecret
```

### GraphQL gateway

The Hive gateway needs a composed supergraph and a gateway config whose subgraph
URLs target the in-cluster manager Service. Create a ConfigMap and enable it:

```bash
kubectl -n backendai create configmap bai-gateway \
  --from-file=supergraph.graphql=docs/manager/graphql-reference/supergraph.graphql \
  --from-file=gateway.config.ts=configs/graphql/gateway-docker.config.ts
helm upgrade bai charts/backend-ai \
  --set gateway.enabled=true --set gateway.existingConfigMap=bai-gateway
```

> The supergraph's `@join__graph` URLs and `gateway.config.ts` `transportEntries`
> must point at `bai-backend-ai-manager:8081` (not `host.docker.internal`).

## Validate without a cluster

```bash
helm lint charts/backend-ai
helm template bai charts/backend-ai | kubectl apply --dry-run=client -f -
```

## Known limitations / TODO

- Bundled infra are single-replica StatefulSets (no HA). For production, disable
  them and use managed services or operators (CrunchyData / Redis / etcd operators).
- The init Job runs `scripts/init-manager.sh` (present in the dev image). Confirm
  the alembic config path for published images; appproxy schema + krunner setup
  are not yet wired as hooks.
- Storage backend (vfolders) is host-local; multi-node needs shared storage
  (NFS/CephFS) wired into `storage-proxy`.
