from unittest.mock import patch

from src.mappings import (convert_dates, generate_download_identifier,
                          generate_manifest_identifier, has_online_asset,
                          has_online_instance, identifier_from_uri,
                          language_name, strip_tags, transform_formats,
                          transform_group, transform_language)
from tests.test_helpers import RecursiveNamespace


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
    mock_head.return_value = RecursiveNamespace.from_obj({"status_code": 200})
    assert has_online_asset(
        "abc", {"ASSET_BASEURL": "https://assets.example.org"}
    ) is True
    mock_head.assert_called_once_with("https://assets.example.org/pdfs/abc")

    mock_head.reset_mock()
    mock_head.return_value = RecursiveNamespace.from_obj({"status_code": 404})
    assert has_online_asset("abc", {}) is False
    mock_head.assert_not_called()

    mock_head.reset_mock()
    mock_head.return_value = RecursiveNamespace.from_obj({"status_code": 404})
    assert has_online_asset("abc", {"ASSET_BASEURL": ""}) is False
    mock_head.assert_not_called()


@patch("src.mappings.has_online_asset")
def test_has_online_instance(mock_online_asset):
    mock_online_asset.return_value = True
    instances = [
        {"instance_type": "digital_object"},
        {"instance_type": "text"},
    ]
    uri = "/repositories/2/resources/123"

    assert has_online_instance(instances, uri, {}) is True
    mock_online_asset.assert_called_once_with(identifier_from_uri(uri), {})

    mock_online_asset.reset_mock()
    mock_online_asset.return_value = False
    assert has_online_instance(instances, uri, {}) is False
    mock_online_asset.assert_called_once_with(identifier_from_uri(uri), {})


@patch("src.mappings.odin.codecs.json_codec.loads")
@patch("src.mappings.SourceDateToDate.apply")
def test_convert_dates_uses_source_date(mock_apply, mock_loads):
    mock_apply.return_value = ["converted"]
    mock_loads.side_effect = lambda value, resource=None: value
    value = [
        {
            "jsonmodel_type": "date",
            "begin": "1900",
            "end": "1901"
        }
    ]
    result = convert_dates(value)
    assert result == ["converted"]
    mock_apply.assert_called_once()


@patch("src.mappings.odin.codecs.json_codec.loads")
@patch("src.mappings.SourceStructuredDateToDate.apply")
def test_convert_dates_uses_structured_date(mock_apply, mock_loads):
    mock_apply.return_value = ["converted"]
    mock_loads.side_effect = lambda value, resource=None: value
    value = [
        {
            "jsonmodel_type": "structured_date_label",
            "date_label": "creation"
        }
    ]
    result = convert_dates(value)
    assert result == ["converted"]
    mock_apply.assert_called_once()


def test_language_name_variants():
    assert language_name(None) is None
    assert language_name("") is None
    assert language_name("eng") == "English"
    assert language_name("en") == "English"
    assert language_name("fre") == "French"


def test_transform_language_value():
    result = transform_language("eng", None)
    assert len(result) == 1
    assert result[0].expression == "English"
    assert result[0].identifier == "eng"


def test_transform_language_lang_materials():
    lang_materials = [
        RecursiveNamespace.from_obj({
            "language_and_script": {"language": "fre"}
        }),
        RecursiveNamespace.from_obj({
            "language_and_script": None
        }),
    ]
    result = transform_language(None, lang_materials)
    assert len(result) == 1
    assert result[0].expression == "French"
    assert result[0].identifier == "fre"


def test_transform_language_defaults_english():
    result = transform_language(None, None)
    assert len(result) == 1
    assert result[0].expression == "English"
    assert result[0].identifier == "eng"


def test_transform_language_unknown_code():
    try:
        transform_language("zzz", None)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Unrecognized language code: zzz"


def test_transform_formats_defaults_documents():
    config = {
        "MOVING_IMAGE_REFS": "mov1,mov2",
        "AUDIO_REFS": "audio1,audio2",
        "PHOTOGRAPH_REFS": "photo1,photo2",
    }
    result = transform_formats([], [], [], config)
    assert result == ["documents"]


def test_transform_formats_matching_formats():
    config = {
        "MOVING_IMAGE_REFS": "mov1,mov2",
        "AUDIO_REFS": "audio1,audio2",
        "PHOTOGRAPH_REFS": "photo1,photo2",
    }
    subjects = [
        RecursiveNamespace.from_obj({"ref": "mov1"}),
        RecursiveNamespace.from_obj({"ref": "photo2"}),
    ]
    ancestors = [
        RecursiveNamespace.from_obj({
            "subjects": [RecursiveNamespace.from_obj({"ref": "audio2"})]
        })
    ]
    result = transform_formats([], subjects, ancestors, config)
    assert result == ["documents", "moving image", "audio", "photographs"]


@patch("src.mappings.SourceGroupToGroup.apply")
def test_transform_group(mock_apply):
    value = RecursiveNamespace.from_obj({
        "identifier": "/repositories/2/groups/5"
    })
    group = RecursiveNamespace.from_obj({})
    mock_apply.return_value = group
    result = transform_group(value, "collections")
    assert result is group
    assert result.identifier == (
        f"/collections/{identifier_from_uri(value.identifier)}"
    )
    mock_apply.assert_called_once_with(value)
