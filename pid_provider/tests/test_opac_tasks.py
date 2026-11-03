from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from pid_provider.tasks import (
    task_load_record_from_xml_url,
    task_load_records_from_counter_dict,
    task_process_article_source,
    task_process_article_sources,
)


class LoadRecordsFromCounterDictTests(SimpleTestCase):
    @patch("pid_provider.tasks.task_load_record_from_xml_url.delay")
    @patch("pid_provider.tasks.OPACHarvester")
    def test_dispatches_documents_from_all_journals_when_journal_acron_is_omitted(
        self,
        harvester_class,
        load_record,
    ):
        harvester = harvester_class.return_value
        rsp_item = {"status": True, "journal_acronym": "rsp"}
        csp_item = {"status": True, "journal_acronym": "csp"}
        harvester.harvest_documents.return_value = [
            ("rsp-pid", rsp_item),
            ("csp-pid", csp_item),
        ]
        harvester.format_raw.side_effect = [
            {
                "url": "https://www.scielo.br/j/rsp/a/rsp-pid/?format=xml",
                "origin_date": "2026-08-01",
                "is_public": True,
                "item": rsp_item,
            },
            {
                "url": "https://www.scielo.br/j/csp/a/csp-pid/?format=xml",
                "origin_date": "2026-08-01",
                "is_public": True,
                "item": csp_item,
            },
        ]

        task_load_records_from_counter_dict.run(collection_acron="scl")

        harvester_class.assert_called_once_with(
            domain="www.scielo.br",
            collection_acron="scl",
            from_date=None,
            until_date=None,
            limit=100,
            timeout=5,
            journal_acron=None,
        )
        self.assertEqual(load_record.call_count, 2)
        self.assertEqual(
            {call.kwargs["pid_v3"] for call in load_record.call_args_list},
            {"rsp-pid", "csp-pid"},
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
    @patch("pid_provider.tasks.Collection")
    @patch("pid_provider.tasks.ArticleSource")
    @patch("pid_provider.tasks._get_user")
    def test_stores_xml_in_article_source_with_expected_pid(
        self, get_user, article_source_class, collection_class
    ):
        user = get_user.return_value
        collection = collection_class.get.return_value
        document_item = {"aid": "expected-pid", "pid_v2": "S0001"}

        task_load_record_from_xml_url.run(
            username="operator",
            collection_acron="scl",
            pid_v3="expected-pid",
            xml_url="https://www.scielo.br/j/rsp/a/expected-pid/?format=xml",
            origin_date="2024-01-31",
            source_date="2024-01-31T10:01:00",
            document_item=document_item,
        )

        collection_class.get.assert_called_once_with("scl")
        article_source_class.create_or_update.assert_called_once_with(
            user,
            url="https://www.scielo.br/j/rsp/a/expected-pid/?format=xml",
            source_date="2024-01-31T10:01:00",
            collection=collection,
            pid="S0001",
            force_update=None,
            auto_solve_pid_conflict=False,
            is_public=True,
            detail=document_item,
            expected_pid_v3="expected-pid",
        )

    @patch("pid_provider.tasks.Collection")
    @patch("pid_provider.tasks.ArticleSource")
    @patch("pid_provider.tasks._get_user")
    def test_uses_origin_date_when_source_date_is_missing(
        self, get_user, article_source_class, collection_class
    ):
        task_load_record_from_xml_url.run(
            username="operator",
            collection_acron="scl",
            pid_v3="pid",
            xml_url="https://www.scielo.br/j/rsp/a/pid/?format=xml",
            origin_date="2024-01-31",
        )

        self.assertEqual(
            article_source_class.create_or_update.call_args.kwargs["source_date"],
            "2024-01-31",
        )

    @patch("pid_provider.tasks.UnexpectedEvent.create")
    @patch("pid_provider.tasks.Collection")
    @patch("pid_provider.tasks.ArticleSource")
    @patch("pid_provider.tasks._get_user")
    def test_records_unexpected_event_when_article_source_fails(
        self, get_user, article_source_class, collection_class, create_event
    ):
        article_source_class.create_or_update.side_effect = ValueError("boom")

        task_load_record_from_xml_url.run(
            username="operator",
            collection_acron="scl",
            pid_v3="pid",
            xml_url="https://www.scielo.br/j/rsp/a/pid/?format=xml",
        )

        create_event.assert_called_once()
        self.assertEqual(create_event.call_args.kwargs["item"], "pid")


class ProcessArticleSourcesTaskTests(SimpleTestCase):
    @patch("pid_provider.tasks.task_process_article_source.delay")
    @patch("pid_provider.tasks.ArticleSource")
    def test_marks_processing_and_dispatches_each_stored_xml(
        self, article_source_class, process_one
    ):
        ids = Mock()
        ids.iterator.return_value = iter([1, 2])
        queryset = article_source_class.get_with_stored_xml.return_value
        queryset.values_list.return_value = ids

        task_process_article_sources.run(
            username="operator",
            collection_acron="scl",
            force_update=True,
        )

        article_source_class.get_with_stored_xml.assert_called_once_with(
            status_list=None,
            collection_acron="scl",
            from_date=None,
            until_date=None,
        )
        self.assertEqual(article_source_class.objects.filter.call_count, 2)
        self.assertEqual(
            [c.kwargs["article_source_id"] for c in process_one.call_args_list],
            [1, 2],
        )
        self.assertTrue(process_one.call_args.kwargs["force_update"])

    @patch("pid_provider.tasks.task_process_article_source.delay")
    @patch("pid_provider.tasks.ArticleSource")
    def test_stop_limits_selected_ids(self, article_source_class, process_one):
        ids = article_source_class.get_with_stored_xml.return_value.values_list.return_value
        ids.__getitem__.return_value.iterator.return_value = iter([1])

        task_process_article_sources.run(username="operator", stop=1)

        ids.__getitem__.assert_called_once_with(slice(None, 1))
        process_one.assert_called_once()

    @patch("pid_provider.tasks.ArticleSource")
    @patch("pid_provider.tasks._get_user")
    def test_process_one_uses_stored_xml(self, get_user, article_source_class):
        article_source = article_source_class.objects.get.return_value

        task_process_article_source.run(
            username="operator", article_source_id=7, force_update=True
        )

        article_source_class.objects.get.assert_called_once_with(pk=7)
        article_source.process_stored_xml.assert_called_once_with(
            get_user.return_value,
            force_update=True,
            auto_solve_pid_conflict=False,
        )
