import json

import requests
import shortuuid
from asnake.aspace import ASpace
from django.conf import settings
from django.core.mail import send_mail
from electronbonder.client import ElectronBond

from .models import FetchRun


def list_chunks(lst, n):
    """Yield successive n-sized chunks from list.
    Args:
        lst (list): list to chunkify
        n (integer): size of chunk to produce
    """
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def last_run_time(source, object_status, object_type):
    """Returns a date object for a successful fetch.

    Args:
        source (int): a data source, see FetchRun.SOURCE_CHOICES
        object_status (int): the process status, see FetchRun.STATUS_CHOICES
        object_type (str): an object type that was fetched, see FetchRun.OBJECT_TYPE_CHOICES

    Returns:
        int: A UTC timestamp coerced to an integer.
    """
    if FetchRun.objects.filter(
            status=FetchRun.FINISHED,
            source=source,
            object_type=object_type,
            object_status=object_status).exists():
        return int(FetchRun.objects.filter(
            status=FetchRun.FINISHED,
            source=source,
            object_type=object_type,
            object_status=object_status
        ).order_by("-start_time")[0].start_time.timestamp())
    else:
        return 0


def instantiate_aspace(self, config=None):
    """Instantiates and returns an ASpace object with a repository as an attribute.

    Args:
        config (dict): optional config dict

    An optional config object can be passed to this function, otherwise the
    default configs are targeted.
    """
    config = config if config else settings.ARCHIVESSPACE
    aspace = ASpace(
        baseurl=config['baseurl'],
        username=config['username'],
        password=config['password'])
    return aspace


def instantiate_electronbond(self, config=None):
    """Instantiates and returns an ElectronBond client.

    Args:
        config (dict): an optional config dict
    """
    config = config if config else settings.CARTOGRAPHER
    client = ElectronBond(baseurl=config['baseurl'])
    try:
        resp = client.get(config['health_check_path'])
        resp.raise_for_status()
        return client
    except Exception as e:
        raise Exception(
            "Cartographer is not available: {}".format(e))


def identifier_from_uri(uri):
    """Creates a short UUID.

    Uses `shortuuid`, which first creates a v5 UUID using an object's AS URI as
    a name, and then converts them to base57 using lowercase and uppercase
    letters and digits, and removing similar-looking characters such as
    l, 1, I, O and 0.

    This is a one-way process; while it is possible to consistently generate a
    given UUID given an AS URI, it is not possible to decode the URI from the
    UUID.
    """
    return shortuuid.uuid(name=uri)


async def handle_deleted_uris(uri_list, source, object_type, current_run):
    """Delivers POST request to indexing service with list of ids to be deleted."""
    updated = None
    es_ids = [identifier_from_uri(uri) for uri in list(set(uri_list))]
    if es_ids:
        try:
            resp = requests.post(settings.INDEX_DELETE_URL, json={"identifiers": es_ids})
            resp.raise_for_status()
            updated = es_ids
        except requests.exceptions.HTTPError:
            raise Exception("Error sending delete request: {}".format(resp.json()["detail"]))
        except Exception as e:
            raise Exception("Error sending delete request: {}".format(e))
    return updated


def send_email_message(title, body):
    """Send email with errors encountered during a fetch run."""
    try:
        send_mail(title, body, "alerts@rockarch.org", settings.EMAIL_TO_ADDRESSES, fail_silently=False,)
    except Exception as e:
        print(f"Unable to send error notification email: {e}")


def send_teams_message(title, body):
    """Send Teams message with errors encountered during a fetch run."""
    message = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "default",
                            "weight": "bolder",
                            "text": title,
                            "style": "heading",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": body,
                            "wrap": True
                        }
                    ]
                }
            }
        ]
    }
    encoded_msg = json.dumps(message)
    try:
        requests.post(settings.TEAMS_URL, headers={'Content-Type': 'application/json'}, data=encoded_msg)
    except Exception as e:
        print(f"Unable to deliver error notification to Teams Channel: {e}")


def send_error_notification(fetch_run):
    """Send error message to configured targets."""
    errors = ""
    err_str = "errors" if fetch_run.error_count > 1 else "error"
    object_type = fetch_run.get_object_type_display()
    object_status = fetch_run.get_object_status_display()
    source = [s[1] for s in FetchRun.SOURCE_CHOICES if s[0] == int(fetch_run.source)][0]
    for err in fetch_run.errors:
        errors += "{}\n".format(err.message)
    title = f"{fetch_run.error_count} {err_str} processing {object_status} {object_type} objects from {source}"
    body = f"The following errors were encountered while processing {object_status} {object_type} objects from {source}:\n\n{errors}"
    if settings.NOTIFY_EMAIL:
        send_email_message(title, body)
    if settings.NOTIFY_TEAMS:
        send_teams_message(title, body)


def object_published(obj):
    """Returns a boolean indicating whether the object is published."""
    return obj.get("publish", False)


def ancestors_published(obj):
    """Returns a boolean indicating whether the object has unpublished ancestors."""
    return not obj.get("has_unpublished_ancestor", False)


def valid_id0(obj):
    """Returns a boolean indicating whether the object's id_0 field is in a configured list."""
    if len(settings.ARCHIVESSPACE.get("resource_id_0_prefixes", [])):
        if obj.get("id_0") and not any(
                [obj.get("id_0").startswith(prefix) for prefix in settings.ARCHIVESSPACE["resource_id_0_prefixes"]]):
            return False
    return True


def valid_finding_aid_status(obj):
    """
    Returns a boolean indicating whether the finding aid status for the object's
    resource is not in a list of configured restricted statuses.
    """
    if len(settings.ARCHIVESSPACE.get("finding_aid_status_restrict", [])) and obj.get("jsonmodel_type") in ["resource", "archival_object"]:
        resource = obj["ancestors"][-1]["_resolved"] if obj["jsonmodel_type"] == "archival_object" else obj
        if not resource.get("finding_aid_status") or any(
                [resource.get("finding_aid_status") == value for value in settings.ARCHIVESSPACE["finding_aid_status_restrict"]]):
            return False
    return True


def generate_download_identifier(source_object, digital_object):
    """Generates a URI for a downloadable object."""
    return f'{settings.DOWNLOAD_BASEURL}/{identifier_from_uri(source_object["uri"])}'


def generate_manifest_identifier(source_object, digital_object):
    """Generates a URI for a IIIF Presentation manifest."""
    return f'{settings.MANIFEST_BASEURL}/{identifier_from_uri(source_object["uri"])}'
