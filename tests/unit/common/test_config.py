import os
import pickle
from typing import Any
from unittest.mock import patch

import tomli

from ai.backend.common.config import (
    _expand_env_value,
    expand_env_vars_recursive,
    merge,
    override_key,
    read_from_file,
)


def test_override_key() -> None:
    sample: dict[str, Any] = {
        "a": {
            "b": 0,
        },
        "c": 1,
    }
    override_key(sample, ("a", "b"), -1)
    assert sample["a"]["b"] == -1
    assert sample["c"] == 1

    sample = {
        "a": {
            "b": 0,
        },
        "c": 1,
    }
    override_key(sample, ("c",), -1)
    assert sample["a"]["b"] == 0
    assert sample["c"] == -1


def test_merge() -> None:
    left = {
        "a": {
            "a": 5,
            "b": 0,
        },
        "c": 1,
    }
    right = {
        "a": {
            "b": 2,
            "c": 3,
        },
        "x": 10,
    }
    result = merge(left, right)
    assert result == {
        "a": {
            "a": 5,
            "b": 2,
            "c": 3,
        },
        "c": 1,
        "x": 10,
    }


class TestExpandEnvValue:
    """Tests for ${VAR:-default} expansion in config values."""

    def test_default_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _expand_env_value("${FOO:-bar}") == "bar"

    def test_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"FOO": "baz"}, clear=True):
            assert _expand_env_value("${FOO:-bar}") == "baz"

    def test_no_default_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _expand_env_value("${MISSING}") == ""

    def test_plain_string_unchanged(self) -> None:
        assert _expand_env_value("hello world") == "hello world"

    def test_partial_expansion(self) -> None:
        with patch.dict(os.environ, {"X": "val"}, clear=True):
            assert _expand_env_value("prefix-${X:-d}-suffix") == "prefix-val-suffix"

    def test_multiple_vars(self) -> None:
        with patch.dict(os.environ, {"A": "1"}, clear=True):
            assert _expand_env_value("${A:-x}:${B:-y}") == "1:y"

    def test_ba_prefix_fallback_to_backend(self) -> None:
        with patch.dict(os.environ, {"BACKEND_DB_PASSWORD": "legacy"}, clear=True):
            assert _expand_env_value("${BA_DB_PASSWORD:-default}") == "legacy"

    def test_ba_prefix_preferred_over_backend(self) -> None:
        with patch.dict(
            os.environ, {"BA_DB_PASSWORD": "new", "BACKEND_DB_PASSWORD": "old"}, clear=True
        ):
            assert _expand_env_value("${BA_DB_PASSWORD:-default}") == "new"

    def test_empty_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"FOO": ""}, clear=True):
            assert _expand_env_value("${FOO:-bar}") == ""

    def test_default_with_special_chars(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert _expand_env_value("${X:-127.0.0.1}") == "127.0.0.1"
            assert _expand_env_value("${X:-/opt/backendai}") == "/opt/backendai"

    def test_dollar_without_braces_unchanged(self) -> None:
        assert _expand_env_value("price is $5") == "price is $5"
        assert _expand_env_value("$HOME/path") == "$HOME/path"

    def test_malformed_patterns_unchanged(self) -> None:
        assert _expand_env_value("${") == "${"
        assert _expand_env_value("${}") == "${}"

    def test_password_with_dollar_sign(self) -> None:
        assert _expand_env_value("p@$$word") == "p@$$word"
        assert _expand_env_value("pa$$w0rd!") == "pa$$w0rd!"

    def test_url_with_env_in_password(self) -> None:
        with patch.dict(os.environ, {"BA_DB_PASSWORD": "s3cret"}, clear=True):
            result = _expand_env_value(
                "postgresql://postgres:${BA_DB_PASSWORD:-develove}@localhost:8100/backend"
            )
            assert result == "postgresql://postgres:s3cret@localhost:8100/backend"


class TestReadFromFileExpansion:
    """Integration test: TOML file -> expansion -> config dict."""

    def test_toml_with_env_refs(self, tmp_path: Any) -> None:
        toml_content = """\
[db]
password = "${BA_TEST_PW:-default_pw}"
host = "localhost"
port = "8100"

[paths]
data = "${BA_TEST_HOME:-/opt/backendai}/data"
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        with patch.dict(
            os.environ, {"BA_TEST_PW": "real_pw", "BA_TEST_HOME": "/home/user"}, clear=True
        ):
            cfg, _ = read_from_file(toml_file, "test")
            assert cfg["db"]["password"] == "real_pw"
            assert cfg["db"]["host"] == "localhost"
            assert cfg["db"]["port"] == "8100"
            assert cfg["paths"]["data"] == "/home/user/data"

    def test_toml_without_env_refs_unchanged(self, tmp_path: Any) -> None:
        toml_content = """\
[db]
password = "develove"
host = "127.0.0.1"
port = 8100
enabled = true
"""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(toml_content)

        cfg, _ = read_from_file(toml_file, "test")
        assert cfg["db"]["password"] == "develove"
        assert cfg["db"]["host"] == "127.0.0.1"
        assert cfg["db"]["port"] == 8100
        assert cfg["db"]["enabled"] is True


class TestExpandEnvVarsRecursive:
    """Tests for recursive config dict expansion."""

    def test_nested_dict(self) -> None:
        with patch.dict(os.environ, {"BA_PW": "secret"}, clear=True):
            cfg: dict[str, Any] = {
                "db": {
                    "password": "${BA_PW:-develove}",
                    "host": "localhost",
                },
            }
            result = expand_env_vars_recursive(cfg)
            assert result["db"]["password"] == "secret"
            assert result["db"]["host"] == "localhost"

    def test_list_values(self) -> None:
        with patch.dict(os.environ, {"BA_ADDR": "10.0.0.1"}, clear=True):
            cfg: dict[str, Any] = {
                "addrs": ["${BA_ADDR:-127.0.0.1}", "static"],
            }
            result = expand_env_vars_recursive(cfg)
            assert result["addrs"] == ["10.0.0.1", "static"]

    def test_non_string_values_unchanged(self) -> None:
        cfg: dict[str, Any] = {
            "port": 8100,
            "enabled": True,
            "ratio": 0.5,
        }
        result = expand_env_vars_recursive(cfg)
        assert result["port"] == 8100
        assert result["enabled"] is True
        assert result["ratio"] == 0.5

    def test_deeply_nested(self) -> None:
        with patch.dict(os.environ, {"V": "deep"}, clear=True):
            cfg: dict[str, Any] = {"a": {"b": {"c": "${V:-shallow}"}}}
            result = expand_env_vars_recursive(cfg)
            assert result["a"]["b"]["c"] == "deep"


def test_sanitize_inline_dicts() -> None:
    sample = """
    [section]
    a = { x = 1, y = 1 }
    b = { x = 1, y = { t = 2, u = 2 } }
    """

    result = tomli.loads(sample)
    assert isinstance(result["section"]["a"], dict)
    assert isinstance(result["section"]["b"], dict)
    assert isinstance(result["section"]["b"]["y"], dict)

    # Also ensure the result is picklable.
    data = pickle.dumps(result)
    result = pickle.loads(data)
    assert result == {
        "section": {
            "a": {"x": 1, "y": 1},
            "b": {"x": 1, "y": {"t": 2, "u": 2}},
        },
    }
