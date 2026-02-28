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

echo "=== Init complete ==="
