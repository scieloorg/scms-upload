from unittest.mock import patch

from django.test import SimpleTestCase

from pid_provider.models import PidProviderXMLRegistration, XMLVersion


class XMLVersionTests(SimpleTestCase):
    def test_string_representation_without_pid_provider_xml(self):
        xml_version = XMLVersion(pid_provider_xml=None)

        self.assertEqual(str(xml_version), "- None")
