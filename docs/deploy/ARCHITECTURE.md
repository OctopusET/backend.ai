# Backend.AI Deployment Architecture

## Overview

Backend.AI has two distinct operational planes with fundamentally different deployment requirements:

```
Control Plane:  manager, webserver, appproxy, storage-proxy, DB, Redis, etcd
                Stateless/stateful services. Need HA, rolling updates, health checks.
                No GPU required.

Compute Plane:  agent (one per GPU node)
                Privileged. Docker socket. GPU device access.
                Creates "compute containers" via Docker API (sibling containers).
                Overhead must be minimal.
```

Forcing both planes into a single deployment tool creates unnecessary compromise.
The control plane benefits from orchestration; the compute plane benefits from simplicity.

### GPU-optimal stack

GPU workloads need the shortest path between application and hardware.
Every intermediate layer (VM, k8s scheduler) costs performance and flexibility.

```
Runtime:      Docker + nvidia-container-toolkit (most mature GPU support)
Compute:      Bare metal agent -> Docker API -> compute containers
Deploy:       docker compose (dev) -> Helm on k8s (prod)
Orchestrate:  Backend.AI itself (that's why it exists)
```

Backend.AI agent on bare metal, creating containers via Docker API with
nvidia-container-toolkit passing GPUs through, is the optimal path.
k8s is a general-purpose orchestrator that doesn't understand GPUs;
KVM gives 1:1 GPU-to-VM only; Backend.AI is the specialized GPU scheduler.

---

## Tiered Deployment Model

Two deployment tiers. Both share the same container images,
the same `BA_*` environment variable system, and the same TOML configuration files.

```
Tier 1: Single Node     docker compose          1 node, dev/PoC
Tier 2: Kubernetes      Helm (control plane)    multi-node production
```

Users pick the tier that matches their scale. Tier 2 builds on Tier 1 --
moving from compose to k8s requires no application changes, only infrastructure.

### How other projects handle this

| Project | Tier 1 (Dev/Single) | Tier 2 (Multi-Node) | Tier 3 (k8s/Large) |
|---------|--------------------|--------------------|-------------------|
| **GitLab** | Omnibus (single package) | Reference architectures by user count | Helm chart |
| **MinIO** | SNSD (single-node single-disk) | MNMD (multi-node multi-disk) | Helm / Operator |
| **HashiCorp Vault** | Dev mode (single process) | Raft cluster (3-5 nodes) | Helm chart |
| **Keycloak** | Docker single-node | Clustered (Infinispan) | Helm / Operator |
| **Ray** | Local mode | Ray cluster (head + workers) | KubeRay Operator |
| **Prometheus** | Docker compose | Ansible + Prometheus | Prometheus Operator (CRDs) |
| **OpenStack** | Standalone (all-in-one) | Kayobe / TripleO (Ansible) | N/A (is the platform) |

The pattern is universal: single-node simplicity, then a k8s scaling path. We deliberately
collapse the middle "config management for bare-metal multi-node" stage -- compose covers
dev/single-node, and k8s/Helm covers multi-node production directly. No major project forces
k8s for small deployments, which is why Tier 1 stays compose-only.

### Backend.AI historical deployment

Backend.AI's current upstream installer is a **Textual TUI** (`src/ai/backend/install/`)
that drives source/package installs, with **systemd** units for production
(`backendai-{manager,agent,storage-proxy,webserver,watcher}.service`). Earlier
versions used **PyInfra** (SSH-based, Python infrastructure-as-code) for the same role.

- Agents discover manager via shared etcd
- Agents self-register via heartbeats, join scaling groups
- NFS/SMB for shared virtual folders across nodes
- The installer pushes config, installs venvs, and registers systemd services per node

This works but: heavy setup, low reproducibility, manual node management.
The tiered model replaces this with containers as deployment units.

---

## Tier 1: Single Node (Docker Compose)

**Target**: Development, PoC, single-GPU-node inference

```
make setup    # one-time: DB schema, etcd config, fixtures, SSL certs
make up       # start all services
make down     # stop
make logs     # tail logs
```

Everything runs on one machine via `docker-compose.yml`:
- Infrastructure: PostgreSQL, Redis, etcd (as containers with health checks)
- Control plane: manager, webserver, appproxy-coordinator/worker, storage-proxy, graphql-gateway
- Compute plane: agent (privileged, host network, docker.sock)
- Init containers: DB migration, fixture loading, krunner extraction

Tier 1 is also the development environment. `docker-compose.yml` builds from source;
`docker-compose.prod.yml` overrides with pre-built images for production use.

### Dev vs Prod images

```
docker-compose.yml          Base: dev mode, builds from source (default)
docker-compose.prod.yml     Override: uses pre-built images from registry
```

- Dev (default): `docker compose up` -- builds from local source
- Prod: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up` -- pulls images

Both share identical service definitions (ports, volumes, env, depends_on).
Only the image source differs.

### Network model

Host networking (`network_mode: host`) for all Backend.AI services.
Required because the agent creates sibling containers via Docker socket --
these containers must reach services on the host network.
Infrastructure services (DB, Redis, etcd) use port mapping.

### Configuration

All configuration flows through `BA_*` environment variables:

```bash
# .env (loaded by docker compose)
BA_HOME=/home/user/.local/share/backendai
BA_DB_PASSWORD=develove
BA_REDIS_PORT=8110
BA_ETCD_PORT=8120
BA_ADMIN_EMAIL=admin@example.com
```

TOML configs use `${BA_VAR:-default}` syntax, expanded at load time by
`expand_env_vars_recursive()` in `common/config.py`. No config file
modifications needed between environments.

### Upstream comparison

The upstream `docker-compose.monorepo.yml` (PR #9472, closed) takes a different approach:
- 4 services only (manager, webserver, appproxy-coordinator, appproxy-worker)
- No infrastructure (assumes external DB/Redis/etcd)
- Pre-built images from registry
- Bridge networking (external network `backendai_half`)
- No init/setup automation

Our Tier 1 is a complete, self-contained environment. Upstream's compose
covers only control plane services, assumes separately managed infrastructure.

---

## Tier 2: Kubernetes (Helm Chart)

**Target**: Multi-node production -- organizations running, or willing to adopt, Kubernetes

### Why k8s for control plane

- Auto-healing, rolling updates for stateless services
- Ingress controllers, cert-manager for TLS
- PostgreSQL (CrunchyData operator), Redis (Redis operator), etcd (etcd operator)
- Prometheus + Grafana + DCGM exporter for monitoring

### Why k8s does NOT manage GPU compute

Backend.AI agent creates compute containers via Docker API. These are "sibling containers"
on the host, invisible to k8s. This is by design:

- Backend.AI provides fractional GPU (fGPU) -- k8s device plugin cannot
- Backend.AI understands GPU topology (NVLink, NVSwitch) -- k8s scheduler does not
- Backend.AI manages session lifecycle (interactive notebooks, inference) -- k8s only knows pods
- k8s `nvidia-device-plugin` allocates whole GPUs; Backend.AI slices them

### Agent as DaemonSet

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: backendai-agent
spec:
  selector:
    matchLabels:
      app: backendai-agent
  template:
    spec:
      nodeSelector:
        backendai.io/gpu: "true"       # only GPU nodes
      hostNetwork: true
      hostIPC: true
      containers:
      - name: agent
        image: "{{ .Values.agent.image }}"
        securityContext:
          privileged: true
        volumeMounts:
        - name: docker-sock
          mountPath: /var/run/docker.sock
        - name: sys
          mountPath: /sys
          readOnly: true
        envFrom:
        - configMapRef:
            name: backendai-agent-config
        - secretRef:
            name: backendai-secrets
      volumes:
      - name: docker-sock
        hostPath:
          path: /var/run/docker.sock
      - name: sys
        hostPath:
          path: /sys
```

The agent runs with `hostNetwork`, `privileged`, and docker.sock access.
It creates compute containers outside k8s. k8s only manages the agent process itself.

### Docker vs containerd on k8s nodes

k8s 1.24+ removed dockershim. Most k8s nodes run containerd only.
Backend.AI agent uses `aiodocker` (Docker API client).

Options:
1. Install Docker alongside containerd on k8s GPU nodes (simplest, works now)
2. Add containerd API support to agent (clean, significant refactor)
3. CRI-O: no advantage over containerd

For now, option 1 (Docker + containerd coexistence) is the pragmatic path.
containerd native support is a future BEP-level effort.

### Upstream context

- BEP-1028 (Kubernetes Bridge): exists as empty template, not designed yet
- BEP-1046 (Unified Service Discovery): relevant for k8s-native discovery

---

## Technology Decisions

### Container runtime

| | Docker | Podman | containerd | CRI-O |
|---|---|---|---|---|
| GPU support | nvidia-container-toolkit (most mature) | CDI (growing) | nvidia-device-plugin (k8s) | nvidia-device-plugin (k8s) |
| API | Docker API | Docker API compatible | CRI / low-level | CRI only |
| Daemon | dockerd (root) | daemonless | containerd (root) | crio (root) |
| Rootless | possible | native | possible | possible |
| Compose | docker compose | podman compose | nerdctl compose | N/A |

**Decision**: Docker now. Podman is the only viable alternative (API compatible,
so `aiodocker` code works with minimal changes). containerd/CRI-O are k8s-only.
Design new container code with Podman compatibility in mind (avoid Docker-specific quirks).

### Virtualization

| | Bare metal + Docker | KVM/QEMU | Incus (LXD fork) | Firecracker |
|---|---|---|---|---|
| GPU passthrough | nvidia-container-toolkit | VFIO (1 GPU = 1 VM) | MIG + container | none |
| Overhead | ~0% | 5-15% | ~0% (container) | ~0% |
| GPU sharing | fGPU (Backend.AI) | impossible | MIG only | N/A |

**Decision**: No VMs. GPU workloads need bare metal proximity. KVM's 1:1 GPU-to-VM
model conflicts with Backend.AI's fGPU. Incus is useful for testing (multi-node k8s
simulation) but not for production compute.

### Bare-metal config management (out of scope)

With only two tiers -- compose for single-node and k8s/Helm for multi-node --
there is no bare-metal multi-node tier to provision. Tier 1 is a single host;
Tier 2 assumes an existing Kubernetes cluster, so the operator provisions nodes
however they like (kubeadm, managed k8s, etc.). A dedicated middle tier was
evaluated (Ansible, then NixOS) and dropped. On k8s, node/app configuration is
expressed as Helm values, ConfigMaps, and Secrets, reusing the same BA_* keys.

### Workflow orchestration (not applicable)

Tools like Airflow, Kubeflow, Prefect are task/DAG schedulers ("run job A then B").
They operate at a different layer than deployment infrastructure.
Backend.AI itself is the workload scheduler for GPU compute.
Airflow could call Backend.AI API for automation, but doesn't replace any part of
the deployment stack.

---

## Configuration System

All tiers share the same configuration mechanism.

### BA_* Environment Variables

Inspired by Keycloak's `KC_*` convention. Every configurable value has a `BA_` env var.

```
BA_DB_HOST, BA_DB_PORT, BA_DB_PASSWORD, BA_DB_NAME
BA_REDIS_HOST, BA_REDIS_PORT
BA_ETCD_HOST, BA_ETCD_PORT, BA_NAMESPACE
BA_HOME                          # data directory
BA_ADVERTISED_HOST               # external-facing address
BA_MODE                          # dev or prod
BA_ADMIN_EMAIL, BA_ADMIN_PASSWORD
```

### TOML env var expansion

TOML files use `${BA_VAR:-default}` syntax:

```toml
[db]
addr = { host = "${BA_DB_HOST:-127.0.0.1}", port = "${BA_DB_PORT:-8100}" }
password = "${BA_DB_PASSWORD:-develove}"
```

Expanded at load time by `expand_env_vars_recursive()` in `common/config.py`.
`BACKEND_*` prefix supported as deprecated fallback with warning.

### BA_MODE

```
BA_MODE=dev   (default)  Auto-resolve 0.0.0.0 to local IP, relaxed validation
BA_MODE=prod             BA_ADVERTISED_HOST required, strict validation
```

### Upstream alignment

BEP-1023 (Unified Config Consolidation) proposes:
- Consolidating duplicated config classes to `common/configs/`
- Common loader system (etcd, TOML, env) with chain-of-responsibility
- Config CLI (`backend.ai config show/get/set`)

Our BA_* env system is complementary: BEP-1023 handles the loading/validation layer,
BA_* env + TOML expansion handles the "how values get into TOML" layer.

**Upstream strategy**: Propose BA_* env convention first (highest value, lowest conflict).
Compose deployment follows naturally on top.

---

## Container Images

Single set of images used across all tiers:

```
ghcr.io/lablup/backend-ai-manager:${VERSION}
ghcr.io/lablup/backend-ai-agent:${VERSION}
ghcr.io/lablup/backend-ai-webserver:${VERSION}
ghcr.io/lablup/backend-ai-appproxy-coordinator:${VERSION}
ghcr.io/lablup/backend-ai-appproxy-worker:${VERSION}
ghcr.io/lablup/backend-ai-storage-proxy:${VERSION}
```

Dev builds from source; CI/CD publishes to registry; prod pulls from registry.
The image is the deployment artifact boundary.

---

## GPU Passthrough

### Docker (Tier 1)

- Host: Docker + nvidia-container-toolkit (daemon.json runtime config)
- Agent container: `privileged: true` + `/var/run/docker.sock` + `/sys:ro`
- Compute containers: created via Docker API with `DeviceRequests`
- Agent does NOT need GPU mount itself -- only enumerates via sysfs/NVML
- Tenstorrent: `privileged` handles `/dev/tenstorrent/*` access

### Kubernetes (Tier 2)

- Agent pod: privileged + docker.sock on host
- Compute containers: still created via Docker API, outside k8s
- Host must have Docker daemon running alongside containerd

### Podman (future)

Docker API compatible. Rootless CUDA via CDI (Container Device Interface).
Current agent code (`aiodocker`) should work with Podman's Docker-compatible socket.

---

## Shared Storage

### Single node (Tier 1)

Local filesystem. `BA_HOME` defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/backendai`.

### Multi-node (Tier 2 / k8s)

Shared storage required for virtual folders (model weights, datasets, user files).

| Option | Characteristics | Best for |
|--------|----------------|----------|
| NFS | Simplest, widely supported | Small-medium clusters |
| Lustre/GPFS | High-performance parallel | Large HPC clusters |
| CephFS | Distributed, self-healing | Medium-large, no dedicated storage |
| MinIO/S3 | Object storage | Cloud-native, immutable data |

The storage-proxy service abstracts the backend; agents access vfolders through it.

---

## Development Environment

Tier 1 (compose) IS the dev environment:

```bash
git clone https://github.com/lablup/backend.ai
cd backend.ai
cp .env.example .env          # edit as needed
make setup                     # DB, etcd, fixtures
make up                        # all services from source
```

For pure source development (no containers for Backend.AI services):

```bash
scripts/install-dev.sh         # existing halfstack setup
./dev start mgr               # manager from source
./dev start ag                 # agent from source
```

Both approaches use the same TOML configs with the same `BA_*` env vars.
The only difference is whether services run in containers or as local processes.

---

## References

- [BEP-1023: Unified Config Consolidation](../../proposals/BEP-1023-unified-config-consolidation.md)
- [BEP-1028: Kubernetes Bridge](../../proposals/BEP-1028-kubernetes-bridge.md) (empty, TBD)
- [BEP-1046: Unified Service Discovery](../../proposals/BEP-1046-unified-service-discovery.md)
- [Backend.AI installer (TUI + systemd)](../../src/ai/backend/install/)
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)
- Keycloak KC_* convention: https://www.keycloak.org/server/all-config
