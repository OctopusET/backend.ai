import os
import pickle
from typing import Any
from unittest.mock import patch

import pytest
import tomli

from ai.backend.common.config import (
    ModelConfig,
    ModelDefinition,
    ModelDefinitionDraft,
    ModelHealthCheck,
    ModelMetadata,
    ModelServiceConfig,
    _expand_env_value,
    _merge_config,
    _merge_definition,
    _merge_metadata,
    _merge_service_config,
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


class TestMergeFieldCoverage:
    """Verify merge functions handle every declared field.

    When a field is added to a config model but the corresponding merge
    function is not updated, these tests will fail because the new field
    will be missing from the result's model_fields_set.
    """

    def test_merge_metadata(self) -> None:
        base = ModelMetadata.model_construct(
            _fields_set=set(ModelMetadata.model_fields),
            author="base",
            title="base",
            version="base",
            created="base",
            last_modified="base",
            description="base",
            task="base",
            category="base",
            architecture="base",
            framework=["base"],
            label=["base"],
            license="base",
            min_resource={"base": 1},
        )
        override = ModelMetadata.model_construct(_fields_set=set())
        result = _merge_metadata(base, override)
        missing = set(ModelMetadata.model_fields) - result.model_fields_set
        assert not missing, f"_merge_metadata() does not handle: {missing}"

    def test_merge_service_config(self) -> None:
        base = ModelServiceConfig.model_construct(
            _fields_set=set(ModelServiceConfig.model_fields),
            pre_start_actions=[],
            start_command=["base-cmd"],
            shell="/bin/base",
            port=9999,
            health_check=None,
        )
        override = ModelServiceConfig.model_construct(
            _fields_set=set(),
            pre_start_actions=[],
            start_command=[],
            shell="",
            port=2,
            health_check=None,
        )
        result = _merge_service_config(base, override)
        missing = set(ModelServiceConfig.model_fields) - result.model_fields_set
        assert not missing, f"_merge_service_config() does not handle: {missing}"

    def test_merge_service_config_health_check_subfields(self) -> None:
        base_hc = ModelHealthCheck.model_construct(
            _fields_set=set(ModelHealthCheck.model_fields),
            interval=99.0,
            path="/base",
            max_retries=99,
            max_wait_time=99.0,
            expected_status_code=201,
            initial_delay=99.0,
        )
        override_hc = ModelHealthCheck.model_construct(
            _fields_set=set(),
            path="",
        )
        base = ModelServiceConfig.model_construct(
            _fields_set={"health_check"},
            start_command=[],
            port=2,
            health_check=base_hc,
        )
        override = ModelServiceConfig.model_construct(
            _fields_set={"health_check"},
            start_command=[],
            port=2,
            health_check=override_hc,
        )
        result = _merge_service_config(base, override)
        assert result.health_check is not None
        missing = set(ModelHealthCheck.model_fields) - result.health_check.model_fields_set
        assert not missing, f"health_check merge does not handle: {missing}"

    def test_merge_config(self) -> None:
        base = ModelConfig.model_construct(
            _fields_set=set(ModelConfig.model_fields),
            name="base",
            model_path="/base",
            service=None,
            metadata=None,
        )
        override = ModelConfig.model_construct(
            _fields_set=set(),
            name="",
            model_path="",
        )
        result = _merge_config(base, override)
        missing = set(ModelConfig.model_fields) - result.model_fields_set
        assert not missing, f"_merge_config() does not handle: {missing}"

    def test_merge_definition(self) -> None:
        base = ModelDefinition.model_construct(
            _fields_set=set(ModelDefinition.model_fields),
            models=[],
        )
        override = ModelDefinition.model_construct(_fields_set=set())
        result = _merge_definition(base, override)
        missing = set(ModelDefinition.model_fields) - result.model_fields_set
        assert not missing, f"_merge_definition() does not handle: {missing}"


class TestModelConfigs:
    def test_sanitize_inline_dicts(self) -> None:
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

    @pytest.fixture
    def model_definition_draft_with_minimal_service(self) -> ModelDefinitionDraft:
        return ModelDefinitionDraft.model_validate({
            "models": [
                {
                    "name": "demo",
                    "model_path": "/models/demo",
                    "service": {
                        "port": 8000,
                    },
                }
            ]
        })

    def test_model_service_config_draft_allows_missing_start_command(
        self, model_definition_draft_with_minimal_service: ModelDefinitionDraft
    ) -> None:
        model_definition = model_definition_draft_with_minimal_service
        resolved = model_definition.to_resolved()

        service = resolved.models[0].service
        assert service is not None
        assert service.start_command is None
        assert service.port == 8000

    def test_to_resolved_substitutes_model_path_placeholder(self) -> None:
        # The variant baseline keeps ``{model_path}`` so a single fixture
        # entry covers any mount destination; the placeholder is resolved
        # once, at the boundary between draft merge and persistence.
        draft = ModelDefinitionDraft.model_validate({
            "models": [
                {
                    "name": "demo",
                    "model_path": "/custom-mount",
                    "service": {
                        "start_command": ["vllm", "serve", "{model_path}"],
                        "port": 8000,
                    },
                }
            ]
        })

        resolved = draft.to_resolved()

        service = resolved.models[0].service
        assert service is not None
        assert service.start_command == ["vllm", "serve", "/custom-mount"]

    def test_to_resolved_substitutes_placeholder_with_named_flag(self) -> None:
        # SGLang-style: ``{model_path}`` lands after a flag; the
        # substitution touches the placeholder token only, not the flag.
        draft = ModelDefinitionDraft.model_validate({
            "models": [
                {
                    "name": "demo",
                    "model_path": "/data",
                    "service": {
                        "start_command": [
                            "python",
                            "-m",
                            "sglang.launch_server",
                            "--model-path",
                            "{model_path}",
                        ],
                        "port": 9001,
                    },
                }
            ]
        })

        resolved = draft.to_resolved()

        service = resolved.models[0].service
        assert service is not None
        assert service.start_command == [
            "python",
            "-m",
            "sglang.launch_server",
            "--model-path",
            "/data",
        ]

    def test_to_resolved_leaves_start_command_with_no_placeholder_unchanged(self) -> None:
        draft = ModelDefinitionDraft.model_validate({
            "models": [
                {
                    "name": "demo",
                    "model_path": "/models",
                    "service": {
                        "start_command": ["my-server", "--bind", "0.0.0.0"],
                        "port": 8000,
                    },
                }
            ]
        })

        resolved = draft.to_resolved()

        service = resolved.models[0].service
        assert service is not None
        assert service.start_command == ["my-server", "--bind", "0.0.0.0"]


class TestModelDefinitionWithArgsAppended:
    @pytest.fixture
    def vllm_definition(self) -> ModelDefinition:
        return ModelDefinition(
            models=[
                ModelConfig(
                    name="demo",
                    model_path="/models",
                    service=ModelServiceConfig(
                        port=8000,
                        start_command=["vllm", "serve", "/models"],
                    ),
                )
            ]
        )

    @pytest.fixture
    def definition_without_start_command(self) -> ModelDefinition:
        return ModelDefinition(
            models=[
                ModelConfig(
                    name="demo",
                    model_path="/models",
                    service=ModelServiceConfig(port=8000, start_command=None),
                )
            ]
        )

    @pytest.fixture
    def definition_without_service(self) -> ModelDefinition:
        return ModelDefinition(
            models=[ModelConfig(name="demo", model_path="/models", service=None)],
        )

    @pytest.fixture
    def multi_model_definition(self) -> ModelDefinition:
        return ModelDefinition(
            models=[
                ModelConfig(
                    name="a",
                    model_path="/models/a",
                    service=ModelServiceConfig(port=8001, start_command=["a"]),
                ),
                ModelConfig(
                    name="b",
                    model_path="/models/b",
                    service=ModelServiceConfig(port=8002, start_command=["b"]),
                ),
            ]
        )

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            pytest.param(
                ["--max-model-len", "4096"],
                ["vllm", "serve", "/models", "--max-model-len", "4096"],
                id="single-flag-pair",
            ),
            pytest.param(
                ["--port", "8000", "--max-model-len", "4096"],
                ["vllm", "serve", "/models", "--port", "8000", "--max-model-len", "4096"],
                id="multiple-flag-pairs",
            ),
            pytest.param(
                ["--trust-remote-code"],
                ["vllm", "serve", "/models", "--trust-remote-code"],
                id="bare-flag",
            ),
        ],
    )
    async def test_appends_args_as_separate_tokens(
        self,
        vllm_definition: ModelDefinition,
        args: list[str],
        expected: list[str],
    ) -> None:
        result = vllm_definition.with_args_appended(args)

        service = result.models[0].service
        assert service is not None
        assert service.start_command == expected

    async def test_empty_args_returns_self(
        self,
        vllm_definition: ModelDefinition,
    ) -> None:
        # Identity (``is``) is the contract for the no-op shortcut — no
        # copy is taken when there is nothing to append.
        assert vllm_definition.with_args_appended([]) is vllm_definition

    async def test_does_not_mutate_input(
        self,
        vllm_definition: ModelDefinition,
    ) -> None:
        # The same ``ModelDefinition`` may be re-used across deployments
        # with different presets; mutation here would cross-contaminate
        # later builds.
        vllm_definition.with_args_appended(["--port", "8000"])

        service = vllm_definition.models[0].service
        assert service is not None
        assert service.start_command == ["vllm", "serve", "/models"]

    async def test_args_become_start_command_when_none(
        self,
        definition_without_start_command: ModelDefinition,
    ) -> None:
        result = definition_without_start_command.with_args_appended(["--port", "8000"])

        service = result.models[0].service
        assert service is not None
        assert service.start_command == ["--port", "8000"]

    async def test_passes_through_models_without_service(
        self,
        definition_without_service: ModelDefinition,
    ) -> None:
        result = definition_without_service.with_args_appended(["--port", "8000"])

        assert result.models[0].service is None

    async def test_each_model_receives_args(
        self,
        multi_model_definition: ModelDefinition,
    ) -> None:
        result = multi_model_definition.with_args_appended(["--shared", "true"])

        first = result.models[0].service
        second = result.models[1].service
        assert first is not None and second is not None
        assert first.start_command == ["a", "--shared", "true"]
        assert second.start_command == ["b", "--shared", "true"]


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
