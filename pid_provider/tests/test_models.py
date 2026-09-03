from unittest.mock import patch

from django.test import SimpleTestCase

from pid_provider.models import FixPidV2, PidProviderXML, PidProviderXMLRegistration, XMLVersion


class XMLVersionTests(SimpleTestCase):
    def test_string_representation_without_pid_provider_xml(self):
        xml_version = XMLVersion(pid_provider_xml=None)

        self.assertEqual(str(xml_version), "- None")


class PidProviderXMLRegistrationTests(SimpleTestCase):
    @patch.object(PidProviderXMLRegistration, "save")
    def test_skipped_event_does_not_store_detail(self, save):
        registration = PidProviderXMLRegistration.record(
            user=None,
            event_status=PidProviderXMLRegistration.EVENT_SKIPPED,
            detail={"large": "payload"},
        )

        save.assert_called_once_with()
        self.assertIsNotNone(registration)
        self.assertIsNone(registration.detail)


class FixPidV2Tests(SimpleTestCase):
    def test_string_representation_with_pid_provider_xml(self):
        xml = PidProviderXML(v3="10.1590/0100-879X2000000100001")
        fix_pid = FixPidV2(
            pid_provider_xml=xml,
            correct_pid_v2="S0100-879X2000000100001",
        )

        self.assertEqual(str(fix_pid), "10.1590/0100-879X2000000100001")
        self.assertEqual(fix_pid.autocomplete_label(), "10.1590/0100-879X2000000100001")

    def test_string_representation_with_pid_provider_xml_without_v3(self):
        xml = PidProviderXML(v3=None)
        fix_pid = FixPidV2(
            pid_provider_xml=xml,
            correct_pid_v2="S0100-879X2000000100001",
        )

        self.assertEqual(str(fix_pid), "S0100-879X2000000100001")
        self.assertEqual(fix_pid.autocomplete_label(), "S0100-879X2000000100001")

    def test_string_representation_without_pid_provider_xml(self):
        fix_pid = FixPidV2(
            pid_provider_xml=None,
            correct_pid_v2="S0100-879X2000000100001",
        )

        self.assertEqual(str(fix_pid), "S0100-879X2000000100001")
        self.assertEqual(fix_pid.autocomplete_label(), "S0100-879X2000000100001")

    def test_string_representation_without_pid_provider_xml_uses_incorrect_pid_fallback(self):
        fix_pid = FixPidV2(
            pid_provider_xml=None,
            correct_pid_v2=None,
            incorrect_pid_v2="S0100-879X2000000100000",
        )

        self.assertEqual(str(fix_pid), "S0100-879X2000000100000")
        self.assertEqual(fix_pid.autocomplete_label(), "S0100-879X2000000100000")

    def test_string_representation_empty(self):
        fix_pid = FixPidV2(pid_provider_xml=None)

        self.assertEqual(str(fix_pid), "-")
        self.assertEqual(fix_pid.autocomplete_label(), "-")
