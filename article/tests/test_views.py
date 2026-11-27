from django.test import TestCase

from article import reports
from article.tests.data_availability_fixtures import ReportDataMixin

URL = "/report/data_availability"


class DataAvailabilityReportViewTest(ReportDataMixin, TestCase):
    def test_is_public(self):
        response = self.client.get(URL)
        self.assertEqual(200, response.status_code)
        self.assertTemplateUsed(response, "article/report/data_availability.html")
        self.assertEqual(4, response.context["report"]["totals"]["total"])

    def test_filters(self):
        response = self.client.get(
            URL,
            {
                "collection": "aaa",
                "pub_date_from": "2023-01-01",
                "pub_date_to": "2023-12-31",
                "group_by": reports.GROUP_BY_PUB_YEAR,
            },
        )
        self.assertEqual(2, response.context["report"]["totals"]["total"])
        self.assertEqual(
            ["2023"], [r["year"] for r in response.context["report"]["rows"]]
        )
        self.assertEqual("aaa", response.context["filters"]["collection"])

    def test_invalid_params_are_ignored(self):
        response = self.client.get(
            URL, {"journal": "abc", "pub_date_from": "x", "group_by": "x"}
        )
        self.assertEqual(200, response.status_code)
        filters = response.context["filters"]
        self.assertEqual("", filters["journal"])
        self.assertEqual("", filters["pub_date_from"])
        self.assertEqual(reports.GROUP_BY_ISSUE_YEAR, filters["group_by"])
        self.assertEqual(4, response.context["report"]["totals"]["total"])

    def test_empty_result(self):
        response = self.client.get(URL, {"collection": "zzz"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(0, response.context["report"]["totals"]["total"])

    def test_csv(self):
        response = self.client.get(URL, {"format": "csv"})
        self.assertEqual(200, response.status_code)
        self.assertIn("text/csv", response["Content-Type"])
        lines = response.content.decode().strip().splitlines()
        self.assertTrue(lines[0].startswith("year,total,data-available,"))
        self.assertTrue(lines[1].startswith("2024,2,"))
        self.assertTrue(lines[-1].startswith("total,4,"))

    def test_journals_restricted_by_collection(self):
        response = self.client.get(URL, {"collection": "aaa"})
        self.assertEqual(
            ["Journal X", "Journal Y"],
            [j.title for j in response.context["journals"]],
        )

    def test_date_inputs_have_range(self):
        response = self.client.get(URL, {"collection": "aaa"})
        self.assertEqual("2022-12-01", response.context["pub_date_min"])
        self.assertEqual("2023-11-01", response.context["pub_date_max"])
        self.assertContains(response, 'min="2022-12-01"')
        self.assertContains(response, 'max="2023-11-01"')

    def test_options_url_in_page(self):
        response = self.client.get(URL)
        self.assertContains(response, f'data-options-url="{OPTIONS_URL}"')


OPTIONS_URL = "/report/data_availability/options"


class DataAvailabilityReportOptionsViewTest(ReportDataMixin, TestCase):
    def test_is_public_json(self):
        response = self.client.get(OPTIONS_URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual("application/json", response["Content-Type"])
        data = response.json()
        self.assertEqual(3, len(data["journals"]))
        self.assertEqual("2022-12-01", data["pub_date_min"])
        self.assertEqual("2024-03-01", data["pub_date_max"])

    def test_collection(self):
        data = self.client.get(OPTIONS_URL, {"collection": "bbb"}).json()
        self.assertEqual(
            ["Journal X", "Journal Z"], [j["label"] for j in data["journals"]]
        )
        self.assertEqual("2022-12-01", data["pub_date_min"])
        self.assertEqual("2024-03-01", data["pub_date_max"])

    def test_collection_and_journal(self):
        data = self.client.get(
            OPTIONS_URL, {"collection": "aaa", "journal": self.journal_y.pk}
        ).json()
        self.assertEqual(2, len(data["journals"]))
        self.assertEqual("2023-11-01", data["pub_date_min"])
        self.assertEqual("2023-11-01", data["pub_date_max"])

    def test_invalid_journal_is_ignored(self):
        data = self.client.get(OPTIONS_URL, {"journal": "abc"}).json()
        self.assertEqual("2022-12-01", data["pub_date_min"])
