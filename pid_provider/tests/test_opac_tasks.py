from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from pid_provider.tasks import (
    task_load_record_from_xml_url,
    task_load_records_from_counter_dict,
)


class LoadRecordsFromCounterDictTests(SimpleTestCase):
    @patch("pid_provider.tasks.UnexpectedEvent.create")
    @patch("pid_provider.tasks.OPACHarvester")
    def test_requires_journal_acron(self, harvester, create_event):
        task_load_records_from_counter_dict.run()

        harvester.assert_not_called()
        create_event.assert_called_once()
        self.assertEqual(
            create_event.call_args.kwargs["detail"]["task"],
            "task_load_records_from_counter_dict",
        )

    @patch("pid_provider.tasks.task_load_record_from_xml_url.delay")
    @patch("pid_provider.tasks.OPACHarvester")
    def test_dispatches_only_public_documents_from_selected_journal(
        self,
        harvester_class,
        load_record,
    ):
        harvester = harvester_class.return_value
        public_item = {"status": True, "journal_acronym": "rsp"}
        private_item = {"status": False, "journal_acronym": "rsp"}
        harvester.harvest_documents.return_value = [
            ("public-pid", public_item),
            ("private-pid", private_item),
        ]
        harvester.format_raw.side_effect = [
            {
                "url": "https://www.scielo.br/j/rsp/a/public-pid/?format=xml",
                "origin_date": "2026-08-01",
                "is_public": True,
                "item": public_item,
            },
            {
                "url": "https://www.scielo.br/j/rsp/a/private-pid/?format=xml",
                "origin_date": "2026-08-01",
                "is_public": False,
                "item": private_item,
            },
        ]

        task_load_records_from_counter_dict.run(
            username="operator",
            collection_acron="scl",
            journal_acron="rsp",
        )

        harvester_class.assert_called_once_with(
            domain="www.scielo.br",
            collection_acron="scl",
            from_date=None,
            until_date=None,
            limit=100,
            timeout=5,
            journal_acron="rsp",
        )
        load_record.assert_called_once()
        self.assertEqual(load_record.call_args.kwargs["pid_v3"], "public-pid")

    @patch("pid_provider.tasks.UnexpectedEvent.create")
    @patch("pid_provider.tasks.task_load_record_from_xml_url.delay")
    @patch("pid_provider.tasks.OPACHarvester")
    def test_records_document_dispatch_failure_with_document_context(
        self,
        harvester_class,
        load_record,
        create_event,
    ):
        harvester = harvester_class.return_value
        harvester.harvest_documents.return_value = [
            ("failed-pid", {"status": True, "journal_acronym": "rsp"}),
        ]
        harvester.format_raw.side_effect = ValueError("invalid document")

        task_load_records_from_counter_dict.run(
            collection_acron="scl",
            journal_acron="rsp",
        )

        load_record.assert_not_called()
        create_event.assert_called_once()
        self.assertEqual(create_event.call_args.kwargs["item"], "failed-pid")
        self.assertEqual(
            create_event.call_args.kwargs["detail"]["stage"],
            "dispatch_document",
        )


class LoadRecordFromXMLURLTaskTests(SimpleTestCase):
    @patch("pid_provider.tasks.PidProvider")
    @patch("pid_provider.tasks._get_user")
    def test_passes_opac_pid_as_expected_pid(self, get_user, provider_class):
        get_user.return_value = Mock()
        provider = provider_class.return_value
        provider.provide_pid_for_xml_uri.return_value = {
            "v3": "expected-pid",
            "created": True,
        }

        task_load_record_from_xml_url.run(
            username="operator",
            collection_acron="scl",
            pid_v3="expected-pid",
            xml_url="https://www.scielo.br/j/rsp/a/expected-pid/?format=xml",
        )

        self.assertEqual(
            provider.provide_pid_for_xml_uri.call_args.kwargs["expected_pid_v3"],
            "expected-pid",
        )
