#!/usr/bin/env bash
# Initialize the manager: DB schema, fixtures, etcd config.
# Run once against a fresh halfstack.
set -euo pipefail

ALEMBIC_INI="${ALEMBIC_INI:-/app/alembic.ini}"
MANAGER_CONF="${MANAGER_CONF:-/app/manager.toml}"
FIXTURE_DIR="/app/fixtures/manager"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@lablup.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-wJalrXUt}"

echo "=== DB schema oneshot ==="
python -m ai.backend.cli mgr schema oneshot -f "$ALEMBIC_INI"

echo "=== Preparing fixtures ==="
WORK_DIR=$(mktemp -d)
# Patch admin email/password in users fixture
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

echo "=== Seeding etcd ==="
python -m ai.backend.cli mgr -f "$MANAGER_CONF" etcd put config/redis/addr/host 127.0.0.1
python -m ai.backend.cli mgr -f "$MANAGER_CONF" etcd put config/redis/addr/port 8110
python -m ai.backend.cli mgr -f "$MANAGER_CONF" etcd put config/docker/registry/cr.backend.ai ""
python -m ai.backend.cli mgr -f "$MANAGER_CONF" etcd put config/docker/image/auto_pull "digest"

echo "=== Creating default scaling group ==="
python3 -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine('postgresql+asyncpg://postgres:develove@127.0.0.1:8100/backend')
    async with engine.begin() as conn:
        await conn.execute(text(\"\"\"
            INSERT INTO scaling_groups (name, description, is_active, is_public, driver, driver_opts, scheduler, scheduler_opts, use_host_network)
            VALUES ('default', 'default', true, true, 'static', '{}', 'fifo', '{\"allowed_session_types\": [\"interactive\", \"batch\"]}', false)
            ON CONFLICT DO NOTHING
        \"\"\"))
        await conn.execute(text(\"\"\"
            INSERT INTO sgroups_for_domains (scaling_group, domain)
            VALUES ('default', 'default')
            ON CONFLICT DO NOTHING
        \"\"\"))
        await conn.execute(text('''
            INSERT INTO sgroups_for_groups (scaling_group, \"group\")
            SELECT 'default', id FROM groups WHERE name = 'default'
            ON CONFLICT DO NOTHING
        '''))
    await engine.dispose()

asyncio.run(main())
"

echo "=== Registering Tenstorrent resources and image ==="
python3 -c "
import asyncio, json, uuid
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:develove@127.0.0.1:8100/backend')

    # 1. Add tt.device resource slot type
    await conn.execute('''
        INSERT INTO resource_slot_types (slot_name, slot_type, display_name, description, display_unit, display_icon, number_format, rank)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7, \$8)
        ON CONFLICT DO NOTHING
    ''', 'tt.device', 'count', 'Tenstorrent', 'Tenstorrent AI Accelerator', 'Device', 'tenstorrent', '{\"binary\": false, \"round_length\": 0}', 500)

    # 2. Register ghcr.io container registry
    reg_id = uuid.uuid4()
    await conn.execute('''
        INSERT INTO container_registries (id, url, registry_name, type, project, ssl_verify, is_global)
        VALUES (\$1, \$2, \$3, \$4, \$5, \$6, \$7)
        ON CONFLICT DO NOTHING
    ''', reg_id, 'https://ghcr.io', 'ghcr.io', 'github', 'tenstorrent/tt-metal', True, True)

    # 3. Add ghcr.io to allowed docker registries
    await conn.execute('''
        UPDATE domains SET allowed_docker_registries = array_append(allowed_docker_registries, 'ghcr.io')
        WHERE name = 'default' AND NOT ('ghcr.io' = ANY(allowed_docker_registries))
    ''')

    # 4. Register tt-metalium image
    labels = json.dumps({
        'ai.backend.kernelspec': '1',
        'ai.backend.features': 'uid-match',
        'ai.backend.base-distro': 'ubuntu22.04',
        'ai.backend.runtime-type': 'python',
        'ai.backend.runtime-path': '/opt/venv/bin/python',
        'ai.backend.accelerators': 'tt',
        'ai.backend.resource.min.tt.device': '1',
        'ai.backend.resource.min.cpu': '1',
        'ai.backend.resource.min.mem': '4g',
        'ai.backend.service-ports': 'jupyter:http:8080',
        'ai.backend.role': 'COMPUTE',
    })
    resources = json.dumps({
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
        'latest-rc',
        'ghcr.io',
        reg_id,
        'x86_64',
        'sha256:manual',
        3160000000,
        False,
        'tt',
        labels,
        resources,
        'ALIVE',
    )
    await conn.close()
    print('  Tenstorrent setup complete')

asyncio.run(main())
"

echo "=== Init complete ==="
