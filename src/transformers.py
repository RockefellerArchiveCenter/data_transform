import json
import logging
import os
import traceback
from os.path import join
from pathlib import Path

import boto3
from jsonschema.exceptions import ValidationError
from odin.codecs import json_codec
from rac_schema_validator import is_valid

from . import mappings as mappings_mod
from .mappings import (SourceAgentCorporateEntityToAgent,
                       SourceAgentFamilyToAgent, SourceAgentPersonToAgent,
                       SourceArchivalObjectToCollection,
                       SourceArchivalObjectToObject,
                       SourceResourceToCollection, SourceSubjectToTerm)
from .resources.source import (SourceAgentCorporateEntity, SourceAgentFamily,
                               SourceAgentPerson, SourceArchivalObject,
                               SourceResource, SourceSubject)


def assume_role_session(session, role_arn):
    """Return a boto3.Session authenticated via role assumption."""
    try:
        from aws_assume_role_lib import assume_role
        return assume_role(session, role_arn)
    except Exception:
        sts = session.client("sts")
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="data_transform_ssm",
        )
        creds = resp["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=session.region_name,
        )


def get_client_with_role(resource, aws_region, role_arn):
    """Get a boto3 client authenticated with a specific IAM role."""
    session = boto3.Session(region_name=aws_region)
    assumed = assume_role_session(session, role_arn) if role_arn else session
    return assumed.client(resource)


def get_config(environment, aws_region, ssm_role_arn,
               service_name="data_transform"):
    """Fetch config values from SSM Parameter Store by path.

    /{environment}/{service_name}/PARAM_NAME -> {PARAM_NAME: value}
    """
    ssm_parameter_path = f"/{environment}/{service_name}"
    configuration = {}
    if not environment or not aws_region or not ssm_role_arn:
        return configuration

    ssm_client = get_client_with_role("ssm", aws_region, ssm_role_arn)
    try:
        paginator = ssm_client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(
                Path=ssm_parameter_path, Recursive=True, WithDecryption=True):
            for entry in page.get("Parameters", []):
                name = entry.get("Name") or ""
                key = name.split("/")[-1] if name else None
                if key:
                    configuration[key] = entry.get("Value")
    except BaseException:
        logging.error("Error loading config from SSM.")
        traceback.print_exc()
    return configuration


class TransformError(Exception):
    pass


class Transformer:
    """Loads config from SSM in __init__.

    Mappings are configured via `mappings.apply_runtime_config` so mapping
    helpers (formats, has_online_asset, etc.) use runtime config.
    """

    def __init__(self, environment, aws_region, ssm_role_arn):
        self.service_name = "data_transform"
        self.aws_region = aws_region
        self.ssm_role_arn = ssm_role_arn
        self.environment = environment
        self.config = self.get_config(environment)
        mappings_mod.apply_runtime_config(self.config, os.environ)

        self._sns_client = None
        self.transformer = None

    def get_config(self, environment):
        return get_config(environment, self.aws_region,
                          self.ssm_role_arn, service_name=self.service_name)

    def cfg(self, name, default=""):
        """Env wins, then SSM config, then default."""
        val = os.environ.get(name)
        if val is not None and str(val).strip() != "":
            return str(val)
        v2 = self.config.get(name)
        if v2 is not None and str(v2).strip() != "":
            return str(v2)
        return default

    def require_env(self):
        """Validate required configuration values."""
        missing = []
        for name in [
            "SUCCESS_TOPIC_ARN",
            "FAILURE_TOPIC_ARN",
            "SCHEMAS_BASE_DIR",
            "SCHEMA_AGENT",
            "SCHEMA_COLLECTION",
            "SCHEMA_OBJECT",
            "SCHEMA_TERM",
        ]:
            if not self.cfg(name, ""):
                missing.append(name)
        if missing:
            raise ValueError(
                "Missing required environment variables: "
                + ", ".join(missing))

    def get_sns_client(self):
        """Return SNS client."""
        if self._sns_client is None:
            sns_role_arn = self.cfg("SNS_ROLE_ARN", "")
            region = self.aws_region or "us-east-1"
            if sns_role_arn:
                self._sns_client = get_client_with_role(
                    "sns", region, sns_role_arn)
            else:
                self._sns_client = boto3.client("sns", region_name=region)
        return self._sns_client

    def publish(
        self,
        topic_arn,
        payload,
        message_attributes,
        message_group_id,
        message_deduplication_id,
        subject=None,
    ):
        self.get_sns_client().publish(
            TopicArn=topic_arn,
            Message=json.dumps(payload, default=str),
            MessageAttributes=message_attributes or {},
            MessageGroupId=str(message_group_id),
            MessageDeduplicationId=str(message_deduplication_id),
            Subject=subject if subject else None,
        )

    def output_object_type(self, input_object_type):
        if input_object_type in (
                "agent_person", "agent_family", "agent_corporate_entity"):
            return "agent"
        if input_object_type in ("resource", "archival_object_collection"):
            return "collection"
        if input_object_type == "archival_object":
            return "object"
        if input_object_type == "subject":
            return "term"
        if input_object_type in ("agent", "collection", "object", "term"):
            return input_object_type
        raise KeyError(f"Unsupported object_type: {input_object_type}")

    def es_id_from_uri(self, uri):
        if not uri or not isinstance(uri, str):
            return None
        return uri.rstrip("/").split("/")[-1] or None

    def build_indexer_payload(
            self, input_object_type, source_data, transformed):
        indexer_object_type = self.output_object_type(input_object_type)
        data = dict(transformed)
        data.setdefault("uri", source_data.get("uri"))
        data["object_type"] = indexer_object_type
        es_id = self.es_id_from_uri(data.get("uri"))
        if not es_id:
            raise ValueError("Cannot derive es_id from transformed uri")
        return {"objects": [{"es_id": es_id, "data": data}]}

    def get_mapping_classes(self, object_type):
        schema_agent = self.service.cfg("SCHEMA_AGENT", "agent.json")
        schema_collection = self.service.cfg(
            "SCHEMA_COLLECTION", "collection.json")
        schema_object = self.service.cfg("SCHEMA_OBJECT", "object.json")
        schema_term = self.service.cfg("SCHEMA_TERM", "term.json")

        type_map = {
            "agent_person": (SourceAgentPerson, SourceAgentPersonToAgent, schema_agent),
            "agent_corporate_entity": (SourceAgentCorporateEntity, SourceAgentCorporateEntityToAgent, schema_agent),
            "agent_family": (SourceAgentFamily, SourceAgentFamilyToAgent, schema_agent),
            "resource": (SourceResource, SourceResourceToCollection, schema_collection),
            "archival_object": (SourceArchivalObject, SourceArchivalObjectToObject, schema_object),
            "archival_object_collection": (SourceArchivalObject, SourceArchivalObjectToCollection, schema_collection),
            "subject": (SourceSubject, SourceSubjectToTerm, schema_term),
        }
        if object_type not in type_map:
            raise KeyError(f"Unsupported object_type: {object_type}")
        return type_map[object_type]

    def get_online_pending(self, instances, online):
        published_digital_instances = [
            v for v in instances
            if v.get("instance_type") == "digital_object"
            and v.get("digital_object", {}).get("_resolved", {}).get("publish")
        ]
        return bool(len(published_digital_instances) and not online)

    def get_transformed_object(self, data, from_resource, mapping):
        from_obj = json_codec.loads(json.dumps(data), resource=from_resource)
        transformed = json.loads(json_codec.dumps(mapping.apply(from_obj)))
        transformed = self.remove_keys_from_dict(transformed)
        return transformed

    def remove_keys_from_dict(self, data, target_key="$"):
        modified_dict = {}
        if hasattr(data, "items"):
            for key, value in data.items():
                if key != target_key:
                    if isinstance(value, dict):
                        modified_dict[key] = self.remove_keys_from_dict(
                            value, target_key=target_key)
                    elif isinstance(value, list):
                        modified_dict[key] = [
                            self.remove_keys_from_dict(
                                i, target_key=target_key) for i in value]
                    else:
                        modified_dict[key] = value
        else:
            return data
        return modified_dict

    def validate_transformed(self, data, schema_name):
        base_dir = self.service.cfg(
            "SCHEMAS_BASE_DIR",
            str(Path(__file__).resolve().parent / "schemas"),
        ).rstrip("/")
        schema_base = self.service.cfg("SCHEMA_BASE", "") or None

        base_schema = None
        if schema_base:
            with open(join(base_dir, schema_base), "r", encoding="utf-8") as base_file:
                base_schema = json.load(base_file)

        with open(join(base_dir, schema_name), "r", encoding="utf-8") as object_file:
            object_schema = json.load(object_file)

        is_valid(data, object_schema, base_schema)

    def run(self, object_type, data):
        try:
            self.identifier = data.get("uri")
            from_resource, mapping, schema_name = self.get_mapping_classes(
                object_type)
            transformed = self.get_transformed_object(
                data, from_resource, mapping)
            self.online_pending = self.get_online_pending(
                data.get("instances", []),
                transformed.get("online", False),
            )
            self.validate_transformed(transformed, schema_name)
            return transformed
        except ValidationError as e:
            raise TransformError(f"Transformed data is invalid: {e}")
        except Exception as e:
            raise TransformError(
                f"Error transforming {object_type} {
                    self.identifier}: {e}")

    def process_message(self, record):
        try:
            body = json.loads(record.get("body") or "{}")
        except json.JSONDecodeError:
            body = record.get("body")

        attributes = record.get("messageAttributes", {}) or {}

        object_type = None
        for candidate in (
            attributes.get("objectType", {}).get("stringValue"),
            attributes.get("object_type", {}).get("stringValue"),
            body.get("objectType") if isinstance(body, dict) else None,
            body.get("object_type") if isinstance(body, dict) else None,
        ):
            if candidate:
                object_type = candidate
                break
        if not object_type:
            raise ValueError(
                "Missing object_type (object_type or body field)")

        if not isinstance(body, dict):
            raise ValueError(
                "Message body must be JSON object")

        source_data = body.get("data") or body.get("record") or body
        if not isinstance(source_data, dict):
            raise ValueError("Source data must be a JSON object (dict)")

        transformed = self.run(object_type, source_data)

        payload = self.build_indexer_payload(
            object_type, source_data, transformed)

        service_name = self.service.cfg("SERVICE_NAME", "data_transform")
        es_id = payload["objects"][0]["es_id"]
        msg_group = f"{service_name}-{es_id}"
        msg_dedup = f"{service_name}-{es_id}-success"

        self.publish_result(
            "success",
            payload,
            subject=f"transform success: {object_type}",
            message_attributes={
                "service": {"DataType": "String", "StringValue": service_name},
                "requested_action": {"DataType": "String", "StringValue": "index"},
            },
            message_group_id=msg_group,
            message_deduplication_id=msg_dedup,
        )
        return payload

    def publish_result(
        self,
        status,
        payload,
        subject=None,
        message_attributes=None,
        message_group_id=None,
        message_deduplication_id=None,
    ):
        if status == "success":
            topic_arn = self.service.cfg("SUCCESS_TOPIC_ARN", "")
        elif status == "failure":
            topic_arn = self.service.cfg("FAILURE_TOPIC_ARN", "")
        else:
            raise ValueError(f"Unknown status: {status}")

        self.service.publish(
            topic_arn,
            payload,
            message_attributes=message_attributes or {},
            message_group_id=message_group_id or "data_transform",
            message_deduplication_id=message_deduplication_id or "data_transform",
            subject=subject,
        )


service = None


def get_service():
    global service
    if service is None:
        environment = os.getenv("ENVIRONMENT", "")
        aws_region = os.getenv("AWS_REGION") or os.getenv(
            "AWS_DEFAULT_REGION") or ""
        ssm_role_arn = os.getenv("SSM_ROLE_ARN", "")
        service = TransformerService(environment, aws_region, ssm_role_arn)
    return service


def lambda_handler(event, context):
    """Process SQS batch and return partial failures."""
    transformer = Transformer(
        os.getenv("ENVIRONMENT"),
        os.getenv("AWS_REGION"),
        os.getenv("AWS_SSM_ROLE_ARN"))

    records = event.get("Records") or []
    failures = []
    for record in records:
        message_id = record.get("messageId", "unknown")
        try:
            transformer.process_message(record)
        except Exception as exc:
            failures.append({"itemIdentifier": message_id})
            failure_payload = {
                "status": "failure",
                "message_id": message_id,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=20),
            }
            transformer.publish_result(
                "failure", failure_payload, subject="transform failure")
    return {"batchItemFailures": failures}
