#!/usr/bin/env bash
# Initialize the manager: DB schema, fixtures, etcd config.
# Run once against a fresh halfstack.
set -euo pipefail

ALEMBIC_INI="${ALEMBIC_INI:-/app/alembic.ini}"
MANAGER_CONF="${MANAGER_CONF:-/app/manager.toml}"
FIXTURE_DIR="/app/fixtures/manager"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"
DB_ADDR="${DB_ADDR:-127.0.0.1:8100}"
DB_PASSWORD="${DB_PASSWORD:-changeme}"
REDIS_ADDR="${REDIS_ADDR:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-8110}"
ETCD_PORT="${ETCD_PORT:-8120}"
APPPROXY_SECRET="${APPPROXY_SECRET:-some_api_secret}"
STORAGE_PROXY_SECRET="${STORAGE_PROXY_SECRET:-some-secret-shared-with-manager}"
STORAGE_PROXY_ID="${STORAGE_PROXY_ID:-i-storage-proxy-local}"

echo "=== DB schema oneshot ==="
python -m ai.backend.cli mgr schema oneshot -f "$ALEMBIC_INI"

echo "=== Preparing fixtures ==="
WORK_DIR=$(mktemp -d)
python3 -c "
import json, sys, os
with open('$FIXTURE_DIR/example-users.json') as f:
    data = json.load(f)
email = os.environ['ADMIN_EMAIL']
password = os.environ['ADMIN_PASSWORD']
for u in data.get('users', []):
    if u.get('role') == 'superadmin':
        u['email'] = email
        u['password'] = password
with open('$WORK_DIR/example-users.json', 'w') as f:
    json.dump(data, f, indent=2)
print(f'  admin: {email}')
"

echo "=== Populating fixtures ==="
for f in \
    "$WORK_DIR/example-users.json" \
    "$FIXTURE_DIR/example-keypairs.json" \
    "$FIXTURE_DIR/example-set-user-main-access-keys.json" \
    "$FIXTURE_DIR/example-resource-presets.json" \
    "/app/src/ai/backend/install/fixtures/example-resource-slot-types.json" \
    "/app/src/ai/backend/install/fixtures/example-roles.json" \
; do
    echo "  -> $(basename "$f")"
    python -m ai.backend.cli mgr -f "$MANAGER_CONF" fixture populate "$f" || true
done

rm -rf "$WORK_DIR"

echo "=== Creating AppProxy database ==="
python3 -c "
import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:${DB_PASSWORD}@${DB_ADDR}/backend')
    await conn.execute('COMMIT')  # exit implicit transaction
    try:
        await conn.execute('CREATE DATABASE appproxy')
    except asyncpg.exceptions.DuplicateDatabaseError:
        pass
    try:
        await conn.execute(\"CREATE USER appproxy WITH PASSWORD '${DB_PASSWORD}'\")
    except asyncpg.exceptions.DuplicateObjectError:
        pass
    await conn.execute('GRANT ALL PRIVILEGES ON DATABASE appproxy TO appproxy')
    await conn.execute('ALTER DATABASE appproxy OWNER TO appproxy')
    await conn.close()
    print('  AppProxy database ready')

asyncio.run(main())
"

echo "=== Seeding etcd ==="
etcd_put() { python -m ai.backend.cli mgr -f "$MANAGER_CONF" etcd put "$1" "$2"; }

etcd_put config/redis/addr/host "$REDIS_ADDR"
etcd_put config/redis/addr/port "$REDIS_PORT"
etcd_put config/docker/registry/cr.backend.ai ""
etcd_put config/docker/image/auto_pull "none"

# Storage proxy config
etcd_put volumes/_default_host "${STORAGE_PROXY_ID}:volume1"
etcd_put volumes/_types/user ""
etcd_put volumes/_types/group ""
etcd_put volumes/proxies/${STORAGE_PROXY_ID}/client_api "http://127.0.0.1:6021"
etcd_put volumes/proxies/${STORAGE_PROXY_ID}/manager_api "https://127.0.0.1:6022"
etcd_put volumes/proxies/${STORAGE_PROXY_ID}/secret "$STORAGE_PROXY_SECRET"
etcd_put volumes/proxies/${STORAGE_PROXY_ID}/ssl_verify "false"

echo "=== Setting up DB resources ==="
python3 -c "
import asyncio, json, uuid
import asyncpg

DB_DSN = 'postgresql://postgres:${DB_PASSWORD}@${DB_ADDR}/backend'
APPPROXY_SECRET = '${APPPROXY_SECRET}'
STORAGE_PROXY_ID = '${STORAGE_PROXY_ID}'

async def main():
    conn = await asyncpg.connect(DB_DSN)

    # --- Scaling group ---
    await conn.execute('''
        INSERT INTO scaling_groups (name, description, is_active, is_public, driver, driver_opts, scheduler, scheduler_opts, use_host_network, wsproxy_addr, wsproxy_api_token)
        VALUES ('default', 'default', true, true, 'static', '{}', 'fifo',
            '{\"allowed_session_types\": [\"interactive\", \"batch\", \"inference\"]}',
            false, 'http://127.0.0.1:10200', \$1)
        ON CONFLICT DO NOTHING
    ''', APPPROXY_SECRET)
    await conn.execute('''
        INSERT INTO sgroups_for_domains (scaling_group, domain)
        VALUES ('default', 'default')
        ON CONFLICT DO NOTHING
    ''')
    await conn.execute('''
        INSERT INTO sgroups_for_groups (scaling_group, \"group\")
        SELECT 'default', id FROM groups WHERE name = 'default'
        ON CONFLICT DO NOTHING
    ''')

    # --- TT resource slot type ---
    await conn.execute('''
        INSERT INTO resource_slot_types (slot_name, slot_type, display_name, description, display_unit, display_icon, number_format, rank)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8)
        ON CONFLICT DO NOTHING
    ''', 'tt.device', 'count', 'Tenstorrent', 'Tenstorrent AI Accelerator', 'Device', 'tenstorrent', '{\"binary\": false, \"round_length\": 0}', 500)

    # --- Container registry (ghcr.io) ---
    reg_id = uuid.uuid4()
    await conn.execute('''
        INSERT INTO container_registries (id, url, registry_name, type, project, ssl_verify, is_global)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7)
        ON CONFLICT DO NOTHING
    ''', reg_id, 'https://ghcr.io', 'ghcr.io', 'github', 'tenstorrent/tt-metal', True, True)

    # --- Allowed docker registries ---
    await conn.execute('''
        UPDATE domains SET allowed_docker_registries = array_append(allowed_docker_registries, 'ghcr.io')
        WHERE name = 'default' AND NOT ('ghcr.io' = ANY(allowed_docker_registries))
    ''')

    # --- Allowed vfolder hosts ---
    vfhost = STORAGE_PROXY_ID + ':volume1'
    hosts = json.dumps({vfhost: ['create-vfolder', 'modify-vfolder', 'delete-vfolder', 'mount-in-session', 'upload-file', 'download-file']})
    await conn.execute('UPDATE domains SET allowed_vfolder_hosts = \$1::jsonb WHERE name = \$2', hosts, 'default')
    await conn.execute('UPDATE groups SET allowed_vfolder_hosts = \$1::jsonb WHERE name = \$2', hosts, 'default')

    # --- TT metalium compute image ---
    metalium_labels = json.dumps({
        'ai.backend.kernelspec': '1',
        'ai.backend.features': 'uid-match',
        'ai.backend.base-distro': 'ubuntu22.04',
        'ai.backend.runtime-type': 'python',
        'ai.backend.runtime-path': '/opt/venv/bin/python',
        'ai.backend.accelerators': 'tt',
        'ai.backend.resource.min.tt.device': '1',
        'ai.backend.resource.min.cpu': '1',
        'ai.backend.resource.min.mem': '4g',
        'ai.backend.role': 'COMPUTE',
    })
    metalium_resources = json.dumps({
        'cpu': {'min': '1', 'max': None},
        'mem': {'min': '4g', 'max': None},
        'tt.device': {'min': '1', 'max': None},
    })
    await conn.execute('''
        INSERT INTO images (id, name, project, image, tag, registry, registry_id, architecture, config_digest, size_bytes, is_local, type, accelerators, labels, resources, status)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10, \$11, 'COMPUTE'::imagetype, \$12, \$13::json, \$14::jsonb, \$15)
        ON CONFLICT DO NOTHING
    ''',
        uuid.uuid4(),
        'ghcr.io/tenstorrent/tt-metal/tt-metalium-ubuntu-22.04-release-amd64:latest-rc',
        'tenstorrent/tt-metal',
        'tenstorrent/tt-metal/tt-metalium-ubuntu-22.04-release-amd64',
        'latest-rc', 'ghcr.io', reg_id, 'x86_64', 'sha256:placeholder',
        12300000000, False, 'tt', metalium_labels, metalium_resources, 'ALIVE',
    )

    # --- vLLM inference image ---
    vllm_labels = json.dumps({
        'ai.backend.kernelspec': '1',
        'ai.backend.features': 'uid-match',
        'ai.backend.base-distro': 'ubuntu22.04',
        'ai.backend.runtime-type': 'python',
        'ai.backend.runtime-path': '/home/container_app_user/tt-metal/python_env/bin/python3',
        'ai.backend.accelerators': 'tt',
        'ai.backend.resource.min.tt.device': '1',
        'ai.backend.resource.min.cpu': '4',
        'ai.backend.resource.min.mem': '32g',
        'ai.backend.role': 'INFERENCE',
        'ai.backend.endpoint-ports': 'Llama-3.1-8B-Instruct',
        'ai.backend.model-path': '/home/container_app_user/cache/model_weights',
        'ai.backend.model-format': 'custom',
    })
    vllm_resources = json.dumps({
        'cpu': {'min': '4', 'max': None},
        'mem': {'min': '32g', 'max': None},
        'tt.device': {'min': '1', 'max': None},
    })
    await conn.execute('''
        INSERT INTO images (id, name, project, image, tag, registry, registry_id, architecture, config_digest, size_bytes, is_local, type, accelerators, labels, resources, status)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8, \$9, \$10, \$11, 'COMPUTE'::imagetype, \$12, \$13::json, \$14::jsonb, \$15)
        ON CONFLICT DO NOTHING
    ''',
        uuid.uuid4(),
        'ghcr.io/tenstorrent/tt-inference-server/vllm-backendai:latest',
        'tenstorrent/tt-inference-server',
        'tenstorrent/tt-inference-server/vllm-backendai',
        'latest', 'ghcr.io', reg_id, 'x86_64', 'sha256:placeholder',
        17100000000, False, 'tt', vllm_labels, vllm_resources, 'ALIVE',
    )

    # --- Resource presets ---
    await conn.execute('''
        INSERT INTO resource_presets (id, name, resource_slots, shared_memory)
        VALUES (\$1, \$2, \$3, \$4)
        ON CONFLICT DO NOTHING
    ''', uuid.uuid4(), 'tt-inference',
        json.dumps({'cpu': '4', 'mem': str(32 * 1024**3), 'tt.device': '1'}),
        32 * 1024**3)

    await conn.execute('''
        INSERT INTO resource_presets (id, name, resource_slots, shared_memory)
        VALUES (\$1, \$2, \$3, \$4)
        ON CONFLICT DO NOTHING
    ''', uuid.uuid4(), 'tt-dev',
        json.dumps({'cpu': '2', 'mem': str(8 * 1024**3), 'tt.device': '1'}),
        2 * 1024**3)

    await conn.close()
    print('  All resources registered')

asyncio.run(main())
"

echo "=== Init complete ==="
