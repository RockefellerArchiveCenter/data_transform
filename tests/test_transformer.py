import json
import unittest
from os import getenv
from pathlib import Path
from unittest.mock import ANY, call, patch

import boto3
from moto import mock_aws
from moto.core import DEFAULT_ACCOUNT_ID

from src.mappings import SourceAgentPersonToAgent
from src.resources.source import SourceAgentPerson
from src.transformer import Transformer, lambda_handler

DEFAULT_CONFIG = {
    "SCHEMAS_BASE_DIR": "rac_schemas/schemas",
    "SCHEMA_BASE": "base.json",
    "SCHEMA_AGENT": "agent.json",
    "SCHEMA_COLLECTION": "collection.json",
    "SCHEMA_OBJECT": "object.json",
    "SCHEMA_TERM": "term.json",
    "SNS_ROLE_ARN": "rn:aws:iam::123456789:role/sns-role",
    "SNS_TOPIC_ARN": "arn:aws:sns:us-east-1:000000000000:success",
    "ASSET_BASEURL": "https://assets.example.org",
    "DOWNLOAD_BASEURL": "https://downloads.example.org/files",
    "MANIFEST_BASEURL": "https://manifests.example.org/iiif",
    "AUDIO_REFS": "/repositories/subjects/1,repositories/subjects/2",
    "MOVING_IMAGE_REFS": "/repositories/subjects/3,repositories/subjects/4",
    "PHOTOGRAPH_REFS": "/repositories/subjects/5",
}


def load_fixture(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class LambdaHandlerTests(unittest.TestCase):

    @patch('src.transformer.Transformer.__init__')
    @patch('src.transformer.Transformer.run')
    def test_lambda_handler(self, mock_run, mock_init):
        mock_init.return_value = None
        records = [
            {"body": "{\"uri\": \"1234\"}", "messageAttributes": {
                "object_type": {"stringValue": "archival_object"}}},
            {"body": "{\"uri\": \"4321\"}", "messageAttributes": {
                "object_type": {"stringValue": "resource"}}}
        ]
        lambda_handler({"Records": records}, None)

        mock_init.assert_called_once()
        mock_run.assert_has_calls([
            call("archival_object", {"uri": "1234"}),
            call("resource", {"uri": "4321"})
        ])


class TransformerMethodTests(unittest.TestCase):
    """Transformer tests (fetch_data-style TransformerService)."""

    @patch('src.transformer.get_config')
    def setUp(self, mock_config):
        mock_config.return_value = DEFAULT_CONFIG
        self.fixtures_dir = Path(__file__).parent / "fixtures/transformer"
        self.transformer = Transformer()
        mock_config.assert_called_once_with(
            getenv('ENVIRONMENT'),
            getenv('AWS_REGION'),
            getenv('AWS_SSM_ROLE_ARN'),
            self.transformer.service_name)

    @patch('src.transformer.Transformer.get_mapping_classes')
    @patch('src.transformer.Transformer.get_transformed_object')
    @patch('src.transformer.Transformer.get_online_pending')
    @patch('src.transformer.Transformer.validate_transformed')
    @patch('src.transformer.Transformer.send_success_message')
    @patch('src.transformer.Transformer.send_error_message')
    def test_run(
            self,
            mock_error_message,
            mock_success_message,
            mock_validate,
            mock_online_pending,
            mock_get_transformed,
            mock_mapping):
        transformed_object = {"uri": "12345"}
        mock_mapping.return_value = (
            SourceAgentPerson,
            SourceAgentPersonToAgent,
            self.transformer.config['SCHEMA_AGENT'])
        mock_get_transformed.return_value = transformed_object
        mock_online_pending.return_value = False
        mock_validate.return_value = True

        self.transformer.run('agent_person', {})

        mock_mapping.assert_called_once_with('agent_person')
        mock_get_transformed.assert_called_once_with(
            {}, SourceAgentPerson, SourceAgentPersonToAgent)
        mock_validate.assert_called_once_with(
            transformed_object, self.transformer.config['SCHEMA_AGENT'])
        mock_success_message.assert_called_once_with(
            transformed_object, 'agent_person')
        mock_error_message.assert_not_called()

        # Test exception gets reported
        mock_mapping.side_effect = Exception("foo")
        self.transformer.run('agent_person', {"uri": "54321"})
        mock_error_message.assert_called_once_with(
            ANY, 'agent_person', '75ddpuBHgPf2TmZRhZ2bKR')

    def test_output_object_type_and_es_id(self):
        for input, output in [
                ("agent_person", "agent"),
                ("resource", "collection"),
                ("archival_object", "object"),
                ("subject", "term"),
                ("agent", "agent")]:
            self.assertEqual(
                self.transformer.output_object_type(input), output)

        # invalid object type
        with self.assertRaises(KeyError):
            self.transformer.output_object_type("not_real")

    def test_es_id_from_uri(self):
        self.assertIsNone(self.transformer.es_id_from_uri(None))
        self.assertIsNone(self.transformer.es_id_from_uri(123))  # non-string
        self.assertEqual(self.transformer.es_id_from_uri("/a/b/123"), "123")
        self.assertEqual(self.transformer.es_id_from_uri("/a/b/123/"), "123")

    def test_get_mapping_classes(self):
        self.assertEqual(
            self.transformer.get_mapping_classes('agent_person'),
            (SourceAgentPerson, SourceAgentPersonToAgent, self.transformer.config['SCHEMA_AGENT']))

        # Invalid object type
        with self.assertRaises(KeyError):
            self.transformer.get_mapping_classes("not_a_real_type")

    def test_get_online_pending(self):
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
            instances = load_fixture(fixture_path)
            output = self.transformer.get_online_pending(instances, online)
            self.assertEqual(output, expected)

    @patch('src.mappings.SourceAgentPersonToAgent.apply')
    @patch('src.transformer.Transformer.remove_keys_from_dict')
    def test_get_transformed_object(self, mock_remove_keys, mock_apply):
        source_object = load_fixture(
            self.fixtures_dir / 'agent_person' / '1.json')
        mock_apply.return_value = source_object
        mock_remove_keys.return_value = {}
        output = self.transformer.get_transformed_object(
            source_object, SourceAgentPerson, SourceAgentPersonToAgent)
        self.assertEqual(output, {})
        mock_remove_keys.assert_called_once_with(source_object)
        mock_apply.assert_called_once()

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

    @patch('src.transformer.is_valid')
    def test_validate_transformed(self, mock_is_valid):
        schema_name = 'agent.json'
        base_dir = self.transformer.config["SCHEMAS_BASE_DIR"].rstrip("/")
        schema_base = self.transformer.config.get("SCHEMA_BASE", None)
        with open(Path(base_dir, schema_base), "r", encoding="utf-8") as base_file:
            base_schema = json.load(base_file)
        with open(Path(base_dir, schema_name), "r", encoding="utf-8") as object_file:
            object_schema = json.load(object_file)

        self.transformer.validate_transformed({}, 'agent.json')

        mock_is_valid.assert_called_once_with({}, object_schema, base_schema)

    @patch('src.transformer.is_valid')
    def test_validate_transformed_no_base(self, mock_is_valid):
        schema_name = 'agent.json'
        base_dir = self.transformer.config["SCHEMAS_BASE_DIR"].rstrip("/")
        with open(Path(base_dir, schema_name), "r", encoding="utf-8") as object_file:
            object_schema = json.load(object_file)

        self.transformer.config.pop('SCHEMA_BASE')
        self.transformer.validate_transformed({}, 'agent.json')

        mock_is_valid.assert_called_once_with({}, object_schema, None)


class TransformerSNSTests(unittest.TestCase):

    @patch('src.transformer.get_config')
    def setUp(self, mock_config):
        mock_config.return_value = DEFAULT_CONFIG
        self.transformer = Transformer()

    def set_up_sns(self):
        client = boto3.client('sns', region_name=getenv('AWS_REGION'))
        topic_arn = client.create_topic(
            Name='test-topic.fifo',
            Attributes={
                'FifoTopic': 'true'})['TopicArn']
        self.transformer.config['SNS_TOPIC_ARN'] = topic_arn
        sqs_conn = boto3.resource('sqs', region_name=getenv('AWS_REGION'))
        sqs_conn.create_queue(QueueName="test-queue")
        client.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=f"arn:aws:sqs:us-east-1:{DEFAULT_ACCOUNT_ID}:test-queue",
        )
        queue = sqs_conn.get_queue_by_name(QueueName="test-queue")
        return queue

    @mock_aws
    def test_send_success_message(self):
        queue = self.set_up_sns()
        self.transformer.send_success_message(
            {"identifier": "12345"}, 'collection')
        messages = queue.receive_messages(MaxNumberOfMessages=1)
        message_body = json.loads(messages[0].body)
        self.assertEqual(message_body['Message'], '{"identifier": "12345"}')
        self.assertEqual(
            message_body['MessageAttributes'],
            {'service': {
                'Type': 'String',
                'Value': self.transformer.service_name,
            },
                'requested_action': {
                'Type': 'String',
                'Value': 'index',
            },
                'object_type': {
                'Type': 'String',
                'Value': 'collection',
            },
                'es_id': {
                'Type': 'String',
                'Value': '12345',
            }})

    @mock_aws
    def test_send_error_message(self):
        queue = self.set_up_sns()
        self.transformer.send_error_message(
            Exception('foo'), 'object', '12345')
        messages = queue.receive_messages(MaxNumberOfMessages=1)
        message_body = json.loads(messages[0].body)
        self.assertEqual(message_body['Message'], '')
        self.assertEqual(
            message_body['MessageAttributes'],
            {'service': {
                'Type': 'String',
                'Value': self.transformer.service_name,
            },
                'object_status': {
                'Type': 'String',
                'Value': 'updated',
            },
                'object_type': {
                'Type': 'String',
                'Value': 'object',
            },
                'object_id': {
                'Type': 'String',
                'Value': '12345',
            },
                'outcome': {
                'Type': 'String',
                'Value': 'FAILURE',
            },
                'message': {
                'Type': 'String',
                'Value': 'foo',
            }})
