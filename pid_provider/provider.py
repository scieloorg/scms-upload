from django.db.models import Q

from pid_provider.base_pid_provider import BasePidProvider
from pid_provider.models import PidProviderXML


class PidProvider(BasePidProvider):
    """
    Recebe XML para validar ou atribuir o ID do tipo v3
    """

    @staticmethod
    def get_xmltree(pid_v3):
        try:
            return PidProviderXML.get_xml_with_pre(pid_v3).xmltree
        except (PidProviderXML.DoesNotExist, AttributeError):
            return None

    @staticmethod
    def get_sps_pkg_name(pid_v3):
        try:
            return PidProviderXML.get_xml_with_pre(pid_v3).sps_pkg_name
        except (PidProviderXML.DoesNotExist, AttributeError):
            return None

    def fix_pid_v2(self, user, pid_v3, correct_pid_v2):
        return PidProviderXML.fix_pid_v2(user, pid_v3, correct_pid_v2)
