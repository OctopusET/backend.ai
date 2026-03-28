"""Backend.AI deployment mode utilities.

Supports ``BA_MODE=dev|prod`` for environment-specific behavior.
Inspired by Keycloak's ``start-dev`` vs ``start`` separation.
"""

from __future__ import annotations

import enum
import logging
import os

from .identity import resolve_local_ip

__all__ = (
    "DeployMode",
    "get_deploy_mode",
    "resolve_advertised_host",
)

log = logging.getLogger(__name__)


class DeployMode(enum.StrEnum):
    DEV = "dev"
    PROD = "prod"


def get_deploy_mode() -> DeployMode:
    """Read ``BA_MODE`` from environment. Defaults to ``dev``."""
    raw = os.environ.get("BA_MODE", "dev").lower()
    try:
        return DeployMode(raw)
    except ValueError:
        log.warning("Unknown BA_MODE=%r, falling back to 'dev'", raw)
        return DeployMode.DEV


def resolve_advertised_host(configured_host: str) -> str:
    """Resolve an advertised host address.

    In dev mode, ``0.0.0.0`` or empty string is auto-resolved to the first
    non-loopback IP via ``resolve_local_ip()``.

    In prod mode, ``0.0.0.0`` or empty string raises an error -- the
    ``BA_ADVERTISED_HOST`` environment variable must be set explicitly.

    Returns the resolved host string.
    """
    if configured_host not in ("0.0.0.0", ""):
        return configured_host

    mode = get_deploy_mode()
    if mode == DeployMode.PROD:
        raise RuntimeError(
            "BA_ADVERTISED_HOST is required in production mode (BA_MODE=prod). "
            "Set it to the externally reachable IP or hostname of this node."
        )

    resolved = resolve_local_ip()
    if resolved:
        log.warning(
            "Advertised host resolved to %s via network interface auto-detection. "
            "Set BA_ADVERTISED_HOST explicitly for production use.",
            resolved,
        )
        return resolved

    log.warning("Could not auto-resolve advertised host, using 0.0.0.0")
    return configured_host
