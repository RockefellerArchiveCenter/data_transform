import json
import logging
import traceback
from os import getenv
from pathlib import Path

import boto3
from aws_assume_role_lib import assume_role
from odin.codecs import json_codec
from rac_schema_validator import is_valid

from .mappings import (SourceAgentCorporateEntityToAgent,
                       SourceAgentFamilyToAgent, SourceAgentPersonToAgent,
                       SourceArchivalObjectToCollection,
                       SourceArchivalObjectToObject,
                       SourceResourceToCollection, SourceSubjectToTerm,
                       identifier_from_uri)
from .resources.source import (SourceAgentCorporateEntity, SourceAgentFamily,
                               SourceAgentPerson, SourceArchivalObject,
                               SourceResource, SourceSubject)


def get_client_with_role(resource, aws_region, role_arn):
    """Gets Boto3 client which authenticates with a specific IAM role."""
    session = boto3.Session(region_name=aws_region)
    assumed_role_session = assume_role(session, role_arn)
    return assumed_role_session.client(resource)


def get_config(environment, aws_region, ssm_role_arn, service_name):
    """Fetch config values from SSM Parameter Store by path."""
    ssm_parameter_path = f"/{environment}/{service_name}"
    configuration = {}

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


class Transformer:

    def __init__(self):
        self.service_name = "data_transform"
        self.config = get_config(
            getenv('ENVIRONMENT'),
            getenv('AWS_REGION'),
            getenv('AWS_SSM_ROLE_ARN'),
            self.service_name)

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

    def get_mapping_classes(self, object_type):
        schema_agent = self.config["SCHEMA_AGENT"]
        schema_collection = self.config["SCHEMA_COLLECTION"]
        schema_object = self.config["SCHEMA_OBJECT"]
        schema_term = self.config["SCHEMA_TERM"]
        type_map = {
            "agent_person": (SourceAgentPerson, SourceAgentPersonToAgent, schema_agent),
            "agent_corporate_entity": (SourceAgentCorporateEntity, SourceAgentCorporateEntityToAgent, schema_agent),
            "agent_family": (SourceAgentFamily, SourceAgentFamilyToAgent, schema_agent),
            "resource": (SourceResource, SourceResourceToCollection, schema_collection),
            "archival_object": (SourceArchivalObject, SourceArchivalObjectToObject, schema_object),
            "archival_object_collection": (SourceArchivalObject, SourceArchivalObjectToCollection, schema_collection),
            "subject": (SourceSubject, SourceSubjectToTerm, schema_term),
        }
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
        transformed = mapping.apply(from_obj, context=self.config)
        transformed_json = json.loads(json_codec.dumps(transformed))
        return self.remove_keys_from_dict(transformed_json)

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
        base_dir = self.config["SCHEMAS_BASE_DIR"].rstrip("/")
        schema_base = self.config.get("SCHEMA_BASE", None)

        base_schema = None
        if schema_base:
            with open(Path(base_dir, schema_base), "r", encoding="utf-8") as base_file:
                base_schema = json.load(base_file)

        with open(Path(base_dir, schema_name), "r", encoding="utf-8") as object_file:
            object_schema = json.load(object_file)

        is_valid(data, object_schema, base_schema)

    def send_success_message(self, transformed, object_type):
        client = get_client_with_role('sns', getenv(
            'AWS_REGION'), self.config['SNS_ROLE_ARN'])
        client.publish(
            TopicArn=self.config['SNS_TOPIC_ARN'],
            MessageGroupId=f'{self.service_name}-{transformed["identifier"]}',
            MessageDeduplicationId=f'{
                self.service_name}-{transformed["identifier"]}-transform',
            Message=json.dumps(transformed),
            MessageAttributes={
                'service': {
                    'DataType': 'String',
                    'StringValue': self.service_name,
                },
                'requested_action': {
                    'DataType': 'String',
                    'StringValue': 'index',
                },
                'es_id': {
                    'DataType': 'String',
                    'StringValue': transformed['identifier'],
                },
                'object_type': {
                    'DataType': 'String',
                    'StringValue': object_type,
                }
            })

    def send_error_message(self, exception, object_type, object_id):
        client = get_client_with_role('sns', getenv(
            'AWS_REGION'), self.config['SNS_ROLE_ARN'])
        tb = ''.join(traceback.format_exception(exception)[:-1])
        client.publish(
            TopicArn=self.config['SNS_TOPIC_ARN'],
            MessageGroupId=f'{self.service_name}-{object_id}',
            MessageDeduplicationId=f'{self.service_name}-{object_id}-failure',
            Message=tb,
            MessageAttributes={
                'service': {
                    'DataType': 'String',
                    'StringValue': self.service_name,
                },
                'object_status': {
                    'DataType': 'String',
                    'StringValue': 'updated',
                },
                'object_type': {
                    'DataType': 'String',
                    'StringValue': object_type,
                },
                'object_id': {
                    'DataType': 'String',
                    'StringValue': object_id,
                },
                'outcome': {
                    'DataType': 'String',
                    'StringValue': 'FAILURE',
                },
                'message': {
                    'DataType': 'String',
                    'StringValue': str(exception),
                }
            })

    def run(self, object_type, data):
        try:
            from_resource, mapping, schema_name = self.get_mapping_classes(
                object_type)
            transformed = self.get_transformed_object(
                data, from_resource, mapping)
            transformed['online_pending'] = self.get_online_pending(
                data.get("instances", []),
                transformed.get("online", False))
            self.validate_transformed(transformed, schema_name)
            self.send_success_message(transformed, object_type)
        except Exception as e:
            self.send_error_message(
                e, object_type, identifier_from_uri(
                    data['uri']))


def lambda_handler(event, context):
    """Process SQS batch."""

    transformer = Transformer()

    records = event.get("Records", [])

    for record in records:
        object_data = json.loads(record.get("body") or "{}")
        attributes = record.get("messageAttributes", {}) or {}
        object_type = attributes.get("object_type", {}).get("stringValue")
        transformer.run(object_type, object_data)
