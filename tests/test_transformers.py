import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.resources.configs import NOTE_TYPE_CHOICES_TRANSFORM


def load_fixture(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class TransformerTest(unittest.TestCase):
    """Transformer tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Use the schemas.
        project_root = Path(__file__).resolve().parents[1]
        cls.schemas_dir = project_root / "src" / "schemas"
        if not cls.schemas_dir.exists():
            raise RuntimeError(
                f"Schemas directory not found: {
                    cls.schemas_dir}")

        os.environ.setdefault("SCHEMAS_BASE_DIR", str(cls.schemas_dir))
        os.environ.setdefault("SCHEMA_BASE", "base.json")
        os.environ.setdefault("SCHEMA_AGENT", "agent.json")
        os.environ.setdefault("SCHEMA_COLLECTION", "collection.json")
        os.environ.setdefault("SCHEMA_OBJECT", "object.json")
        os.environ.setdefault("SCHEMA_TERM", "term.json")
        os.environ.setdefault("SNS_TOPIC_ARN",
                              "arn:aws:sns:us-east-1:000000000000:dummy")

        os.environ.setdefault("ASSET_BASEURL", "https://assets.example.org")

        # Resolve fixtures directory (data_transform/tests/fixtures).
        cls.fixtures_dir = Path(__file__).parent / "fixtures/transformer"

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

    def check_list_counts(self, source, transformed, object_type):
        """Checks that lists of items are the same on source and data objects.

        Ensures that only notes in NOTE_TYPE_CHOICES_TRANSFORM are transformed.
        This includes notes in agents, which do not have a type field, so the
        jsonmodel_type field must be checked instead.
        """
        date_source_key = "dates_of_existence" if object_type.startswith(
            "agent_") else "dates"
        for source_key, transformed_key in [("notes", "notes"),
                                            (date_source_key, "dates"),
                                            ("extents", "extents")]:
            source_len = len(
                [n for n in source.get(source_key, []) if (n["publish"] and n.get(
                    "type", n["jsonmodel_type"].split("_")[-1]) in NOTE_TYPE_CHOICES_TRANSFORM)]
            ) if source_key == "notes" else len(source.get(source_key, []))
            transformed_len = len(transformed.get(transformed_key, []))
            self.assertEqual(source_len, transformed_len,
                             "Found {} {} in source but {} {} in transformed.".format(
                                 source_len, source_key, transformed_len, transformed_key))

    def check_agent_counts(self, source, transformed):
        """Checks that agent names and contacts are the same on source and data objects."""
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
                        f"{prop} missing from {key} reference in {
                            transformed.get('uri')}",
                    )

    def check_uri(self, transformed):
        """Checks that object has uri field and it is an ArchivesSpace uri."""
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

        # Group can be an Odin resource or a dict
        if hasattr(group, "to_dict"):
            group = group.to_dict()
        self.assertIsInstance(
            group, dict, f"Expected group dict, got {type(group)}")
        self.assertIn("identifier", group)

        import importlib
        mappings_mod = importlib.import_module("src.mappings")
        identifier_from_uri = mappings_mod.identifier_from_uri
        ancestors = source.get("ancestors", []) or []
        if len(ancestors):
            expected = "/collections/{}".format(
                identifier_from_uri(ancestors[-1]["ref"])
            )
        else:
            expected = transformed.get("uri")
        self.assertEqual(group["identifier"], expected)
        if transformed.get("type") == "agent":
            self.assertEqual(group.get("title"), transformed.get("title"))

    def check_formats(self, transformed):
        """Cary Reich papers have `Sound recordings` as a subject term at the top
        level, so all objects from this collection should include `audio` in the
        formats list.
        """
        if transformed["group"]["identifier"] == "/collections/gfvm2HihpLwCTnKgpDtdhR":
            self.assertIn("audio", transformed.get("formats"))

    def check_component_id(self, source, transformed):
        if source.get("component_id"):
            self.assertEqual(
                transformed["title"],
                "{}, {} {}".format(
                    source["title"],
                    source["level"].capitalize(),
                    source["component_id"]))

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

    @patch("requests.head")
    def test_online_instance(self, mock_head):
        self.import_transformers()
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
            output = has_online_instance(
                instances, "/repositories/2/archival_objects/4")
            self.assertEqual(output, expected)

        # 404 => always false
        mock_head.return_value = Mock(status_code=404)
        for fixture, _expected in cases:
            fixture_path = online_dir / fixture
            if not fixture_path.exists():
                self.skipTest(f"Missing fixture: {fixture_path}")

            instances = load_fixture(fixture_path)
            output = has_online_instance(
                instances, "/repositories/2/archival_objects/4")
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

    @patch("rac_schema_validator.is_valid")
    def test_validate_transformed(self, mock_is_valid):
        """validate_transformed loads schemas from src/schemas and passes them to is_valid."""
        mod = self.import_transformers()
        transformer = mod.Transformer()

        sample = {"uri": "/repositories/2/resources/123", "type": "collection"}

        # With base schema configured, base_schema is passed as a dict.
        os.environ["SCHEMA_BASE"] = "base.json"
        transformer.validate_transformed(sample, "object.json")
        arg_values = mock_is_valid.call_args[0]
        self.assertTrue(isinstance(arg_values[0], dict))
        self.assertTrue(isinstance(arg_values[1], dict))
        self.assertTrue(isinstance(arg_values[2], dict))

        # Without base schema configured, base_schema is None.
        mock_is_valid.reset_mock()
        os.environ.pop("SCHEMA_BASE", None)
        transformer.validate_transformed(sample, "object.json")
        arg_values = mock_is_valid.call_args[0]
        self.assertTrue(isinstance(arg_values[0], dict))
        self.assertTrue(isinstance(arg_values[1], dict))
        self.assertEqual(arg_values[2], None)

    def _mock_ssm_paginator(self, parameters):
        """Helper to build a mock paginator result for get_parameters_by_path."""
        paginator = Mock()
        paginator.paginate.return_value = [{"Parameters": parameters}]
        return paginator

    @patch("boto3.Session")
    def test_get_config_loads_parameters_by_path(self, mock_session):
        os.environ["ENVIRONMENT"] = "test"
        os.environ["AWS_REGION"] = "us-east-1"
        os.environ["SSM_ROLE_ARN"] = "arn:aws:iam::000000000000:role/DummySsmRole"

        ssm_client = Mock()
        ssm_client.get_paginator.return_value = self._mock_ssm_paginator([
            {"Name": "/test/data_transform/SUCCESS_TOPIC_ARN",
             "Value": "arn:aws:sns:us-east-1:1:success"},
            {"Name": "/test/data_transform/FAILURE_TOPIC_ARN",
             "Value": "arn:aws:sns:us-east-1:1:failure"},
            {"Name": "/test/data_transform/SCHEMAS_BASE_DIR",
             "Value": "/var/task/schemas"},
        ])

        session = Mock()
        mock_session.return_value = session

        assumed_session = Mock()
        assumed_session.client.return_value = ssm_client

        fake_lib = types.SimpleNamespace()
        fake_lib.assume_role = Mock(return_value=assumed_session)

        # IMPORTANT: patch sys.modules BEFORE importing transformers/mappings
        with patch.dict("sys.modules", {"aws_assume_role_lib": fake_lib}):
            mod = self.import_transformers()

            cfg = mod.get_config(
                environment=os.environ["ENVIRONMENT"],
                aws_region=os.environ["AWS_REGION"],
                ssm_role_arn=os.environ["SSM_ROLE_ARN"],
                service_name="data_transform",
            )

        self.assertEqual(
            cfg["SUCCESS_TOPIC_ARN"],
            "arn:aws:sns:us-east-1:1:success")
        self.assertEqual(
            cfg["FAILURE_TOPIC_ARN"],
            "arn:aws:sns:us-east-1:1:failure")
        self.assertEqual(cfg["SCHEMAS_BASE_DIR"], "/var/task/schemas")

        paginator = ssm_client.get_paginator.return_value
        paginator.paginate.assert_called()
        called_kwargs = paginator.paginate.call_args.kwargs
        self.assertEqual(called_kwargs.get("Path"), "/test/data_transform")

        fake_lib.assume_role.assert_called_with(
            session, os.environ["SSM_ROLE_ARN"])
        self.assertGreaterEqual(fake_lib.assume_role.call_count, 1)

    @patch("boto3.Session")
    def test_cfg_env_overrides_ssm(self, mock_session):
        os.environ["ENVIRONMENT"] = "test"
        os.environ["AWS_REGION"] = "us-east-1"
        os.environ["SSM_ROLE_ARN"] = "arn:aws:iam::000000000000:role/DummySsmRole"
        os.environ["SUCCESS_TOPIC_ARN"] = "arn:aws:sns:us-east-1:999:env-success"

        ssm_client = Mock()
        ssm_client.get_paginator.return_value = self._mock_ssm_paginator([
            {"Name": "/test/data_transform/SUCCESS_TOPIC_ARN",
             "Value": "arn:aws:sns:us-east-1:1:ssm-success"},
        ])

        session = Mock()
        mock_session.return_value = session

        assumed_session = Mock()
        assumed_session.client.return_value = ssm_client

        fake_lib = types.SimpleNamespace()
        fake_lib.assume_role = Mock(return_value=assumed_session)

        # Patch before import so mappings’ import-time ENV load doesn’t hit STS
        # fallback
        with patch.dict("sys.modules", {"aws_assume_role_lib": fake_lib}):
            mod = self.import_transformers()

            # Recompute CONFIG deterministically for this test
            mod.CONFIG = mod.get_config(
                environment=os.environ["ENVIRONMENT"],
                aws_region=os.environ["AWS_REGION"],
                ssm_role_arn=os.environ["SSM_ROLE_ARN"],
                service_name="data_transform",
            )

        value = mod.cfg("SUCCESS_TOPIC_ARN")
        self.assertEqual(value, "arn:aws:sns:us-east-1:999:env-success")

    def test_get_config_returns_empty_without_required_env(self):
        """If required env vars are missing, get_config should return {} and not attempt AWS calls."""
        # Clear required vars
        os.environ.pop("ENVIRONMENT", None)
        os.environ.pop("AWS_REGION", None)
        os.environ.pop("AWS_DEFAULT_REGION", None)
        os.environ.pop("SSM_ROLE_ARN", None)

        mod = self.import_transformers()
        cfg = mod.get_config(
            environment=None,
            aws_region=None,
            ssm_role_arn=None,
            service_name="data_transform")
        self.assertEqual(cfg, {})

    def test_get_mapping_classes_unsupported_type_raises(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()
        with self.assertRaises(KeyError):
            transformer.get_mapping_classes("not_a_real_type")

    def test_remove_keys_from_dict_removes_nested_dollar_keys(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()

        payload = {
            "uri": "/x/1",
            "$": {"should": "be removed"},
            "nested": {
                "keep": 1,
                "$": "remove me",
                "items": [{"a": 1, "$": 2}, {"b": 3}],
            },
            "lst": ["a", {"$": "x", "c": 4}],
        }
        cleaned = transformer.remove_keys_from_dict(payload, target_key="$")

        self.assertNotIn("$", cleaned)
        self.assertNotIn("$", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["items"][0], {"a": 1})
        self.assertEqual(cleaned["nested"]["items"][1], {"b": 3})
        self.assertEqual(cleaned["lst"][0], "a")
        self.assertEqual(cleaned["lst"][1], {"c": 4})

    def test_assume_role_session_falls_back_to_sts(self):
        mod = self.import_transformers()

        session = Mock()
        session.region_name = "us-east-1"
        sts = Mock()
        session.client.return_value = sts
        sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEST",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
            }
        }
        with patch.object(mod, "boto3") as mock_boto3:
            mock_boto3.Session.return_value = "ASSUMED_SESSION"
            with patch.dict("sys.modules", {"aws_assume_role_lib": None}):
                assumed = mod.assume_role_session(
                    session, "arn:aws:iam::1:role/Dummy")

        self.assertEqual(assumed, "ASSUMED_SESSION")
        sts.assume_role.assert_called_once()
        mock_boto3.Session.assert_called_once()
        kwargs = mock_boto3.Session.call_args.kwargs
        self.assertEqual(kwargs["aws_access_key_id"], "AKIA_TEST")
        self.assertEqual(kwargs["aws_secret_access_key"], "SECRET")
        self.assertEqual(kwargs["aws_session_token"], "TOKEN")
        self.assertEqual(kwargs["region_name"], "us-east-1")

    def test_require_env_raises_when_missing(self):
        mod = self.import_transformers()
        with patch.object(mod, "SUCCESS_TOPIC_ARN", ""), patch.object(mod, "FAILURE_TOPIC_ARN", ""), patch.object(mod, "SCHEMAS_BASE_DIR", ""):
            with self.assertRaises(ValueError) as ctx:
                mod.require_env()
        self.assertIn(
            "Missing required environment variables", str(
                ctx.exception))

    def test_publish_calls_sns_and_truncates_subject(self):
        mod = self.import_transformers()
        long_subject = "x" * 200
        payload = {"hello": "world"}

        with patch.object(mod.sns, "publish") as mock_publish:
            mod.publish("arn:topic", payload, subject=long_subject)

        mock_publish.assert_called_once()
        called = mock_publish.call_args.kwargs
        self.assertEqual(called["TopicArn"], "arn:topic")
        self.assertTrue(isinstance(called["Message"], str))
        self.assertEqual(len(called["Subject"]), 100)

    def test_publish_result_unknown_status_raises(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()
        with self.assertRaises(ValueError):
            transformer.publish_result("wat", {"a": 1})

    def test_process_message_parses_object_type_from_attributes_and_body(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()
        transformer.run = Mock(
            return_value={
                "uri": "/subjects/1",
                "type": "term"})
        transformer.online_pending = True
        transformer.publish_result = Mock()
        record = {
            "messageId": "m1",
            "body": json.dumps({"data": {"uri": "/subjects/1"}, "object_type": "subject"}),
            "messageAttributes": {
                "objectType": {"stringValue": "subject"},
                "object_type": {"stringValue": "resource"},
            },
        }
        out = transformer.process_message(record)
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["message_id"], "m1")
        self.assertEqual(out["object_type"], "subject")
        transformer.run.assert_called_once_with(
            "subject", {"uri": "/subjects/1"})
        transformer.publish_result.assert_called_once()
        self.assertIn("message_attributes", out)

    def test_process_message_handles_non_json_body_missing_object_type(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()
        record = {
            "messageId": "m2",
            "body": "this is not json",
            "messageAttributes": {}}
        with self.assertRaises(ValueError) as ctx:
            transformer.process_message(record)
        self.assertIn("Missing object_type", str(ctx.exception))

    def test_process_message_rejects_non_dict_source_data(self):
        mod = self.import_transformers()
        transformer = mod.Transformer()
        record = {
            "messageId": "m3",
            "body": json.dumps({"object_type": "subject", "data": [1, 2, 3]}),
            "messageAttributes": {},
        }
        with self.assertRaises(ValueError) as ctx:
            transformer.process_message(record)
        self.assertIn("Source data must be a JSON object", str(ctx.exception))

    def test_get_transformer_is_singleton(self):
        mod = self.import_transformers()
        mod.transformer = None
        t1 = mod.get_transformer()
        t2 = mod.get_transformer()
        self.assertIs(t1, t2)

    def test_lambda_handler_returns_batch_item_failures(self):
        mod = self.import_transformers()

        fake_transformer = Mock()

        def _proc(record):
            if record.get("messageId") == "bad":
                raise RuntimeError("boom")
            return {"ok": True}

        fake_transformer.process_message.side_effect = _proc
        fake_transformer.publish_result = Mock()

        with patch.object(mod, "get_transformer", return_value=fake_transformer):
            event = {
                "Records": [
                    {"messageId": "good", "body": "{}"},
                    {"messageId": "bad", "body": "{}"},
                ]
            }
            out = mod.lambda_handler(event, context=None)

        self.assertEqual(out["batchItemFailures"], [{"itemIdentifier": "bad"}])
        fake_transformer.publish_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
