from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ai.backend.common.mode import (
    DeployMode,
    get_deploy_mode,
    resolve_advertised_host,
)


class TestGetDeployMode:
    def test_default_is_dev(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert get_deploy_mode() == DeployMode.DEV

    def test_dev_explicit(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "dev"}, clear=True):
            assert get_deploy_mode() == DeployMode.DEV

    def test_prod(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "prod"}, clear=True):
            assert get_deploy_mode() == DeployMode.PROD

    def test_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "PROD"}, clear=True):
            assert get_deploy_mode() == DeployMode.PROD

    def test_invalid_falls_back_to_dev(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "staging"}, clear=True):
            assert get_deploy_mode() == DeployMode.DEV


class TestResolveAdvertisedHost:
    def test_real_ip_unchanged(self) -> None:
        assert resolve_advertised_host("192.168.1.100") == "192.168.1.100"

    def test_hostname_unchanged(self) -> None:
        assert resolve_advertised_host("my-server.example.com") == "my-server.example.com"

    def test_dev_mode_auto_resolves(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "dev"}, clear=True):
            with patch("ai.backend.common.mode.resolve_local_ip", return_value="10.0.0.5"):
                assert resolve_advertised_host("0.0.0.0") == "10.0.0.5"

    def test_dev_mode_auto_resolves_empty(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "dev"}, clear=True):
            with patch("ai.backend.common.mode.resolve_local_ip", return_value="10.0.0.5"):
                assert resolve_advertised_host("") == "10.0.0.5"

    def test_dev_mode_fallback_when_no_interface(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "dev"}, clear=True):
            with patch("ai.backend.common.mode.resolve_local_ip", return_value=None):
                assert resolve_advertised_host("0.0.0.0") == "0.0.0.0"

    def test_prod_mode_rejects_unset(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "prod"}, clear=True):
            with pytest.raises(RuntimeError, match="BA_ADVERTISED_HOST is required"):
                resolve_advertised_host("0.0.0.0")

    def test_prod_mode_rejects_empty(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "prod"}, clear=True):
            with pytest.raises(RuntimeError, match="BA_ADVERTISED_HOST is required"):
                resolve_advertised_host("")

    def test_prod_mode_accepts_real_ip(self) -> None:
        with patch.dict(os.environ, {"BA_MODE": "prod"}, clear=True):
            assert resolve_advertised_host("10.0.0.1") == "10.0.0.1"
