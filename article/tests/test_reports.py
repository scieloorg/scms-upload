from datetime import date

from django.test import TestCase

from article import choices, reports
from article.tests.data_availability_fixtures import ReportDataMixin


class ParseDateTest(TestCase):
    def test_valid(self):
        self.assertEqual(date(2024, 1, 31), reports.parse_date("2024-01-31"))

    def test_invalid_or_empty(self):
        self.assertIsNone(reports.parse_date("31/01/2024"))
        self.assertIsNone(reports.parse_date(""))
        self.assertIsNone(reports.parse_date(None))


class PercentTest(TestCase):
    def test_percent(self):
        self.assertEqual(33.33, reports.percent(1, 3))

    def test_zero_total(self):
        self.assertEqual(0, reports.percent(0, 0))


class StatusColumnsTest(TestCase):
    def test_includes_all_status_and_not_processed(self):
        columns = [status for status, _label in reports.get_status_columns()]
        self.assertEqual(
            [s for s, _l in choices.DATA_AVAILABILITY_STATUS] + [reports.NOT_PROCESSED],
            columns,
        )


class DataAvailabilityReportTest(ReportDataMixin, TestCase):
    def test_group_by_issue_year(self):
        report = reports.build_data_availability_report(reports.filter_articles())
        self.assertEqual(["2024", "2023"], [r["year"] for r in report["rows"]])

        row_2023 = report["rows"][1]
        self.assertEqual(2, row_2023["total"])
        self.assertEqual(1, self.cell(row_2023, choices.DAS_DATA_AVAILABLE)["count"])
        self.assertEqual(50, self.cell(row_2023, choices.DAS_DATA_AVAILABLE)["percent"])
        self.assertEqual(50, self.cell(row_2023, choices.DAS_ABSENT)["percent"])

        row_2024 = report["rows"][0]
        self.assertEqual(1, self.cell(row_2024, reports.NOT_PROCESSED)["count"])

    def test_totals(self):
        report = reports.build_data_availability_report(reports.filter_articles())
        totals = report["totals"]
        self.assertEqual(4, totals["total"])
        self.assertEqual(2, self.cell(totals, choices.DAS_DATA_AVAILABLE)["count"])
        self.assertEqual(50, self.cell(totals, choices.DAS_DATA_AVAILABLE)["percent"])
        self.assertEqual(25, self.cell(totals, reports.NOT_PROCESSED)["percent"])
        self.assertEqual(0, self.cell(totals, choices.DAS_INVALID)["count"])

    def test_group_by_pub_year(self):
        report = reports.build_data_availability_report(
            reports.filter_articles(), group_by=reports.GROUP_BY_PUB_YEAR
        )
        self.assertEqual(["2024", "2023", "2022"], [r["year"] for r in report["rows"]])
        self.assertEqual(2, report["rows"][1]["total"])

    def test_without_year_goes_last(self):
        self.issue_2023.publication_year = None
        self.issue_2023.save()
        report = reports.build_data_availability_report(reports.filter_articles())
        self.assertEqual(["2024", None], [r["year"] for r in report["rows"]])

    def test_filter_collection_does_not_duplicate(self):
        report = reports.build_data_availability_report(
            reports.filter_articles(collection_acron="aaa")
        )
        self.assertEqual(3, report["totals"]["total"])

    def test_filter_journal(self):
        report = reports.build_data_availability_report(
            reports.filter_articles(journal_id=999999)
        )
        self.assertEqual(0, report["totals"]["total"])
        self.assertEqual([], report["rows"])

    def test_filter_pub_date_is_independent_of_issue_year(self):
        qs = reports.filter_articles(
            pub_date_from=date(2023, 1, 1), pub_date_to=date(2023, 12, 31)
        )
        report = reports.build_data_availability_report(qs)
        self.assertEqual(2, report["totals"]["total"])
        self.assertEqual(["2024", "2023"], [r["year"] for r in report["rows"]])


class FilterOptionsTest(ReportDataMixin, TestCase):
    def test_journals_all(self):
        self.assertEqual(
            ["Journal X", "Journal Y", "Journal Z"],
            [j.title for j in reports.get_journals()],
        )

    def test_journals_by_collection(self):
        self.assertEqual(
            ["Journal X", "Journal Y"],
            [j.title for j in reports.get_journals("aaa")],
        )
        self.assertEqual(
            ["Journal X", "Journal Z"],
            [j.title for j in reports.get_journals("bbb")],
        )

    def test_journals_unknown_collection(self):
        self.assertEqual([], list(reports.get_journals("zzz")))

    def test_pub_date_range(self):
        self.assertEqual(
            (date(2022, 12, 1), date(2024, 3, 1)), reports.get_pub_date_range()
        )
        self.assertEqual(
            (date(2022, 12, 1), date(2023, 11, 1)), reports.get_pub_date_range("aaa")
        )
        self.assertEqual(
            (date(2022, 12, 1), date(2023, 2, 1)),
            reports.get_pub_date_range("aaa", self.journal_x.pk),
        )

    def test_pub_date_range_empty(self):
        self.assertEqual((None, None), reports.get_pub_date_range("zzz"))

    def test_filter_options(self):
        options = reports.get_filter_options("bbb", self.journal_z.pk)
        self.assertEqual(
            [
                {"id": self.journal_x.pk, "label": "Journal X"},
                {"id": self.journal_z.pk, "label": "Journal Z"},
            ],
            options["journals"],
        )
        self.assertEqual("2024-03-01", options["pub_date_min"])
        self.assertEqual("2024-03-01", options["pub_date_max"])

    def test_filter_options_empty_dates(self):
        options = reports.get_filter_options("zzz")
        self.assertEqual([], options["journals"])
        self.assertEqual("", options["pub_date_min"])
        self.assertEqual("", options["pub_date_max"])
