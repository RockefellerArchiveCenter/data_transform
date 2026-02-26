# tests/test_mappings.py
import importlib
import os
import sys
from unittest.mock import Mock, patch

import pytest

BASE_ENV = {
    "ASSET_BASEURL": "https://assets.example.org",
    "AUDIO_REFS": "",
    "MOVING_IMAGE_REFS": "",
    "PHOTOGRAPH_REFS": "",
}


def import_fresh(module_name: str):
    """Import a module fresh so import-time env reads are re-evaluated."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


@pytest.fixture
def mod(request):
    """Import src.mappings under a baseline env (no SSM)."""
    extra_env = getattr(request, "param", None) or {}

    env = dict(BASE_ENV)
    env.update(extra_env)

    with patch.dict(os.environ, env, clear=False):
        yield import_fresh("src.mappings")


@pytest.fixture
def mod_ssm(request):
    """Import src.mappings with ENVIRONMENT/AWS_REGION/SSM_ROLE_ARN and mocked SSM."""
    params = getattr(request, "param", None) or {}
    extra_env = params.get("extra_env") or {}
    ssm_params = params.get("ssm_params") or {}

    env = {
        "ASSET_BASEURL": "https://assets.example.org",
        "ENVIRONMENT": "dev",
        "AWS_REGION": "us-east-1",
        "SSM_ROLE_ARN": "arn:aws:iam::000000000000:role/dummy",
    }
    env.update(extra_env)

    # Mock STS assume_role
    sts_client = Mock()
    sts_client.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA_TEST",
            "SecretAccessKey": "SECRET",
            "SessionToken": "TOKEN",
        }
    }

    # Mock SSM paginator returning parameters under:
    # /{ENVIRONMENT}/data_transform/{KEY}
    paginator = Mock()
    paginator.paginate.return_value = [
        {
            "Parameters": [
                {"Name": f"/{env['ENVIRONMENT']
                             }/data_transform/{k}", "Value": v}
                for k, v in ssm_params.items()
            ]
        }
    ]

    ssm_client = Mock()
    ssm_client.get_paginator.return_value = paginator

    base_session = Mock()
    base_session.region_name = env["AWS_REGION"]
    base_session.client.side_effect = (
        lambda service: sts_client if service == "sts" else Mock()
    )

    assumed_session = Mock()
    assumed_session.region_name = env["AWS_REGION"]
    assumed_session.client.side_effect = (
        lambda service: ssm_client if service == "ssm" else Mock()
    )

    with (
        patch.dict(os.environ, env, clear=False),
        patch("boto3.Session", side_effect=[base_session, assumed_session]),
    ):
        yield import_fresh("src.mappings")


@pytest.mark.parametrize("mod",
                         [{"AUDIO_REFS": " a, b ,c ,, "}], indirect=True)
def test_env_list_empty_and_split(mod):
    assert mod.env_list("DOES_NOT_EXIST") == []
    assert mod.env_list("AUDIO_REFS") == ["a", "b", "c"]


def test_identifier_from_uri_handles_full_url_and_path(mod):
    assert mod.identifier_from_uri("/repositories/2/resources/123") == "123"
    assert mod.identifier_from_uri(
        "https://host/repositories/2/resources/999?x=1"
    ) == "999"
    assert mod.identifier_from_uri("") == ""


def test_generate_manifest_and_download_identifiers(mod):
    assert mod.generate_manifest_identifier(
        {"uri": "/x/1"}, {}) == "manifest-1"
    assert mod.generate_download_identifier(
        {"ref": "/x/2"}, {}) == "download-2"
    assert mod.generate_manifest_identifier({}, {}) == "manifest"


def test_strip_tags_xml_and_regex_fallback(mod):
    assert mod.strip_tags("hi <b>there</b>") == "hi there"
    assert mod.strip_tags("a <b>broken") == "a broken"


def test_has_online_asset_uses_requests_head_status_code(mod):
    resp = type("R", (), {"status_code": 200})()
    with patch.object(mod.requests, "head", return_value=resp) as m:
        assert mod.has_online_asset("abc") is True
        m.assert_called_once()

    resp2 = type("R", (), {"status_code": 404})()
    with patch.object(mod.requests, "head", return_value=resp2):
        assert mod.has_online_asset("abc") is False


@pytest.mark.parametrize("mod", [{"ASSET_BASEURL": ""}], indirect=True)
def test_has_online_asset_false_when_no_baseurl(mod):
    assert mod.has_online_asset("abc") is False


def test_has_online_instance_with_dict_instances_calls_has_online_asset(mod):
    instances = [{"instance_type": "digital_object"},
                 {"instance_type": "text"}]
    with patch.object(mod, "has_online_asset", return_value=True) as hoa:
        assert mod.has_online_instance(
            instances, "/repositories/2/resources/123"
        ) is True
        hoa.assert_called_once_with("123")


def test_has_online_instance_with_object_instances_calls_has_online_asset(mod):
    class Inst:
        def __init__(self, t):
            self.instance_type = t

    instances = [Inst("digital_object"), Inst("text")]
    with patch.object(mod, "has_online_asset", return_value=False):
        assert mod.has_online_instance(
            instances, "/repositories/2/resources/123"
        ) is False


@pytest.mark.parametrize(
    "mod_ssm",
    [
        {
            "extra_env": {
                # DO NOT seed AUDIO_REFS/etc here, or SSM won't fill them.
            },
            "ssm_params": {
                "AUDIO_REFS": "a, b, c",
                "MOVING_IMAGE_REFS": "m1,m2",
                "PHOTOGRAPH_REFS": "p1",
            },
        }
    ],
    indirect=True,
)
def test_load_runtime_env_merges_ssm_defaults_when_env_missing(mod_ssm):
    assert mod_ssm.env_list("AUDIO_REFS") == ["a", "b", "c"]
    assert mod_ssm.env_list("MOVING_IMAGE_REFS") == ["m1", "m2"]
    assert mod_ssm.env_list("PHOTOGRAPH_REFS") == ["p1"]


@pytest.mark.parametrize(
    "mod_ssm",
    [
        {
            "extra_env": {"AUDIO_REFS": "x,y"},
            "ssm_params": {"AUDIO_REFS": "a,b,c"},
        }
    ],
    indirect=True,
)
def test_load_runtime_env_env_vars_win_over_ssm(mod_ssm):
    assert mod_ssm.env_list("AUDIO_REFS") == ["x", "y"]


def test_get_config_returns_empty_when_missing_required_inputs(mod):
    assert mod.get_config("", "us-east-1", "arn:role") == {}
    assert mod.get_config("dev", "", "arn:role") == {}
    assert mod.get_config("dev", "us-east-1", "") == {}
