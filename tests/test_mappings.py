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
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


@pytest.fixture
def mod():
    with patch.dict(os.environ, dict(BASE_ENV), clear=False):
        return import_fresh("src.mappings")


@pytest.mark.parametrize("raw,expected",
                         [("", []), (" a, b ,c ,, ", ["a", "b", "c"])])
def test_env_list_empty_and_split(mod, raw, expected):
    # apply runtime config using config dict; env vars may be empty
    mod.apply_runtime_config({"AUDIO_REFS": raw},
                             env={"ASSET_BASEURL": "https://assets.example.org"})
    assert mod.env_list("AUDIO_REFS") == expected


def test_apply_runtime_config_env_wins_over_ssm(mod):
    env = {"AUDIO_REFS": "x,y", "ASSET_BASEURL": "https://env.example.org"}
    cfg = {"AUDIO_REFS": "a,b,c", "ASSET_BASEURL": "https://ssm.example.org"}
    mod.apply_runtime_config(cfg, env=env)
    assert mod.env_list("AUDIO_REFS") == ["x", "y"]
    assert mod.ASSET_BASEURL == "https://env.example.org"


def test_identifier_from_uri_handles_full_url_and_path(mod):
    assert mod.identifier_from_uri("/repositories/2/resources/123") == "123"
    assert mod.identifier_from_uri(
        "https://host/repositories/2/resources/999?x=1") == "999"
    assert mod.identifier_from_uri("") == ""


def test_generate_manifest_and_download_identifiers(mod):
    assert mod.generate_manifest_identifier(
        {"uri": "/x/1"}, {}) == "manifest-1"
    assert mod.generate_download_identifier(
        {"ref": "/x/2"}, {}) == "download-2"
    assert mod.generate_manifest_identifier({}, {}) == "manifest"


def test_strip_tags_xml_and_regex(mod):
    assert mod.strip_tags("hi <b>there</b>") == "hi there"
    assert mod.strip_tags("a <b>broken") == "a broken"


def test_has_online_asset_uses_requests_head_status_code(mod):
    resp = type("R", (), {"status_code": 200})()
    mod.apply_runtime_config(
        {"ASSET_BASEURL": "https://assets.example.org"}, env={})
    with patch.object(mod.requests, "head", return_value=resp) as m:
        assert mod.has_online_asset("abc") is True
        m.assert_called_once()

    resp2 = type("R", (), {"status_code": 404})()
    with patch.object(mod.requests, "head", return_value=resp2):
        assert mod.has_online_asset("abc") is False


def test_has_online_asset_false_when_no_baseurl(mod):
    mod.apply_runtime_config({"ASSET_BASEURL": ""}, env={})
    assert mod.has_online_asset("abc") is False


def test_has_online_instance_with_dict_instances_calls_has_online_asset(mod):
    instances = [{"instance_type": "digital_object"},
                 {"instance_type": "text"}]
    with patch.object(mod, "has_online_asset", return_value=True) as hoa:
        assert mod.has_online_instance(
            instances, "/repositories/2/resources/123") is True
        hoa.assert_called_once_with("123")


def test_has_online_instance_with_object_instances_calls_has_online_asset(mod):
    class Inst:
        def __init__(self, t):
            self.instance_type = t

    instances = [Inst("digital_object"), Inst("text")]
    with patch.object(mod, "has_online_asset", return_value=False):
        assert mod.has_online_instance(
            instances, "/repositories/2/resources/123") is False


def test_get_config_returns_empty_when_missing_required(mod):
    assert mod.get_config("", "us-east-1", "arn:role") == {}
    assert mod.get_config("dev", "", "arn:role") == {}
    assert mod.get_config("dev", "us-east-1", "") == {}


def test_get_config_loads_parameters_by_path():
    # This tests the helper directly without importing transformers.
    mod = import_fresh("src.mappings")

    env = {"ENVIRONMENT": "test", "AWS_REGION": "us-east-1",
           "SSM_ROLE_ARN": "arn:aws:iam::1:role/Dummy"}

    paginator = Mock()
    paginator.paginate.return_value = [{
        "Parameters": [
            {"Name": "/test/data_transform/AUDIO_REFS", "Value": "a,b,c"},
            {"Name": "/test/data_transform/ASSET_BASEURL",
                "Value": "https://assets.example.org"},
        ]
    }]
    ssm_client = Mock()
    ssm_client.get_paginator.return_value = paginator

    base_session = Mock()
    base_session.region_name = env["AWS_REGION"]
    base_session.client.return_value = Mock()

    assumed_session = Mock()
    assumed_session.region_name = env["AWS_REGION"]
    assumed_session.client.side_effect = lambda svc: ssm_client if svc == "ssm" else Mock()

    with (
        patch.dict(os.environ, env, clear=False),
        patch("boto3.Session", side_effect=[base_session, assumed_session]),
        patch.object(mod, "assume_role_session", return_value=assumed_session),
    ):
        cfg = mod.get_config(
            env["ENVIRONMENT"],
            env["AWS_REGION"],
            env["SSM_ROLE_ARN"],
            service_name="data_transform")

    assert cfg["AUDIO_REFS"] == "a,b,c"
    assert cfg["ASSET_BASEURL"] == "https://assets.example.org"
    paginator.paginate.assert_called()
