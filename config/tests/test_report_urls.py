from django.test import TestCase
from django.urls import reverse

from config.report_urls import REPORTS


class ReportIndexViewTest(TestCase):
    def test_is_public(self):
        response = self.client.get("/report/")
        self.assertEqual(200, response.status_code)
        self.assertTemplateUsed(response, "report/index.html")

    def test_lists_all_reports(self):
        response = self.client.get("/report/")
        for report in REPORTS:
            self.assertContains(response, f'href="{reverse(report["url_name"])}"')
            self.assertContains(response, str(report["title"]))

    def test_every_report_url_resolves(self):
        for report in REPORTS:
            self.assertTrue(reverse(report["url_name"]).startswith("/report/"))

    def test_report_page_links_back_to_index(self):
        response = self.client.get(reverse("report_data_availability"))
        self.assertContains(response, 'href="/report/"')
