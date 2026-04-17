import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.transformer import Transformer

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


class TransformerTests(unittest.TestCase):
    """Transformer tests (fetch_data-style TransformerService)."""

    @patch('src.transformer.get_config')
    def setUp(self, mock_config):
        mock_config.return_value = DEFAULT_CONFIG
        self.fixtures_dir = Path(__file__).parent / "fixtures/transformer"
        self.transformer = Transformer()

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
                    from_resource, mapping, schema_name = self.transformer.get_mapping_classes(object_type)
                    transformed = self.transformer.get_transformed_object(
                        source, from_resource, mapping)
                    self.transformer.validate_transformed(transformed, schema_name)
