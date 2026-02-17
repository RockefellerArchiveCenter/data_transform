import importlib
import os
from unittest.mock import patch

import pytest


def import_mappings(extra_env=None):
    env = {
        "ASSET_BASEURL": "https://assets.example.org",
        "AUDIO_REFS": "",
        "MOVING_IMAGE_REFS": "",
        "PHOTOGRAPH_REFS": "",
    }
    if extra_env:
        env.update(extra_env)

    with patch.dict(os.environ, env, clear=False):
        import sys
        sys.modules.pop("src.mappings", None)
        mod = importlib.import_module("src.mappings")
    return mod


def test_env_list_empty_and_split():
    mod = import_mappings({"AUDIO_REFS": " a, b ,c ,, "})
    assert mod.env_list("DOES_NOT_EXIST") == []
    assert mod.env_list("AUDIO_REFS") == ["a", "b", "c"]


def test_identifier_from_uri_handles_full_url_and_path():
    mod = import_mappings()
    assert mod.identifier_from_uri("/repositories/2/resources/123") == "123"
    assert mod.identifier_from_uri("https://host/repositories/2/resources/999?x=1") == "999"
    assert mod.identifier_from_uri("") == ""


def test_generate_manifest_and_download_identifiers():
    mod = import_mappings()
    assert mod.generate_manifest_identifier({"uri": "/x/1"}, {}) == "manifest-1"
    assert mod.generate_download_identifier({"ref": "/x/2"}, {}) == "download-2"
    assert mod.generate_manifest_identifier({}, {}) == "manifest"


def test_strip_tags_xml_and_regex_fallback():
    mod = import_mappings()
    assert mod.strip_tags("hi <b>there</b>") == "hi there"
    assert mod.strip_tags("a <b>broken") == "a broken"


def test_has_online_asset_uses_requests_head_status_code():
    mod = import_mappings({"ASSET_BASEURL": "https://assets.example.org"})
    resp = type("R", (), {"status_code": 200})()
    with patch.object(mod.requests, "head", return_value=resp) as m:
        assert mod.has_online_asset("abc") is True
        m.assert_called_once()
    resp2 = type("R", (), {"status_code": 404})()
    with patch.object(mod.requests, "head", return_value=resp2):
        assert mod.has_online_asset("abc") is False


def test_has_online_asset_false_when_no_baseurl():
    mod = import_mappings({"ASSET_BASEURL": ""})
    assert mod.has_online_asset("abc") is False


def test_has_online_instance_with_dict_instances_calls_has_online_asset():
    mod = import_mappings({"ASSET_BASEURL": "https://assets.example.org"})

    instances = [{"instance_type": "digital_object"}, {"instance_type": "text"}]
    with patch.object(mod, "has_online_asset", return_value=True) as hoa:
        assert mod.has_online_instance(instances, "/repositories/2/resources/123") is True
        hoa.assert_called_once_with("123")


def test_has_online_instance_with_object_instances_calls_has_online_asset():
    mod = import_mappings({"ASSET_BASEURL": "https://assets.example.org"})

    class Inst:
        def __init__(self, t):
            self.instance_type = t

    instances = [Inst("digital_object"), Inst("text")]
    with patch.object(mod, "has_online_asset", return_value=False):
        assert mod.has_online_instance(instances, "/repositories/2/resources/123") is False
