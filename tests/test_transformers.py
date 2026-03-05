import json
import os
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from src.resources.configs import NOTE_TYPE_CHOICES_TRANSFORM


def load_fixture(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def mk_service(mod, cfg_overrides=None):
    """
    Create a TransformerService without touching AWS/SSM.
    """
    cfg_overrides = cfg_overrides or {}
    with patch.object(mod, "get_config", return_value=cfg_overrides), patch.object(
        mod.mappings_mod, "apply_runtime_config", return_value=None
    ):
        return mod.TransformerService(
            "test", "us-east-1", "arn:aws:iam::1:role/Dummy")


class TransformerTest(unittest.TestCase):
    """Transformer tests (fetch_data-style TransformerService)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        project_root = Path(__file__).resolve().parents[1]
        cls.schemas_dir = project_root / "src" / "schemas"
        if not cls.schemas_dir.exists():
            raise RuntimeError(
                f"Schemas directory not found: {
                    cls.schemas_dir}")

        # Minimal env: service.cfg reads these (env wins)
        os.environ.setdefault("SCHEMAS_BASE_DIR", str(cls.schemas_dir))
        os.environ.setdefault("SCHEMA_BASE", "base.json")
        os.environ.setdefault("SCHEMA_AGENT", "agent.json")
        os.environ.setdefault("SCHEMA_COLLECTION", "collection.json")
        os.environ.setdefault("SCHEMA_OBJECT", "object.json")
        os.environ.setdefault("SCHEMA_TERM", "term.json")
        os.environ.setdefault("SUCCESS_TOPIC_ARN",
                              "arn:aws:sns:us-east-1:000000000000:success")
        os.environ.setdefault("FAILURE_TOPIC_ARN",
                              "arn:aws:sns:us-east-1:000000000000:failure")
        os.environ.setdefault("SERVICE_NAME", "data_transform")
        os.environ.setdefault("ASSET_BASEURL", "https://assets.example.org")

        cls.fixtures_dir = Path(__file__).parent / "fixtures/transformer"

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
                transformed_len,
                f"Found {source_len} {source_key} in source but {
                    transformed_len} {transformed_key} in transformed.",
            )

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
                        f"{prop} missing from {key} reference in {
                            transformed.get('uri')}")

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

    def import_transformers(self):
        import importlib
        importlib.sys.modules.pop("src.transformers", None)
        importlib.sys.modules.pop("src.mappings", None)
        return importlib.import_module("src.transformers")

    def make_service(self, mod, config=None):
        config = config or {}
        with patch.object(mod, "get_config", return_value=config):
            return mod.TransformerService(
                "test", "us-east-1", "arn:aws:iam::1:role/Dummy")

    @patch("requests.head")
    def test_object_types(self, mock_head):
        mock_head.return_value = Mock(status_code=200)

        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()

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

        mock_head.return_value = Mock(status_code=200)
        for fixture, expected in cases:
            fixture_path = online_dir / fixture
            if not fixture_path.exists():
                self.skipTest(f"Missing fixture: {fixture_path}")

            instances = load_fixture(fixture_path)
            output = has_online_instance(
                instances, "/repositories/2/archival_objects/4")
            self.assertEqual(output, expected)

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
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()

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
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()

        sample = {"uri": "/repositories/2/resources/123", "type": "collection"}

        os.environ["SCHEMA_BASE"] = "base.json"
        transformer.validate_transformed(sample, "object.json")
        arg_values = mock_is_valid.call_args[0]
        self.assertTrue(isinstance(arg_values[0], dict))
        self.assertTrue(isinstance(arg_values[1], dict))
        self.assertTrue(isinstance(arg_values[2], dict))

        mock_is_valid.reset_mock()
        os.environ.pop("SCHEMA_BASE", None)
        transformer.validate_transformed(sample, "object.json")
        arg_values = mock_is_valid.call_args[0]
        self.assertTrue(isinstance(arg_values[0], dict))
        self.assertTrue(isinstance(arg_values[1], dict))
        self.assertEqual(arg_values[2], None)

    def mock_ssm_paginator(self, parameters):
        paginator = Mock()
        paginator.paginate.return_value = [{"Parameters": parameters}]
        return paginator

    @patch("boto3.Session")
    def test_get_config_loads_parameters_by_path(self, mock_session):
        os.environ["ENVIRONMENT"] = "test"
        os.environ["AWS_REGION"] = "us-east-1"
        os.environ["SSM_ROLE_ARN"] = "arn:aws:iam::000000000000:role/DummySsmRole"

        ssm_client = Mock()
        ssm_client.get_paginator.return_value = self.mock_ssm_paginator([
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

        with patch.dict("sys.modules", {"aws_assume_role_lib": fake_lib}):
            mod = self.import_transformers()
            cfg = mod.get_config(
                "test",
                "us-east-1",
                os.environ["SSM_ROLE_ARN"],
                service_name="data_transform")

        self.assertEqual(
            cfg["SUCCESS_TOPIC_ARN"],
            "arn:aws:sns:us-east-1:1:success")
        self.assertEqual(
            cfg["FAILURE_TOPIC_ARN"],
            "arn:aws:sns:us-east-1:1:failure")
        self.assertEqual(cfg["SCHEMAS_BASE_DIR"], "/var/task/schemas")

        paginator = ssm_client.get_paginator.return_value
        called_kwargs = paginator.paginate.call_args.kwargs
        self.assertEqual(called_kwargs.get("Path"), "/test/data_transform")
        fake_lib.assume_role.assert_called_with(
            session, os.environ["SSM_ROLE_ARN"])

    def test_service_cfg_env_overrides_ssm(self):
        mod = self.import_transformers()
        os.environ["SUCCESS_TOPIC_ARN"] = "arn:env-success"
        service = self.make_service(
            mod, config={
                "SUCCESS_TOPIC_ARN": "arn:ssm-success"})
        self.assertEqual(service.cfg("SUCCESS_TOPIC_ARN"), "arn:env-success")

    def test_get_config_returns_empty_without_required_env(self):
        mod = self.import_transformers()
        cfg = mod.get_config(
            environment=None,
            aws_region=None,
            ssm_role_arn=None,
            service_name="data_transform")
        self.assertEqual(cfg, {})

    def test_get_mapping_classes_unsupported_types(self):
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()
        with self.assertRaises(KeyError):
            transformer.get_mapping_classes("not_a_real_type")

    def test_remove_keys_from_dict_removes_nested_dollar_keys(self):
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()

        payload = {
            "uri": "/x/1",
            "$": {"should": "be removed"},
            "nested": {"keep": 1, "$": "remove me", "items": [{"a": 1, "$": 2}, {"b": 3}]},
            "lst": ["a", {"$": "x", "c": 4}],
        }
        cleaned = transformer.remove_keys_from_dict(payload, target_key="$")
        self.assertNotIn("$", cleaned)
        self.assertNotIn("$", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["items"][0], {"a": 1})
        self.assertEqual(cleaned["nested"]["items"][1], {"b": 3})
        self.assertEqual(cleaned["lst"][0], "a")
        self.assertEqual(cleaned["lst"][1], {"c": 4})

    def test_assume_role_session_sts(self):
        mod = self.import_transformers()
        session = Mock()
        session.region_name = "us-east-1"
        sts = Mock()
        session.client.return_value = sts
        sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEST",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN"}}

        with patch.object(mod, "boto3") as mock_boto3:
            mock_boto3.Session.return_value = "ASSUMED_SESSION"
            with patch.dict("sys.modules", {"aws_assume_role_lib": None}):
                assumed = mod.assume_role_session(
                    session, "arn:aws:iam::1:role/Dummy")

        self.assertEqual(assumed, "ASSUMED_SESSION")
        sts.assume_role.assert_called_once()
        kwargs = mock_boto3.Session.call_args.kwargs
        self.assertEqual(kwargs["aws_access_key_id"], "AKIA_TEST")
        self.assertEqual(kwargs["region_name"], "us-east-1")

    def test_require_env_raises_when_missing(self):
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        with patch.object(service, "cfg", return_value=""):
            with self.assertRaises(ValueError):
                service.require_env()

    def test_service_publish_calls_sns(self):
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        payload = {"hello": "world"}
        attrs = {
            "service": {
                "DataType": "String",
                "StringValue": "data_transform"}}

        with patch.object(service, "get_sns_client") as mock_get_sns:
            client = Mock()
            mock_get_sns.return_value = client
            service.publish(
                "arn:topic",
                payload,
                message_attributes=attrs,
                message_group_id="g",
                message_deduplication_id="d",
            )
        client.publish.assert_called_once()
        called = client.publish.call_args.kwargs
        self.assertEqual(called["TopicArn"], "arn:topic")
        self.assertEqual(called["MessageAttributes"], attrs)

    def test_publish_result_unknown_status(self):
        mod = self.import_transformers()
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()
        with self.assertRaises(ValueError):
            transformer.publish_result("wat", {"a": 1})

    def test_lambda_handler_partial_failures(self):
        mod = self.import_transformers()

        # Make a service and transformer but avoid AWS and avoid schema work
        service = self.make_service(mod, config={})
        transformer = service.get_transformer()

        with (
            patch.object(mod, "get_service", return_value=service),
            patch.object(
                transformer,
                "process_message",
                side_effect=[
                    None,
                    Exception("boom")]),
            patch.object(transformer, "publish_result") as pr,
        ):
            out = mod.lambda_handler(
                {"Records": [{"messageId": "m1"}, {"messageId": "m2"}]},
                None,
            )
        self.assertEqual(out, {"batchItemFailures": [
                         {"itemIdentifier": "m2"}]})
        pr.assert_called()

    def test_service_get_sns_client_uses_role(self):
        mod = self.import_transformers()
        service = mk_service(mod, cfg_overrides={})

        # force sns role
        with patch.object(service, "cfg", side_effect=lambda k, d="": "arn:role" if k == "SNS_ROLE_ARN" else d), \
                patch.object(mod, "get_client_with_role") as gcr, \
                patch.object(mod.boto3, "client") as direct_client:
            gcr.return_value = MagicMock()
            c1 = service.get_sns_client()
            c2 = service.get_sns_client()

        self.assertIs(c1, c2)
        gcr.assert_called_once()
        direct_client.assert_not_called()

    def test_service_get_sns_client_no_role(self):
        mod = self.import_transformers()
        service = mk_service(mod, cfg_overrides={})

        with patch.object(service, "cfg", side_effect=lambda k, d="": "" if k == "SNS_ROLE_ARN" else d), \
                patch.object(mod, "get_client_with_role") as gcr, \
                patch.object(mod.boto3, "client") as direct_client:
            direct_client.return_value = MagicMock()
            c1 = service.get_sns_client()
            c2 = service.get_sns_client()

        self.assertIs(c1, c2)
        direct_client.assert_called_once_with("sns", region_name="us-east-1")
        gcr.assert_not_called()

    def test_output_object_type_and_es_id(self):
        mod = self.import_transformers()
        svc = MagicMock()
        t = mod.Transformer(svc)

        # known mappings
        self.assertEqual(t.output_object_type("agent_person"), "agent")
        self.assertEqual(t.output_object_type("resource"), "collection")
        self.assertEqual(t.output_object_type("archival_object"), "object")
        self.assertEqual(t.output_object_type("subject"), "term")

        # wrong types
        self.assertEqual(t.output_object_type("agent"), "agent")

        # invalid object type
        with self.assertRaises(KeyError):
            t.output_object_type("not_real")

        # es_id_from_uri edge cases
        self.assertIsNone(t.es_id_from_uri(None))
        self.assertIsNone(t.es_id_from_uri(123))  # non-string
        self.assertEqual(t.es_id_from_uri("/a/b/123"), "123")
        self.assertEqual(t.es_id_from_uri("/a/b/123/"), "123")

    def test_build_indexer_payload_no_uri(self):
        mod = self.import_transformers()
        svc = MagicMock()
        t = mod.Transformer(svc)

        # no uri included
        with self.assertRaises(ValueError):
            t.build_indexer_payload(
                input_object_type="resource",
                source_data={},              # no uri
                transformed={"title": "x"},  # no uri
            )

    def test_run_wraps_errors(self):
        mod = self.import_transformers()
        svc = MagicMock()
        t = mod.Transformer(svc)

        # ValidationError for wrong path
        with patch.object(t, "get_mapping_classes", return_value=(None, None, "x.json")), \
                patch.object(t, "get_transformed_object", return_value={"uri": "/x/1"}), \
                patch.object(t, "get_online_pending", return_value=False), \
                patch.object(t, "validate_transformed", side_effect=JsonSchemaValidationError("bad")):
            with self.assertRaises(mod.TransformError) as ctx:
                t.run("resource", {"uri": "/x/1"})
            self.assertIn("Transformed data is invalid", str(ctx.exception))

        # Generic exception wrong path
        with patch.object(t, "get_mapping_classes", side_effect=Exception("boom")):
            with self.assertRaises(mod.TransformError) as ctx:
                t.run("resource", {"uri": "/repositories/2/resources/999"})
            self.assertIn("Error transforming resource", str(ctx.exception))

    def test_process_message_validation_failures(self):
        mod = self.import_transformers()
        svc = MagicMock()
        # cfg must return SERVICE_NAME for success path
        svc.cfg.side_effect = lambda k, d="": d
        t = mod.Transformer(svc)

        # invalid JSON
        with self.assertRaises(ValueError):
            t.process_message(
                {"body": "not-json", "messageAttributes": {"objectType": {"stringValue": "resource"}}})

        # missing object_type in both attrs and body
        with self.assertRaises(ValueError):
            t.process_message(
                {"body": json.dumps({"data": {"uri": "/x/1"}}), "messageAttributes": {}})

        # source_data not dict (data is list)
        with self.assertRaises(ValueError):
            t.process_message({
                "body": json.dumps({"objectType": "resource", "data": ["not", "a", "dict"]}),
                "messageAttributes": {},
            })

    def test_publish_result_routes(self):
        mod = self.import_transformers()
        svc = MagicMock()
        svc.cfg.side_effect = lambda k, d="": {
            "SUCCESS_TOPIC_ARN": "arn:success",
            "FAILURE_TOPIC_ARN": "arn:failure",
        }.get(k, d)
        svc.publish = MagicMock()

        t = mod.Transformer(svc)
        payload = {"objects": [{"es_id": "1", "data": {"uri": "/x/1"}}]}

        t.publish_result("success", payload, subject="ok")
        svc.publish.assert_called()
        self.assertEqual(svc.publish.call_args.args[0], "arn:success")

        svc.publish.reset_mock()
        t.publish_result("failure", {"error": "x"}, subject="nope")
        self.assertEqual(svc.publish.call_args.args[0], "arn:failure")

        with self.assertRaises(ValueError):
            t.publish_result("wat", payload)

    def test_get_service_caches(self):
        mod = self.import_transformers()

        # reset module global
        mod.service = None

        with patch.object(mod, "TransformerService") as TS:
            inst = MagicMock()
            TS.return_value = inst
            with patch.dict(os.environ, {"ENVIRONMENT": "dev", "AWS_REGION": "us-east-1", "SSM_ROLE_ARN": "arn:ssm"}):
                s1 = mod.get_service()
                s2 = mod.get_service()

        self.assertIs(s1, s2)
        TS.assert_called_once()
