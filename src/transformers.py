import json
import logging
import os
import traceback
from os import getenv
from os.path import join
from pathlib import Path

import boto3
from jsonschema.exceptions import ValidationError
from odin.codecs import json_codec
from rac_schema_validator import is_valid

from .mappings import (SourceAgentCorporateEntityToAgent,
                       SourceAgentFamilyToAgent, SourceAgentPersonToAgent,
                       SourceArchivalObjectToCollection,
                       SourceArchivalObjectToObject,
                       SourceResourceToCollection, SourceSubjectToTerm)
from .resources.source import (SourceAgentCorporateEntity, SourceAgentFamily,
                               SourceAgentPerson, SourceArchivalObject,
                               SourceResource, SourceSubject)


def assume_role_session(session, role_arn):
    """Return a boto3.Session authenticated via role assumption.

    Uses aws_assume_role_lib.assume_role when available; otherwise falls back to
    STS AssumeRole directly.
    """
    try:
        from aws_assume_role_lib import assume_role
        return assume_role(session, role_arn)
    except Exception:
        sts = session.client("sts")
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="data_transform_ssm")
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

    Mirrors the Pisces/DataFetcher pattern:
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
        logging.error("Encountered an error loading config from SSM.")
        traceback.print_exc()
    return configuration


ENVIRONMENT = getenv("ENVIRONMENT", "")
AWS_REGION = getenv("AWS_REGION") or getenv("AWS_DEFAULT_REGION") or ""
SSM_ROLE_ARN = getenv("SSM_ROLE_ARN", "")

CONFIG = get_config(
    ENVIRONMENT,
    AWS_REGION,
    SSM_ROLE_ARN,
    service_name="data_transform")


def cfg(name, default=""):
    """Return config value: env var wins, else SSM config, else default."""
    value = os.environ.get(name)
    if value is not None and str(value).strip() != "":
        return value
    if name in CONFIG and str(CONFIG.get(name)).strip() != "":
        return CONFIG.get(name)
    return default


# Environment variables. These may be supplied as env vars or via SSM Parameter Store
# under /{ENVIRONMENT}/data_transform/ (env vars win).
SUCCESS_TOPIC_ARN = cfg("SUCCESS_TOPIC_ARN", "")
FAILURE_TOPIC_ARN = cfg("FAILURE_TOPIC_ARN", "")
SCHEMAS_BASE_DIR = cfg(
    "SCHEMAS_BASE_DIR",
    str(Path(__file__).resolve().parent / "schemas"),
).rstrip("/")
SCHEMA_AGENT = cfg("SCHEMA_AGENT", "agent.json")
SCHEMA_COLLECTION = cfg("SCHEMA_COLLECTION", "collection.json")
SCHEMA_OBJECT = cfg("SCHEMA_OBJECT", "object.json")
SCHEMA_TERM = cfg("SCHEMA_TERM", "term.json")
SCHEMA_BASE = cfg("SCHEMA_BASE", "") or None  # optional
SCHEMAS = {
    "base": SCHEMA_BASE,
    "agent": SCHEMA_AGENT,
    "collection": SCHEMA_COLLECTION,
    "object": SCHEMA_OBJECT,
    "term": SCHEMA_TERM,
}

sns = boto3.client("sns")


class TransformError(Exception):
    """Sets up the error messaging for AS transformations."""
    pass


def require_env():
    """Validate required environment variables."""
    missing = []
    for name, value in [
        ("SUCCESS_TOPIC_ARN", SUCCESS_TOPIC_ARN),
        ("FAILURE_TOPIC_ARN", FAILURE_TOPIC_ARN),
        ("SCHEMAS_BASE_DIR", SCHEMAS_BASE_DIR),
        ("SCHEMA_AGENT", SCHEMA_AGENT),
        ("SCHEMA_COLLECTION", SCHEMA_COLLECTION),
        ("SCHEMA_OBJECT", SCHEMA_OBJECT),
        ("SCHEMA_TERM", SCHEMA_TERM),
    ]:
        if not value:
            missing.append(name)
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing))


def publish(topic_arn, payload, subject=None):
    """Publish a JSON payload to SNS."""
    params = {
        "TopicArn": topic_arn,
        "Message": json.dumps(
            payload,
            default=str)}
    if subject:
        params["Subject"] = subject[:100]
    sns.publish(**params)


class Transformer:
    """
    - Parses SQS record: JSON from body, metadata from message attributes
    - Transforms and validates using mappings and resources
    - Publishes success/failure events to SNS
    """

    def __init__(self):
        self.identifier = None
        self.online_pending = False

    def run(self, object_type, data):
        """
        Transform and validate a single object.

        Args:
            object_type (str): e.g. "resource", "archival_object", "agent_person", "subject"
            data (dict): source record dict

        Returns:
            dict: transformed object (validated).
        """
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
            raise TransformError("Transformed data is invalid: {0}".format(e))
        except Exception as e:
            raise TransformError(
                "Error transforming {0} {1}: {2}".format(
                    object_type, self.identifier, str(e))
            )

    def get_mapping_classes(self, object_type):
        """Return tuple for object_type."""
        type_map = {
            "agent_person": (SourceAgentPerson, SourceAgentPersonToAgent, SCHEMA_AGENT),
            "agent_corporate_entity": (
                SourceAgentCorporateEntity,
                SourceAgentCorporateEntityToAgent,
                SCHEMA_AGENT,
            ),
            "agent_family": (SourceAgentFamily, SourceAgentFamilyToAgent, SCHEMA_AGENT),
            "resource": (SourceResource, SourceResourceToCollection, SCHEMA_COLLECTION),
            "archival_object": (SourceArchivalObject, SourceArchivalObjectToObject, SCHEMA_OBJECT),
            "archival_object_collection": (
                SourceArchivalObject,
                SourceArchivalObjectToCollection,
                SCHEMA_COLLECTION,
            ),
            "subject": (SourceSubject, SourceSubjectToTerm, SCHEMA_TERM),
        }
        if object_type not in type_map:
            raise KeyError("Unsupported object_type: {0}".format(object_type))
        return type_map[object_type]

    def get_online_pending(self, instances, online):
        """
        If published digital instances exist but the transformed object is not online,
        mark as pending.
        """
        published_digital_instances = [
            v
            for v in instances
            if v.get("instance_type") == "digital_object" and v.get("digital_object", {}).get("_resolved", {}).get("publish")
        ]
        if len(published_digital_instances) and not online:
            return True
        return False

    def get_transformed_object(self, data, from_resource, mapping):
        """Transform source dict, returning a plain dict."""
        from_obj = json_codec.loads(json.dumps(data), resource=from_resource)
        transformed = json.loads(json_codec.dumps(mapping.apply(from_obj)))
        transformed = self.remove_keys_from_dict(transformed)
        return transformed

    def remove_keys_from_dict(self, data, target_key="$"):
        """Remove all matching keys from dict."""
        modified_dict = {}
        if hasattr(data, "items"):
            for key, value in data.items():
                if key != target_key:
                    if isinstance(value, dict):
                        modified_dict[key] = self.remove_keys_from_dict(
                            data[key], target_key=target_key)
                    elif isinstance(value, list):
                        modified_dict[key] = [
                            self.remove_keys_from_dict(i, target_key=target_key) for i in data[key]
                        ]
                    else:
                        modified_dict[key] = value
        else:
            return data
        return modified_dict

    def validate_transformed(self, data, schema_name):
        """Validate an object against the specified schema."""
        base_dir = cfg("SCHEMAS_BASE_DIR", SCHEMAS_BASE_DIR).rstrip("/")
        schema_base = cfg("SCHEMA_BASE", "") or None

        base_schema = None
        if schema_base:
            with open(join(base_dir, schema_base), "r", encoding="utf-8") as base_file:
                base_schema = json.load(base_file)

        with open(join(base_dir, schema_name), "r", encoding="utf-8") as object_file:
            object_schema = json.load(object_file)

        is_valid(data, object_schema, base_schema)

    def process_message(self, record):
        """
        Parse and process a single SQS record, then publish success/failure to SNS.
        Args:
            record (dict): A single SQS message record.

        Returns:
            dict: success payload that was published (useful for local testing).
        """
        message_id = record.get("messageId", "unknown")
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
                "Missing object_type (messageAttributes.objectType/object_type or body field)")
        source_data = None
        if isinstance(body, dict):
            source_data = body.get("data") or body.get("record") or body
        else:
            raise ValueError(
                "Message body must be JSON object for transformation")
        if not isinstance(source_data, dict):
            raise ValueError("Source data must be a JSON object (dict)")
        transformed = self.run(object_type, source_data)
        success_payload = {
            "status": "success",
            "message_id": message_id,
            "object_type": object_type,
            "identifier": source_data.get("uri"),
            "transformed": transformed,
            "online_pending": self.online_pending,
            "message_attributes": dict(
                (k, (v.get("stringValue") if isinstance(v, dict) else None))
                for k, v in attributes.items()
            ),
        }
        self.publish_result(
            "success",
            success_payload,
            subject="transform success: {0}".format(object_type),
        )
        return success_payload

    def publish_result(self, status, payload, subject=None):
        """Publish a result payload to SNS.

        This method exists primarily so tests can patch it and avoid real SNS calls.
        """
        if status == "success":
            topic_arn = SUCCESS_TOPIC_ARN
        elif status == "failure":
            topic_arn = FAILURE_TOPIC_ARN
        else:
            raise ValueError(f"Unknown status: {status}")
        publish(topic_arn, payload, subject=subject)


# Hacky method because I'm running into env issues.
transformer = None


def get_transformer():
    global transformer
    if transformer is None:
        transformer = Transformer()
    return transformer


def lambda_handler(event, context):
    """
    Processes each record, and returns partial failures so only failed messages retry.
    """
    transformer = get_transformer()

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
                "failure",
                failure_payload,
                subject="transform failure",
            )
    return {"batchItemFailures": failures}
