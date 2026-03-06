import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.resources.configs import NOTE_TYPE_CHOICES_TRANSFORM
from src.transformers import Transformer

DEFAULT_CONFIG = {
    "SCHEMAS_BASE_DIR": "rac_schemas/schemas",
    "SCHEMA_BASE": "base.json",
    "SCHEMA_AGENT": "agent.json",
    "SCHEMA_COLLECTION": "collection.json",
    "SCHEMA_OBJECT": "object.json",
    "SCHEMA_TERM": "term.json",
    "SUCCESS_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:success",
    "FAILURE_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:failure",
    "SERVICE_NAME": "data_transform",
    "ASSET_BASEURL": "https://assets.example.org",
    "ASSET_BASEURL": "https://assets.example.org",
    "AUDIO_REFS": "/repositories/subjects/1,repositories/subjects/2",
    "MOVING_IMAGE_REFS": "/repositories/subjects/3,repositories/subjects/4",
    "PHOTOGRAPH_REFS": "/repositories/subjects/5",
}


def load_fixture(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class TransformerTest(unittest.TestCase):
    """Transformer tests (fetch_data-style TransformerService)."""

    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures/transformer"
        self.transformer = Transformer(DEFAULT_CONFIG)

    def check_list_counts(self, source, transformed, object_type):
        date_source_key = "dates_of_existence" if object_type.startswith(
            "agent_") else "dates"
        for source_key, transformed_key in [
                ("notes", "notes"), (date_source_key, "dates"), ("extents", "extents")]:
            source_len = (
                len([
                    n for n in source.get(source_key, [])
                    if (n["publish"] and n.get("type", n["jsonmodel_type"].split("_")[-1]) in NOTE_TYPE_CHOICES_TRANSFORM)
                ])
                if source_key == "notes"
                else len(source.get(source_key, []))
            )
            transformed_len = len(transformed.get(transformed_key, []))
            self.assertEqual(
                source_len,
                transformed_len)

    def check_agent_counts(self, source, transformed):
        for source_key, transformed_key in [
                ("agent_contacts", "contacts"), ("names", "names")]:
            source_len = len([n for n in source.get(
                source_key, []) if n.get("publish") is True])
            transformed_len = len(transformed.get(transformed_key, []))
            self.assertEqual(source_len, transformed_len)

    def check_references(self, transformed):
        for key in ["people", "organizations",
                    "families", "terms", "creators", "ancestors"]:
            for obj in transformed.get(key, []):
                for prop in ["identifier", "title", "type"]:
                    self.assertIsNotNone(
                        obj.get(prop),
                        f"{prop} missing from {key} reference in {transformed.get('uri')}")

    def check_uri(self, transformed):
        self.assertIn("uri", transformed)
        self.assertTrue(transformed["uri"].startswith("/"))

    def check_parent(self, transformed):
        if transformed.get("ancestors"):
            self.assertEqual(
                transformed.get("parent"),
                transformed["ancestors"][0]["identifier"])

    def check_group(self, source, transformed):
        group = transformed.get("group")
        self.assertIsNotNone(group, "group missing from transformed")

        if hasattr(group, "to_dict"):
            group = group.to_dict()
        self.assertIsInstance(group, dict)
        self.assertIn("identifier", group)

        import importlib
        mappings_mod = importlib.import_module("src.mappings")
        identifier_from_uri = mappings_mod.identifier_from_uri
        ancestors = source.get("ancestors", []) or []
        if len(ancestors):
            expected = "/collections/{}".format(
                identifier_from_uri(ancestors[-1]["ref"]))
        else:
            expected = transformed.get("uri")
        self.assertEqual(group["identifier"], expected)
        if transformed.get("type") == "agent":
            self.assertEqual(group.get("title"), transformed.get("title"))

    def check_formats(self, transformed):
        if transformed["group"]["identifier"] == "/collections/gfvm2HihpLwCTnKgpDtdhR":
            self.assertIn("audio", transformed.get("formats"))

    def check_component_id(self, source, transformed):
        if source.get("component_id"):
            self.assertEqual(
                transformed["title"],
                "{}, {} {}".format(
                    source["title"],
                    source["level"].capitalize(),
                    source["component_id"]),
            )

    def check_position(self, transformed, object_type):
        if object_type.startswith("archival_object"):
            self.assertIn("position", transformed)

    def check_external_identifiers(self, source, transformed):
        if source.get("external_ids"):
            self.assertIn("external_identifiers", transformed)
            self.assertIsInstance(transformed["external_identifiers"], list)

    def check_files(self, source, transformed):
        if source.get("instances"):
            self.assertIn("files", transformed)
            self.assertIsInstance(transformed["files"], list)

    def make_service(self, mod, config=None):
        config = config or {}
        with patch.object(mod, "get_config", return_value=config):
            return mod.TransformerService(
                "test", "us-east-1", "arn:aws:iam::1:role/Dummy")

    @patch("requests.head")
    def test_object_types(self, mock_head):
        mock_head.return_value = Mock(status_code=200)
        object_types = [
            "agent_person",
            "agent_corporate_entity",
            "agent_family",
            "resource",
            "archival_object",
            "archival_object_collection",
            "subject",
        ]

        for object_type in object_types:
            object_dir = self.fixtures_dir / object_type
            fixture_paths = sorted(object_dir.glob("*.json"))
            for source_path in fixture_paths:
                with self.subTest(object_type=object_type, fixture=source_path.name):
                    source = load_fixture(source_path)
                    from_resource, mapping, _ = self.transformer.get_mapping_classes(
                        object_type)
                    transformed = self.transformer.get_transformed_object(
                        source, from_resource, mapping)

                    self.assertNotIn("online_pending", transformed)
                    self.check_list_counts(source, transformed, object_type)

                    if object_type.startswith("agent_"):
                        self.check_agent_counts(source, transformed)

                    if object_type.startswith("archival_object"):
                        self.check_references(transformed)
                        self.check_uri(transformed)
                        self.check_group(source, transformed)
                        self.check_parent(transformed)
                        self.check_formats(transformed)
                        self.check_component_id(source, transformed)
                        self.check_position(transformed, object_type)
                        self.check_external_identifiers(source, transformed)
                        self.check_files(source, transformed)

    def test_online_pending(self):
        online_dir = self.fixtures_dir / "online_instance"
        if not online_dir.exists():
            self.skipTest(f"Missing fixture directory: {online_dir}")

        cases = [
            ("no_online_instances.json", False, False),
            ("online_instance.json", False, True),
            ("no_online_instances.json", True, False),
            ("online_instance.json", True, False),
            ("unpublished_online_instance.json", False, False),
        ]
        for fixture, online, expected in cases:
            fixture_path = online_dir / fixture
            if not fixture_path.exists():
                self.skipTest(f"Missing fixture: {fixture_path}")
            instances = load_fixture(fixture_path)
            output = self.transformer.get_online_pending(instances, online)
            self.assertEqual(output, expected)

    def mock_ssm_paginator(self, parameters):
        paginator = Mock()
        paginator.paginate.return_value = [{"Parameters": parameters}]
        return paginator

    def test_get_mapping_classes_unsupported_types(self):
        with self.assertRaises(KeyError):
            self.transformer.get_mapping_classes("not_a_real_type")

    def test_remove_keys_from_dict_removes_nested_dollar_keys(self):
        payload = {
            "uri": "/x/1",
            "$": {"should": "be removed"},
            "nested": {"keep": 1, "$": "remove me", "items": [{"a": 1, "$": 2}, {"b": 3}]},
            "lst": ["a", {"$": "x", "c": 4}],
        }
        cleaned = self.transformer.remove_keys_from_dict(
            payload, target_key="$")
        self.assertNotIn("$", cleaned)
        self.assertNotIn("$", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["items"][0], {"a": 1})
        self.assertEqual(cleaned["nested"]["items"][1], {"b": 3})
        self.assertEqual(cleaned["lst"][0], "a")
        self.assertEqual(cleaned["lst"][1], {"c": 4})

    def test_output_object_type_and_es_id(self):
        # known mappings
        self.assertEqual(
            self.transformer.output_object_type("agent_person"),
            "agent")
        self.assertEqual(
            self.transformer.output_object_type("resource"),
            "collection")
        self.assertEqual(
            self.transformer.output_object_type("archival_object"),
            "object")
        self.assertEqual(
            self.transformer.output_object_type("subject"),
            "term")

        # wrong types
        self.assertEqual(self.transformer.output_object_type("agent"), "agent")

        # invalid object type
        with self.assertRaises(KeyError):
            self.transformer.output_object_type("not_real")

        # es_id_from_uri edge cases
        self.assertIsNone(self.transformer.es_id_from_uri(None))
        self.assertIsNone(self.transformer.es_id_from_uri(123))  # non-string
        self.assertEqual(self.transformer.es_id_from_uri("/a/b/123"), "123")
        self.assertEqual(self.transformer.es_id_from_uri("/a/b/123/"), "123")
