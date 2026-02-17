import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from src.resources.configs import NOTE_TYPE_CHOICES_TRANSFORM


def load_fixture(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class TransformerTest(unittest.TestCase):
    """Transformer tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create a temporary schema directory so validate_transformed can open files.
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.schemas_dir = Path(cls._tmpdir.name)
        for name in [
            "base.json",
            "agent.json",
            "collection.json",
            "object.json",
            "term.json",
        ]:
            (cls.schemas_dir / name).write_text("{}", encoding="utf-8")

        os.environ.setdefault("SCHEMAS_BASE_DIR", str(cls.schemas_dir))
        os.environ.setdefault("SCHEMA_BASE", "base.json")
        os.environ.setdefault("SCHEMA_AGENT", "agent.json")
        os.environ.setdefault("SCHEMA_COLLECTION", "collection.json")
        os.environ.setdefault("SCHEMA_OBJECT", "object.json")
        os.environ.setdefault("SCHEMA_TERM", "term.json")
        os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:dummy")

        os.environ.setdefault("ASSET_BASEURL", "https://assets.example.org")

        # Resolve fixtures directory (data_transform/tests/fixtures).
        cls.fixtures_dir = Path(__file__).parent / "fixtures/transformer"

    @classmethod
    def tearDownClass(cls):
        try:
            cls._tmpdir.cleanup()
        finally:
            super().tearDownClass()

    def check_list_counts(self, source, transformed, object_type):
        """Checks that lists of items are the same on source and data objects.

        Ensures that only notes in NOTE_TYPE_CHOICES_TRANSFORM are transformed.
        This includes notes in agents, which do not have a type field, so the
        jsonmodel_type field must be checked instead.
        """
        date_source_key = "dates_of_existence" if object_type.startswith("agent_") else "dates"
        for source_key, transformed_key in [("notes", "notes"),
                                            (date_source_key, "dates"),
                                            ("extents", "extents")]:
            source_len = len(
                [n for n in source.get(source_key, []) if (n["publish"] and n.get("type", n["jsonmodel_type"].split("_")[-1]) in NOTE_TYPE_CHOICES_TRANSFORM)]
            ) if source_key == "notes" else len(source.get(source_key, []))
            transformed_len = len(transformed.get(transformed_key, []))
            self.assertEqual(source_len, transformed_len,
                             "Found {} {} in source but {} {} in transformed.".format(
                                 source_len, source_key, transformed_len, transformed_key))

    def check_agent_counts(self, source, transformed):
        """Checks that agent names and contacts are the same on source and data objects."""
        for source_key, transformed_key in [("agent_contacts", "contacts"), ("names", "names")]:
            source_len = len([n for n in source.get(source_key, []) if n.get("publish") is True])
            transformed_len = len(transformed.get(transformed_key, []))
            self.assertEqual(source_len, transformed_len)

    def check_references(self, transformed):
        """Checks that object has references and they are in correct formats."""
        self.assertIn("references", transformed)
        self.assertIsInstance(transformed["references"], list)

    def check_uri(self, transformed):
        """Checks that object has uri field and it is an ArchivesSpace uri."""
        self.assertIn("uri", transformed)
        self.assertTrue(transformed["uri"].startswith("/"))

    def check_parent(self, transformed):
        """Checks that object has parent and that it is ArchivesSpace uri."""
        self.assertIn("parent", transformed)
        self.assertTrue(transformed["parent"].startswith("/"))

    def check_group(self, source, transformed):
        """Checks that correct group is assigned based on finding aid."""
        if source.get("finding_aid", {}).get("title"):
            self.assertEqual(transformed.get("group"), "finding_aid")
        else:
            self.assertEqual(transformed.get("group"), "default")

    def check_formats(self, transformed):
        """Checks that object has formats list."""
        self.assertIn("formats", transformed)
        self.assertIsInstance(transformed["formats"], list)

    def check_component_id(self, source, transformed):
        """Checks that object has component_id if it exists on the source."""
        if source.get("component_id"):
            self.assertIn("component_id", transformed)
            self.assertEqual(source["component_id"], transformed["component_id"])

    def check_position(self, transformed, object_type):
        """Checks that object has a position field for archival objects."""
        if object_type.startswith("archival_object"):
            self.assertIn("position", transformed)

    def check_external_identifiers(self, source, transformed):
        """Checks external_identifiers are present and in correct format."""
        if source.get("external_ids"):
            self.assertIn("external_identifiers", transformed)
            self.assertIsInstance(transformed["external_identifiers"], list)

    def check_files(self, source, transformed):
        """Checks file list exists when source has instances."""
        if source.get("instances"):
            self.assertIn("files", transformed)
            self.assertIsInstance(transformed["files"], list)

    def import_transformers(self):
        """Import src.transformers after env vars are set."""
        import importlib
        if "src.transformers" in importlib.sys.modules:
            del importlib.sys.modules["src.transformers"]
        if "src.mappings" in importlib.sys.modules:
            del importlib.sys.modules["src.mappings"]

        mod = importlib.import_module("src.transformers")
        return mod

    @patch("requests.head")
    def test_object_types(self, mock_head):
        """Test that core object types transform and preserve key invariants."""
        mock_head.return_value = Mock(status_code=200)

        mod = self.import_transformers()
        transformer = mod.Transformer()

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

            if not object_dir.exists():
                self.skipTest(f"Missing fixture directory: {object_dir}")

            fixture_paths = sorted(object_dir.glob("*.json"))

            if not fixture_paths:
                self.skipTest(f"No fixtures found in: {object_dir}")

            for source_path in fixture_paths:
                with self.subTest(object_type=object_type, fixture=source_path.name):
                    source = load_fixture(source_path)
                    transformed = transformer.run(object_type, source)

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

    @patch("requests.head")
    def test_online_instance(self, mock_head):
        mod = self.import_transformers()

        import importlib
        mappings_mod = importlib.import_module("src.mappings")
        has_online_instance = mappings_mod.has_online_instance

        online_dir = self.fixtures_dir / "online_instance"

        if not online_dir.exists():
            self.skipTest(f"Missing fixture directory: {online_dir}")

        cases = [
            ("no_online_instances.json", False),
            ("online_instance.json", True),
            ("multiple_instances.json", True),
        ]

        # 200 => evaluate normally
        mock_head.return_value = Mock(status_code=200)
        for fixture, expected in cases:
            fixture_path = online_dir / fixture
            if not fixture_path.exists():
                self.skipTest(f"Missing fixture: {fixture_path}")

            instances = load_fixture(fixture_path)
            output = has_online_instance(instances, "/repositories/2/archival_objects/4")
            self.assertEqual(output, expected)

        # 404 => always false
        mock_head.return_value = Mock(status_code=404)
        for fixture, _expected in cases:
            fixture_path = online_dir / fixture
            if not fixture_path.exists():
                self.skipTest(f"Missing fixture: {fixture_path}")

            instances = load_fixture(fixture_path)
            output = has_online_instance(instances, "/repositories/2/archival_objects/4")
            self.assertEqual(output, False)

    def test_online_pending(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()

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
            output = transformer.get_online_pending(instances, online)
            self.assertEqual(output, expected)

    def test_validate_transformed(self):
        """Test that validate_transformed loads schemas and calls is_valid."""
        mod = self.import_transformers()
        transformer = mod.Transformer()

        sample = {"uri": "/repositories/2/resources/123", "type": "collection"}

        with patch.object(mod, "is_valid") as mock_is_valid:
            transformer.validate_transformed(sample, mod.SCHEMAS["collection"])
            self.assertTrue(mock_is_valid.called)


if __name__ == "__main__":
    unittest.main()
