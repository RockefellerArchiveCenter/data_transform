from unittest.mock import patch

from src.mappings import (generate_download_identifier,
                          generate_manifest_identifier, has_online_asset,
                          has_online_instance, identifier_from_uri, strip_tags)


def test_identifier_from_uri_is_deterministic():
    uri = "/repositories/2/resources/123"
    value1 = identifier_from_uri(uri)
    value2 = identifier_from_uri(uri)

    assert value1 == value2
    assert value1
    assert value1 != "123"

    other = identifier_from_uri(
        "https://host/repositories/2/resources/999?x=1")
    assert other
    assert other != value1


def test_generate_manifest_and_download_identifiers():
    config = {
        "MANIFEST_BASEURL": "https://manifests.example.org/iiif/",
        "DOWNLOAD_BASEURL": "https://downloads.example.org/files/",
    }

    manifest_uri = "/x/1"
    download_uri = "/x/2"

    assert (
        generate_manifest_identifier({"uri": manifest_uri}, {}, config)
        == f"https://manifests.example.org/iiif/{identifier_from_uri(manifest_uri)}"
    )
    assert (
        generate_download_identifier({"uri": download_uri}, {}, config)
        == f"https://downloads.example.org/files/{identifier_from_uri(download_uri)}"
    )


def test_strip_tags_xml_and_regex():
    assert strip_tags("hi <b>there</b>") == "hi there"
    # current regex fallback does not normalize malformed unterminated tags
    assert strip_tags("a <b>broken") == "a <b>broken"


@patch("requests.head")
def test_has_online_asset(mock_head):
    mock_head.return_value = type("R", (), {"status_code": 200})()
    assert has_online_asset(
        "abc", {"ASSET_BASEURL": "https://assets.example.org"}
    ) is True
    mock_head.assert_called_once_with("https://assets.example.org/pdfs/abc")

    mock_head.reset_mock()
    mock_head.return_value = type("R", (), {"status_code": 404})()
    assert has_online_asset("abc", {}) is False
    mock_head.assert_not_called()

    mock_head.reset_mock()
    mock_head.return_value = type("R", (), {"status_code": 404})()
    assert has_online_asset("abc", {"ASSET_BASEURL": ""}) is False
    mock_head.assert_not_called()


@patch("src.mappings.has_online_asset")
def test_has_online_instance(mock_online_asset):
    mock_online_asset.return_value = True
    instances = [{"instance_type": "digital_object"},
                 {"instance_type": "text"}]
    uri = "/repositories/2/resources/123"

    assert has_online_instance(instances, uri, {}) is True
    mock_online_asset.assert_called_once_with(identifier_from_uri(uri), {})

    mock_online_asset.reset_mock()
    mock_online_asset.return_value = False
    assert has_online_instance(instances, uri, {}) is False
    mock_online_asset.assert_called_once_with(identifier_from_uri(uri), {})
