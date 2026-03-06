from unittest.mock import patch

from src.mappings import (generate_download_identifier,
                          generate_manifest_identifier, has_online_asset,
                          has_online_instance, identifier_from_uri, strip_tags)


def test_identifier_from_uri_handles_full_url_and_path():
    assert identifier_from_uri("/repositories/2/resources/123") == "123"
    assert identifier_from_uri(
        "https://host/repositories/2/resources/999?x=1") == "999"
    assert identifier_from_uri("") == ""


def test_generate_manifest_and_download_identifiers():
    assert generate_manifest_identifier(
        {"uri": "/x/1"}, {}) == "manifest-1"
    assert generate_download_identifier(
        {"ref": "/x/2"}, {}) == "download-2"
    assert generate_manifest_identifier({}, {}) == "manifest"


def test_strip_tags_xml_and_regex():
    assert strip_tags("hi <b>there</b>") == "hi there"
    assert strip_tags("a <b>broken") == "a broken"


@patch('requests.head')
def test_has_online_asset(mock_head):
    mock_head.return_value = type("R", (), {"status_code": 200})()
    assert has_online_asset(
        "abc", {"ASSET_BASEURL": "https://assets.example.org"}) is True
    mock_head.assert_called_once_with('https://assets.example.org/pdfs/abc')

    mock_head.reset_mock()
    mock_head.return_value = type("R", (), {"status_code": 404})()
    assert has_online_asset("abc", {}) is False
    mock_head.assert_not_called()

    mock_head.reset_mock()
    mock_head.return_value = type("R", (), {"status_code": 404})()
    assert has_online_asset("abc", {"ASSET_BASEURL": ""}) is False
    mock_head.assert_not_called()


@patch('src.mappings.has_online_asset')
def test_has_online_instance(mock_online_asset):
    mock_online_asset.return_value = True
    instances = [{"instance_type": "digital_object"},
                 {"instance_type": "text"}]
    assert has_online_instance(
        instances,
        "/repositories/2/resources/123",
        {}) is True
    mock_online_asset.assert_called_once_with("123", {})

    mock_online_asset.reset_mock()
    mock_online_asset.return_value = False
    assert has_online_instance(
        instances,
        "/repositories/2/resources/123",
        {}) is False
    mock_online_asset.assert_called_once_with("123", {})
