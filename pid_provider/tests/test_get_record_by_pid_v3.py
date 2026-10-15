from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from pid_provider.models import OtherPid, PidProviderXML


class GetRecordByPidV3Tests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pid-review")

    def test_pid_registered_only_as_other_pid_does_not_identify_record(self):
        registered = PidProviderXML.objects.create(creator=self.user, v3="V3-CURRENT")
        OtherPid.objects.create(
            creator=self.user,
            pid_provider_xml=registered,
            pid_type="pid_v3",
            pid_in_xml="V3-LEGACY",
        )

        with patch.object(PidProviderXML, "get_best_match") as best_match:
            with self.assertRaises(PidProviderXML.DoesNotExist):
                PidProviderXML.get_record_by_pid_v3(MagicMock(v3="V3-LEGACY"))

        best_match.assert_not_called()

    def test_only_canonical_pid_record_is_selected_when_other_pid_collides(self):
        registered = PidProviderXML.objects.create(creator=self.user, v3="V3-SHARED")
        other = PidProviderXML.objects.create(creator=self.user, v3="V3-OTHER")
        OtherPid.objects.create(
            creator=self.user,
            pid_provider_xml=other,
            pid_type="pid_v3",
            pid_in_xml="V3-SHARED",
        )

        with patch.object(
            PidProviderXML, "get_best_match", return_value={"registered": registered}
        ) as best_match:
            result = PidProviderXML.get_record_by_pid_v3(MagicMock(v3="V3-SHARED"))

        self.assertEqual(result, registered)
        self.assertEqual(list(best_match.call_args.args[0]), [registered])
