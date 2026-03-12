import json
from unittest import TestCase
from unittest.mock import Mock, call, patch

from odin.codecs import json_codec

from src.mappings import (SourceAgentCorporateEntityToAgent,
                          SourceAgentCorporateEntityToAgentReference,
                          SourceAgentFamilyToAgent,
                          SourceAgentFamilyToAgentReference,
                          SourceAgentPersonToAgent,
                          SourceAgentPersonToAgentReference,
                          SourceAncestorToRecordReference,
                          SourceArchivalObjectToCollection,
                          SourceArchivalObjectToObject, SourceDateToDate,
                          SourceGroupToGroup,
                          SourceLinkedAgentToAgentReference, SourceNoteToNote,
                          SourceRefToTermReference, SourceResourceToCollection,
                          SourceStructuredDateToDate, SourceSubjectToTerm)
from tests.test_helpers import RecursiveNamespace


class BaseTestCase(TestCase):

    def setUp(self):
        patch_str = f"src.mappings.{self.mapping_class.__name__}.__init__"
        with patch(patch_str, return_value=None):
            self.mapping = self.mapping_class()


class SourceRefToTermReferenceTests(BaseTestCase):
    mapping_class = SourceRefToTermReference

    def test_title(self):
        for input, expected in [
                ("This is a title", "This is a title"),
                (" This is a  title ", "This is a  title")]:
            output = self.mapping.title(input)
            self.assertEqual(output, expected)

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_identifier(self):
        output = self.mapping.identifier("/repositories/2/archival_objects/1")
        self.assertEqual(output, 'YRa9EbvFzk9qcLdrsEhK6u')


class SourceAncestorToRecordReferenceTests(BaseTestCase):
    mapping_class = SourceAncestorToRecordReference

    def test_title(self):
        for input, expected in [
                ("This is a title", "This is a title"),
                (" This is a  title ", "This is a  title")]:
            output = self.mapping.title(input)
            self.assertEqual(output, expected)

    def test_order(self):
        for input, expected in [("1", 1), (2, 2)]:
            output = self.mapping.order(input)
            self.assertEqual(output, expected)

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_identifier(self):
        output = self.mapping.identifier("/repositories/2/archival_objects/1")
        self.assertEqual(output, 'YRa9EbvFzk9qcLdrsEhK6u')


class SourceLinkedAgentToAgentReferenceTests(BaseTestCase):
    mapping_class = SourceLinkedAgentToAgentReference

    def test_type(self):
        for input, expected in [
                ('agent_corporate_entity', 'organization'),
                ('agent_person', 'person'),
                ('agent_family', 'family')]:
            output = self.mapping.type(input)
            self.assertEqual(output, expected)

    def test_title(self):
        for input, expected in [
                ("This is a title", "This is a title"),
                (" This is a  title ", "This is a  title")]:
            output = self.mapping.title(input)
            self.assertEqual(output, expected)

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_identifier(self):
        output = self.mapping.identifier("/repositories/2/archival_objects/1")
        self.assertEqual(output, 'YRa9EbvFzk9qcLdrsEhK6u')


class SourceStructuredDateToDateTests(BaseTestCase):
    mapping_class = SourceStructuredDateToDate

    def test_begin(self):
        self.mapping.source = RecursiveNamespace.from_obj({
            "structured_date_single": {"date_standardized": "1990"},
            "structured_date_range": {"begin_date_standardized": "1991"}})
        output = self.mapping.begin('single')
        self.assertEqual(output, '1990')
        output = self.mapping.begin('inclusive')
        self.assertEqual(output, '1991')

    def test_end(self):
        self.mapping.source = RecursiveNamespace.from_obj({
            "structured_date_single": {"date_standardized": "1990"},
            "structured_date_range": {"end_date_standardized": "1991"}})
        output = self.mapping.end('single')
        self.assertEqual(output, '1990')
        output = self.mapping.end('inclusive')
        self.assertEqual(output, '1991')

    def test_expression(self):
        # single dates
        for date_obj in [{"date_expression": "1990"}, {"date_standardized": "1990", "date_expression": None}]:
            self.mapping.source = RecursiveNamespace.from_obj({"structured_date_single": date_obj})
            output = self.mapping.expression('single')
            self.assertEqual(output, '1990')

        # inclusive date ranges
        for date_obj in [
                {"begin_date_expression": "1990", "end_date_expression": "1991"},
                {
                    "begin_date_standardized": "1990", "end_date_standardized": "1991",
                    "begin_date_expression": None, "end_date_expression": None
                }]:
            self.mapping.source = RecursiveNamespace.from_obj({"structured_date_range": date_obj})
            output = self.mapping.expression('inclusive')
            self.assertEqual(output, '1990-1991')


class SourceDateToDateTests(BaseTestCase):
    mapping_class = SourceDateToDate

    def test_end(self):
        self.mapping.source = RecursiveNamespace.from_obj({"date_type": "single", "begin": "1990"})
        self.assertEqual(self.mapping.end("1989"), "1990")
        self.mapping.source = RecursiveNamespace.from_obj({"date_type": "inclusive", "begin": "1990"})
        self.assertEqual(self.mapping.end("1989"), "1989")

    def test_expression(self):
        self.mapping.source = RecursiveNamespace.from_obj({"begin": "1989", "end": "1990"})
        self.assertEqual(self.mapping.expression(""), "1989-1990")
        self.assertEqual(self.mapping.expression(None), "1989-1990")
        self.assertEqual(self.mapping.expression("1991-1992"), "1991-1992")
        self.mapping.source = RecursiveNamespace.from_obj({"begin": "1989", "end": None})
        self.assertEqual(self.mapping.expression(""), "1989-")


class SourceGroupToGroupTests(BaseTestCase):
    mapping_class = SourceGroupToGroup

    def test_category(self):
        for identifier, expected in [
                ("/corporate_entities/1", "organization"),
                ("/subjects/1", "subject"),
                ("/families/1", "person"),
                ("/people/1", "person"),
                ("/resources", "collection")]:
            self.mapping.source = RecursiveNamespace.from_obj({"identifier": identifier})
            output = self.mapping.category()
            self.assertEqual(output, expected)

    @patch('src.mappings.convert_dates')
    def test_dates(self, mock_convert):
        mock_convert.return_value = "1990"
        self.assertEqual(self.mapping.dates("2000"), "1990")
        mock_convert.assert_called_once_with("2000")


class SourceNoteToNoteTests(BaseTestCase):
    mapping_class = SourceNoteToNote

    def test_title(self):
        # Label on source note object
        self.mapping.source = RecursiveNamespace.from_obj({"label": "Explicit Label"})
        self.assertEqual(self.mapping.title("abstract"), "Explicit Label")
        # Label passed in value
        self.mapping.source = RecursiveNamespace.from_obj({"label": None})
        self.assertEqual(self.mapping.title("abstract"), "Abstract")
        # label inferred from jsonmodel_type
        self.mapping.source = RecursiveNamespace.from_obj({"label": None, "jsonmodel_type": "note_bibliography"})
        self.assertEqual(self.mapping.title(None), "Bibliography")

    def test_type(self):
        self.mapping.source = RecursiveNamespace.from_obj({"jsonmodel_type": "note_bibliography"})
        self.assertEqual(self.mapping.type(None), "bibliography")
        self.assertEqual(self.mapping.type("abstract"), "abstract")

    @patch('src.mappings.strip_tags')
    def test_map_subnotes(self, mock_strip_tags):
        value = RecursiveNamespace.from_obj({"jsonmodel_type": "note_definedlist", "items": [{"1": "1"}, {"2": "2"}]})
        output = self.mapping.map_subnotes(value)
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            {
                '$': 'src.resources.rac.Subnote',
                'content': [],
                'items': [{'1': '1'}, {'2': '2'}],
                'type': 'definedlist'
            })

        value = RecursiveNamespace.from_obj({"jsonmodel_type": "note_orderedlist", "items": ["1", "2", "3"]})
        output = self.mapping.map_subnotes(value)
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            {
                '$': 'src.resources.rac.Subnote',
                'content': [],
                'items': [{'0': '1'}, {'1': '2'}, {'2': '3'}],
                'type': 'orderedlist'
            })

        mock_bibliography = Mock(return_value="foo")
        value = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_bibliography",
            "items": [{"1": "1"}, {"2": "2"}],
            "content": ["note content"]})
        self.mapping.bibliograpy_subnotes = mock_bibliography
        self.assertEqual(self.mapping.map_subnotes(value), "foo")
        mock_bibliography.assert_called_once_with(['note content'], [{'1': '1'}, {'2': '2'}])

        mock_index = Mock(return_value="foo")
        value = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_index",
            "items": [{"1": "1"}, {"2": "2"}],
            "content": ["note content"]})
        self.mapping.index_subnotes = mock_index
        self.assertEqual(self.mapping.map_subnotes(value), "foo")
        mock_index.assert_called_once_with(['note content'], [{'1': '1'}, {'2': '2'}])

        mock_chronology = Mock(return_value="foo")
        value = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_chronology",
            "items": [{"1": "1"}, {"2": "2"}]})
        self.mapping.chronology_subnotes = mock_chronology
        self.assertEqual(self.mapping.map_subnotes(value), "foo")
        mock_chronology.assert_called_once_with([{'1': '1'}, {'2': '2'}])

        value = RecursiveNamespace.from_obj({"jsonmodel_type": "note_text", "content": ["note content", "more note content"]})
        mock_strip_tags.return_value = "foo"
        output = self.mapping.map_subnotes(value)
        self.assertEqual(output.__dict__, {'type': 'text', 'content': ['foo', 'foo'], 'items': []})
        self.assertEqual(mock_strip_tags.call_count, 2)

    def test_subnotes(self):
        for note_type in ["note_multipart", "note_bioghist"]:
            mock_map_subnotes = Mock(return_value="foo")
            self.mapping.source = RecursiveNamespace.from_obj({"jsonmodel_type": note_type})
            self.mapping.map_subnotes = mock_map_subnotes
            self.assertEqual(self.mapping.subnotes([1, 2]), ["foo", "foo"])
            mock_map_subnotes.assert_has_calls([
                call(1),
                call(2)])

        self.mapping.source = RecursiveNamespace.from_obj({"jsonmodel_type": "note_singlepart", "content": "[\"Note content\"]"})
        output = self.mapping.subnotes(None)
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [{'type': 'text', 'content': ['Note content'], 'items': [], '$': 'src.resources.rac.Subnote'}])

        mock_index = Mock(return_value="foo")
        self.mapping.source = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_index",
            "items": [1, 2, 3],
            "content": ["note content"]})
        self.mapping.index_subnotes = mock_index
        self.assertEqual(self.mapping.subnotes(None), "foo")
        mock_index.assert_called_once_with(["note content"], [1, 2, 3])

        mock_bibliography = Mock(return_value="foo")
        self.mapping.source = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_bibliography",
            "items": [1, 2, 3],
            "content": ["note content"]})
        self.mapping.bibliograpy_subnotes = mock_bibliography
        self.assertEqual(self.mapping.subnotes(None), "foo")
        mock_bibliography.assert_called_once_with(["note content"], [1, 2, 3])

        mock_chronology = Mock(return_value="foo")
        self.mapping.source = RecursiveNamespace.from_obj({
            "jsonmodel_type": "note_chronology",
            "items": [1, 2, 3]})
        self.mapping.chronology_subnotes = mock_chronology
        self.assertEqual(self.mapping.subnotes(None), "foo")
        mock_chronology.assert_called_once_with([1, 2, 3])

    @patch('src.mappings.strip_tags')
    def test_bibliography_subnotes(self, mock_strip):
        mock_strip.return_value = "foo"
        output = self.mapping.bibliograpy_subnotes("[\"This is a subnote\"]", None)
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {'type': 'text', 'content': ['foo'], 'items': [], '$': 'src.resources.rac.Subnote'},
                {'type': 'orderedlist', 'content': None, 'items': [], '$': 'src.resources.rac.Subnote'}
            ])
        mock_strip.assert_called_once_with('"This is a subnote"')

        output = self.mapping.bibliograpy_subnotes("[\"This is a subnote\"]", [{"1": "1"}])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {'type': 'text', 'content': ['foo'], 'items': [], '$': 'src.resources.rac.Subnote'},
                {'type': 'orderedlist', 'content': [{'1': '1'}], 'items': [], '$': 'src.resources.rac.Subnote'}
            ])

    def test_index_subnotes(self):
        output = self.mapping.index_subnotes("[\"This is a subnote\"]", [{"type": "item type", "value": "item value"}])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {
                    'type': 'text',
                    'content': ['This is a subnote'],
                    'items': [],
                    '$': 'src.resources.rac.Subnote'},
                {
                    'type': 'definedlist',
                    'content': [],
                    'items': [{'label': 'item type', 'value': 'item value'}],
                    '$': 'src.resources.rac.Subnote'
                }
            ])

    def test_chronology_subnotes(self):
        output = self.mapping.chronology_subnotes([{"type": "item type", "value": "item value"}])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            {
                'type': 'definedlist',
                'content': [],
                'items': [{'label': None, 'value': None}],
                '$': 'src.resources.rac.Subnote'
            })


class SourceResourceToCollectionTests(BaseTestCase):
    mapping_class = SourceResourceToCollection

    @patch('src.mappings.strip_tags')
    def test_title(self, mock_strip):
        mock_strip.return_value = "foo"
        self.assertEqual(self.mapping.title("input"), "foo")
        mock_strip.assert_called_once_with("input")

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "type": "abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with([RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])

    @patch('src.mappings.SourceDateToDate.apply')
    def test_dates(self, mock_apply):
        mock_apply.return_value = ["converted"]
        self.assertEqual(self.mapping.dates([1, 2]), ["converted"])
        mock_apply.assert_called_once_with([1, 2])

    @patch('src.mappings.transform_language')
    def test_languages(self, mock_transform):
        mock_transform.return_value = [{"expression": "English", "identifier": "eng"}]
        self.mapping.source = RecursiveNamespace.from_obj({"lang_materials": None})
        self.assertEqual(
            self.mapping.languages(["en"]),
            [{"expression": "English", "identifier": "eng"}])
        mock_transform.assert_called_once_with(["en"], None)

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/collections/1234")
        mock_id.assert_called_once_with("foo")

    @patch('src.mappings.SourceRefToTermReference.apply')
    def test_terms(self, mock_apply):
        mock_apply.return_value = ["converted"]
        self.assertEqual(self.mapping.terms(["foo"]), ["converted"])
        mock_apply.assert_called_once_with(["foo"])

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_creators(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.creators([
            RecursiveNamespace.from_obj({"role": "creator"}),
            RecursiveNamespace.from_obj({"role": "subject"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"role": "creator"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_people(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.people([
            RecursiveNamespace.from_obj({"type": "agent_person"}),
            RecursiveNamespace.from_obj({"type": "agent_family"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_person"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_organizations(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.organizations([
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
            RecursiveNamespace.from_obj({"type": "agent_person"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_families(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.families([
            RecursiveNamespace.from_obj({"type": "agent_family"}),
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_family"}))

    @patch('src.mappings.transform_formats')
    def test_formats(self, mock_formats):
        mock_formats.return_value = ["documents"]
        self.mapping.source = RecursiveNamespace.from_obj({"subjects": ["subject"], "ancestors": ["anceestor"]})
        self.mapping.context = None
        self.assertEqual(self.mapping.formats(["foo"]), ["documents"])
        mock_formats.assert_called_once_with(["foo"], ["subject"], ["anceestor"], None)

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "collections")

    @patch('src.mappings.identifier_from_uri')
    def test_parent(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(
            self.mapping.parent([RecursiveNamespace.from_obj({"ref": "/repositories/2/archival_objects/1"})]),
            "1234")
        self.assertEqual(None, None)


class SourceArchivalObjectToCollectionTests(BaseTestCase):
    mapping_class = SourceArchivalObjectToCollection

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "type": "abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with([RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])

    def test_title(self):
        self.mapping.source = RecursiveNamespace.from_obj({"display_string": "display string title"})
        self.assertEqual(self.mapping.title(None), "display string title")
        self.assertEqual(self.mapping.title("explicit title"), "explicit title")
        self.mapping.source = RecursiveNamespace.from_obj({"component_id": "1", "level": "series"})
        self.assertEqual(self.mapping.title("explicit title"), "explicit title, Series 1")

    @patch('src.mappings.transform_language')
    def test_languages(self, mock_transform):
        mock_transform.return_value = [{"expression": "English", "identifier": "eng"}]
        self.mapping.source = RecursiveNamespace.from_obj({"lang_materials": None})
        self.assertEqual(
            self.mapping.languages(["en"]),
            [{"expression": "English", "identifier": "eng"}])
        mock_transform.assert_called_once_with(["en"], None)

    @patch('src.mappings.SourceRefToTermReference.apply')
    def test_terms(self, mock_apply):
        mock_apply.return_value = ["converted"]
        self.assertEqual(self.mapping.terms(["foo"]), ["converted"])
        mock_apply.assert_called_once_with(["foo"])

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_creators(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.creators([
            RecursiveNamespace.from_obj({"role": "creator"}),
            RecursiveNamespace.from_obj({"role": "subject"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"role": "creator"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_people(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.people([
            RecursiveNamespace.from_obj({"type": "agent_person"}),
            RecursiveNamespace.from_obj({"type": "agent_family"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_person"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_organizations(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.organizations([
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
            RecursiveNamespace.from_obj({"type": "agent_person"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_families(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.families([
            RecursiveNamespace.from_obj({"type": "agent_family"}),
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_family"}))

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/collections/1234")
        mock_id.assert_called_once_with("foo")

    @patch('src.mappings.transform_formats')
    def test_formats(self, mock_formats):
        mock_formats.return_value = ["documents"]
        self.mapping.source = RecursiveNamespace.from_obj({"subjects": ["subject"], "ancestors": ["anceestor"]})
        self.mapping.context = None
        self.assertEqual(self.mapping.formats(["foo"]), ["documents"])
        mock_formats.assert_called_once_with(["foo"], ["subject"], ["anceestor"], None)

    @patch('src.mappings.has_online_instance')
    def test_online(self, mock_online_instance):
        mock_online_instance.return_value = False
        self.mapping.source = RecursiveNamespace.from_obj({"uri": "uri"})
        self.mapping.context = None
        self.assertFalse(self.mapping.online("value"))
        mock_online_instance.assert_called_once_with("value", "uri", None)

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "collections")

    @patch('src.mappings.identifier_from_uri')
    def test_parent(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(
            self.mapping.parent([RecursiveNamespace.from_obj({"ref": "/repositories/2/archival_objects/1"})]),
            "1234")
        self.assertEqual(None, None)


class SourceArchivalObjectToObjectTests(BaseTestCase):
    mapping_class = SourceArchivalObjectToObject

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "type": "abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with([RecursiveNamespace.from_obj({"publish": True, "type": "abstract"})])

    def test_title(self):
        self.mapping.source = RecursiveNamespace.from_obj({"display_string": "display string title"})
        self.assertEqual(self.mapping.title(None), "display string title")
        self.assertEqual(self.mapping.title("explicit title"), "explicit title")

    @patch('src.mappings.SourceDateToDate.apply')
    def test_dates(self, mock_apply):
        mock_apply.return_value = ["date"]
        self.assertEqual(self.mapping.dates(["input"]), ["date"])
        mock_apply.assert_called_once_with(["input"])

    @patch('src.mappings.transform_language')
    def test_languages(self, mock_transform):
        mock_transform.return_value = [{"expression": "English", "identifier": "eng"}]
        self.mapping.source = RecursiveNamespace.from_obj({"lang_materials": None})
        self.assertEqual(
            self.mapping.languages(["en"]),
            [{"expression": "English", "identifier": "eng"}])
        mock_transform.assert_called_once_with(["en"], None)

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/objects/1234")
        mock_id.assert_called_once_with("foo")

    @patch('src.mappings.SourceRefToTermReference.apply')
    def test_terms(self, mock_apply):
        mock_apply.return_value = ["converted"]
        self.assertEqual(self.mapping.terms(["foo"]), ["converted"])
        mock_apply.assert_called_once_with(["foo"])

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_people(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.people([
            RecursiveNamespace.from_obj({"type": "agent_person"}),
            RecursiveNamespace.from_obj({"type": "agent_family"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_person"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_organizations(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.organizations([
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
            RecursiveNamespace.from_obj({"type": "agent_person"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}))

    @patch('src.mappings.SourceLinkedAgentToAgentReference.apply')
    def test_families(self, mock_apply):
        mock_apply.return_value = "converted"
        self.assertEqual(self.mapping.families([
            RecursiveNamespace.from_obj({"type": "agent_family"}),
            RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}),
        ]), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_family"}))

    @patch('src.mappings.transform_formats')
    def test_formats(self, mock_formats):
        mock_formats.return_value = ["documents"]
        self.mapping.source = RecursiveNamespace.from_obj({"subjects": ["subject"], "ancestors": ["anceestor"]})
        self.mapping.context = None
        self.assertEqual(self.mapping.formats(["foo"]), ["documents"])
        mock_formats.assert_called_once_with(["foo"], ["subject"], ["anceestor"], None)

    @patch('src.mappings.has_online_instance')
    def test_online(self, mock_online_instance):
        mock_online_instance.return_value = False
        self.mapping.source = RecursiveNamespace.from_obj({"uri": "uri"})
        self.mapping.context = None
        self.assertFalse(self.mapping.online("value"))
        mock_online_instance.assert_called_once_with("value", "uri", None)

    @patch('src.mappings.generate_download_identifier')
    @patch('src.mappings.generate_manifest_identifier')
    def test_files(self, mock_manifest_id, mock_download_id):
        mock_manifest_id.return_value = "manifest_id"
        mock_download_id.return_value = "download_id"
        self.mapping.source = RecursiveNamespace.from_obj({})
        self.mapping.context = "https://context.org"
        output = self.mapping.files([
            RecursiveNamespace.from_obj({"digital_object": {"title": "digital object title", "publish": True}}),
            RecursiveNamespace.from_obj({"digital_object": {"title": "digital object title", "publish": False}}),
            RecursiveNamespace.from_obj({"digital_object": None})])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [{
                'title': 'digital object title',
                'download': 'download_id',
                'manifest': 'manifest_id',
                '$': 'src.resources.rac.FileObject'
            }])

        mock_download_id.assert_called_once_with(
            {}, {"title": "digital object title", "publish": True}, "https://context.org")
        mock_manifest_id.assert_called_once_with(
            {}, {"title": "digital object title", "publish": True}, "https://context.org")

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "collections")

    @patch('src.mappings.identifier_from_uri')
    def test_parent(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(
            self.mapping.parent([RecursiveNamespace.from_obj({"ref": "/repositories/2/archival_objects/1"})]),
            "1234")
        self.assertEqual(None, None)


class SourceSubjectToTermTests(BaseTestCase):
    mapping_class = SourceSubjectToTerm

    def test_type(self):
        self.assertEqual(
            self.mapping.type([RecursiveNamespace.from_obj({"term_type": "foo"})]),
            "foo")

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{
                'identifier': 'foo',
                'source': 'archivesspace',
                '$': 'src.resources.rac.ExternalIdentifier'}])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/terms/1234")
        mock_id.assert_called_once_with("foo")

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "terms")


class SourceAgentCorporateEntityToAgentReferenceTests(BaseTestCase):
    mapping_class = SourceAgentCorporateEntityToAgentReference

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{
                'identifier': 'foo',
                'source': 'archivesspace',
                '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_reference_type(self):
        self.assertEqual(self.mapping.reference_type(), "organization")

    @patch('src.mappings.identifier_from_uri')
    def test_identifier(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.identifier("foo"), "1234")
        mock_id.assert_called_once_with("foo")

    def test_role(self):
        self.assertEqual(self.mapping.role(), "creator")


class SourceAgentCorporateEntityToAgentTests(BaseTestCase):
    mapping_class = SourceAgentCorporateEntityToAgent

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "jsonmodel_type": "note_abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with(
            [RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])

    @patch('src.mappings.convert_dates')
    def test_dates(self, mock_convert):
        mock_convert.return_value = "1990"
        self.assertEqual(self.mapping.dates("2000"), "1990")
        mock_convert.assert_called_once_with("2000")

    def test_external_identifiers(self):
        self.mapping.source = RecursiveNamespace.from_obj({"uri": "/agents/1234"})
        output = self.mapping.external_identifiers([
            RecursiveNamespace.from_obj({"record_identifier": "12345", "source": "cartographer"})])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {'identifier': '12345', 'source': 'cartographer', '$': 'src.resources.rac.ExternalIdentifier'},
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])
        self.assertEqual(
            json.loads(json_codec.dumps(self.mapping.external_identifiers(None))),
            [
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/agents/1234")
        mock_id.assert_called_once_with("foo")

    def test_agent_types(self):
        self.assertEqual(self.mapping.agent_types(), "organization")

    def test_category(self):
        self.assertEqual(self.mapping.category(), "organization")

    @patch('src.mappings.SourceAgentCorporateEntityToAgentReference.apply')
    def test_organizations(self, mock_apply):
        mock_apply.return_value = "converted"
        self.mapping.source = RecursiveNamespace.from_obj({"type": "agent_corporate_entity"})
        self.assertEqual(
            self.mapping.organizations(None),
            ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"type": "agent_corporate_entity"}))

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "agents")


class SourceAgentFamilyToAgentReferenceTests(BaseTestCase):
    mapping_class = SourceAgentFamilyToAgentReference

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_reference_type(self):
        self.assertEqual(self.mapping.reference_type(), "family")

    @patch('src.mappings.identifier_from_uri')
    def test_identifier(self, mock_id):
        mock_id.return_value = "12345"
        self.assertEqual(self.mapping.identifier("foo"), "12345")
        mock_id.assert_called_once_with("foo")

    def test_role(self):
        self.assertEqual(self.mapping.role(), "creator")


class SourceAgentFamilyToAgentTests(BaseTestCase):
    mapping_class = SourceAgentFamilyToAgent

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "jsonmodel_type": "note_abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with(
            [RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])

    @patch('src.mappings.convert_dates')
    def test_dates(self, mock_convert):
        mock_convert.return_value = "1990"
        self.assertEqual(self.mapping.dates("2000"), "1990")
        mock_convert.assert_called_once_with("2000")

    def test_external_identifiers(self):
        self.mapping.source = RecursiveNamespace.from_obj({"uri": "/agents/1234"})
        output = self.mapping.external_identifiers([
            RecursiveNamespace.from_obj({"record_identifier": "12345", "source": "cartographer"})])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {'identifier': '12345', 'source': 'cartographer', '$': 'src.resources.rac.ExternalIdentifier'},
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])
        self.assertEqual(
            json.loads(json_codec.dumps(self.mapping.external_identifiers(None))),
            [
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/agents/1234")
        mock_id.assert_called_once_with("foo")

    def test_agent_types(self):
        self.assertEqual(self.mapping.agent_types(), "family")

    def test_category(self):
        self.assertEqual(self.mapping.category(), "person")

    @patch('src.mappings.SourceAgentFamilyToAgentReference.apply')
    def test_families(self, mock_apply):
        mock_apply.return_value = "converted"
        self.mapping.source = RecursiveNamespace.from_obj({"foo": "bar"})
        self.assertEqual(self.mapping.families(None), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"foo": "bar"}))

    @patch('src.mappings.transform_group')
    def test_group(self, mock_group):
        mock_group.return_value = {"foo": "bar"}
        self.assertEqual(self.mapping.group("foo"), {"foo": "bar"})
        mock_group.assert_called_once_with("foo", "agents")


class SourceAgentPersonToAgentReferenceTests(BaseTestCase):
    mapping_class = SourceAgentPersonToAgentReference

    def test_external_identifiers(self):
        output = self.mapping.external_identifiers("foo")
        self.assertEqual(json.loads(
            json_codec.dumps(output)),
            [{'identifier': 'foo', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}])

    def test_reference_type(self):
        self.assertEqual(self.mapping.reference_type(), "person")

    @patch('src.mappings.identifier_from_uri')
    def test_identifier(self, mock_id):
        mock_id.return_value = "12345"
        self.assertEqual(self.mapping.identifier("foo"), "12345")
        mock_id.assert_called_once_with("foo")

    def test_role(self):
        self.assertEqual(self.mapping.role(), "creator")


class SourceAgentPersonToAgentTests(BaseTestCase):
    mapping_class = SourceAgentPersonToAgent

    def test_parse_name(self):
        for input, expected in [
            (RecursiveNamespace.from_obj({"rest_of_name": " Mickey", "primary_name": "Mouse "}), "Mickey Mouse"),
            (RecursiveNamespace.from_obj({"rest_of_name": " Cher", "primary_name": None}), "Cher"),
            (RecursiveNamespace.from_obj({"rest_of_name": None, "primary_name": " Rocker Duck"}), "Rocker Duck"),
        ]:
            self.assertEqual(self.mapping.parse_name(input), expected)

    @patch('src.mappings.SourceAgentPersonToAgent.parse_name')
    def test_title(self, mock_parse):
        mock_parse.return_value = "parsed name"
        self.assertEqual(self.mapping.title("input name"), "parsed name")
        mock_parse.assert_called_once_with("input name")

    @patch('src.mappings.SourceNoteToNote.apply')
    def test_notes(self, mock_apply):
        mock_apply.return_value = ["converted"]
        output = self.mapping.notes([
            RecursiveNamespace.from_obj({"publish": False, "jsonmodel_type": "note_abstract"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_physloc"}),
            RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])
        self.assertEqual(output, ["converted"])
        mock_apply.assert_called_once_with(
            [RecursiveNamespace.from_obj({"publish": True, "jsonmodel_type": "note_abstract"})])

    @patch('src.mappings.convert_dates')
    def test_dates(self, mock_convert):
        mock_convert.return_value = "1990"
        self.assertEqual(self.mapping.dates("2000"), "1990")
        mock_convert.assert_called_once_with("2000")

    def test_external_identifiers(self):
        self.mapping.source = RecursiveNamespace.from_obj({"uri": "/agents/1234"})
        output = self.mapping.external_identifiers([
            RecursiveNamespace.from_obj({"record_identifier": "12345", "source": "cartographer"})])
        self.assertEqual(
            json.loads(json_codec.dumps(output)),
            [
                {'identifier': '12345', 'source': 'cartographer', '$': 'src.resources.rac.ExternalIdentifier'},
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])
        self.assertEqual(
            json.loads(json_codec.dumps(self.mapping.external_identifiers(None))),
            [
                {'identifier': '/agents/1234', 'source': 'archivesspace', '$': 'src.resources.rac.ExternalIdentifier'}
            ])

    @patch('src.mappings.identifier_from_uri')
    def test_uri(self, mock_id):
        mock_id.return_value = "1234"
        self.assertEqual(self.mapping.uri("foo"), "/agents/1234")
        mock_id.assert_called_once_with("foo")

    def test_agent_types(self):
        self.assertEqual(self.mapping.agent_types(), "person")

    def test_category(self):
        self.assertEqual(self.mapping.category(), "person")

    @patch('src.mappings.SourceAgentPersonToAgentReference.apply')
    def test_people(self, mock_apply):
        mock_apply.return_value = "converted"
        self.mapping.source = RecursiveNamespace.from_obj({"foo": "bar"})
        self.assertEqual(self.mapping.people(None), ["converted"])
        mock_apply.assert_called_once_with(RecursiveNamespace.from_obj({"foo": "bar"}))

    @patch('src.mappings.transform_group')
    @patch('src.mappings.SourceAgentPersonToAgent.parse_name')
    def test_group(self, mock_parse, mock_group):
        mock_group.return_value = {"foo": "bar"}
        mock_parse.return_value = "display name"
        self.mapping.source = RecursiveNamespace.from_obj({"display_name": "display name"})
        self.assertEqual(self.mapping.group(RecursiveNamespace.from_obj({})), {"foo": "bar"})
        mock_group.assert_called_once_with(RecursiveNamespace.from_obj({"title": "display name"}), "agents")
        mock_parse.assert_called_once_with("display name")
