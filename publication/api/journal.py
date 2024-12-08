import logging

from django.utils.translation import gettext_lazy as _

from journal.models import JournalHistory
from publication.api.publication import PublicationAPI
from publication.utils.journal import build_journal


def publish_journal(journal_proc, api_data):
    logging.info(f"publish_journal {journal_proc}")

    journal = journal_proc.journal
    journal_pid = journal_proc.pid
    journal_acron = journal_proc.acron
    journal_history = JournalHistory.objects.filter(
        journal_collection__collection=journal_proc.collection,
        journal_collection__journal=journal_proc.journal,
    )

    payload = {}

    journal_payload_builder = JournalPayload(payload)
    build_journal(
        journal_payload_builder, journal, journal_pid, journal_acron, journal_history,
        journal_proc.availability_status
    )

    api = PublicationAPI(**api_data)
    return api.post_data(payload)


class JournalPayload:
    """
    {
        "id": "1678-4463",
        "logo_url": "http://cadernos.ensp.fiocruz.br/csp/logo.jpeg",
        "mission": [
            {
            "language": "pt",
            "value": "Publicar artigos originais que contribuam para o estudo da saúde pública em geral e disciplinas afins, como epidemiologia, nutrição, parasitologia, ecologia e controles de vetores, saúde ambiental, políticas públicas e planejamento em saúde, ciências sociais aplicadas à saúde, dentre outras."
            },
            {
            "language": "es",
            "value": "Publicar artículos originales que contribuyan al estudio de la salud pública en general y de disciplinas afines como epidemiología, nutrición, parasitología, ecología y control de vectores, salud ambiental, políticas públicas y planificación en el ámbito de la salud, ciencias sociales aplicadas a la salud, entre otras."
            },
            {
            "language": "en",
            "value": "To publish original articles that contribute to the study of public health in general and to related disciplines such as epidemiology, nutrition, parasitology,vector ecology and control, environmental health, public polices and health planning, social sciences applied to health, and others."
            }
        ],
        "title": "Bla",
        "title_iso": "Cad. saúde pública",
        "short_title": "Cad. Saúde Pública",
        "acronym": "csp",
        "scielo_issn": "0102-311X",
        "print_issn": "0102-311X",
        "electronic_issn": "1678-4464",
        "status_history": [
            {
            "status": "current",
            "date": "1999-07-02T00:00:00.000000Z",
            "reason": ""
            }
        ],
        "subject_areas": [
            "HEALTH SCIENCES"
        ],
        "sponsors": [
            {
            "name": "CNPq - Conselho Nacional de Desenvolvimento Científico e Tecnológico "
            }
        ],
        "subject_categories": [
            "Health Policy & Services"
        ],
        "online_submission_url": "http://cadernos.ensp.fiocruz.br/csp/index.php",
        "contact": {
            "email": "cadernos@ensp.fiocruz.br",
            "address": "Rua Leopoldo Bulhões, 1480 , Rio de Janeiro, Rio de Janeiro, BR, 21041-210 , 55 21 2598-2511, 55 21 2598-2508"
        },
        "created": "1999-07-02T00:00:00.000000Z",
        "updated": "2019-07-19T20:33:17.102106Z"
    }
    """

    def __init__(self, data=None):
        self.data = data
        self.reset_lists()

    def add_dates(self, created, updated):
        self.data["created"] = created.isoformat()
        if updated:
            self.data["updated"] = updated.isoformat()

    @property
    def default(self):
        return {
            "id": "1678-4463",
            "logo_url": "http://cadernos.ensp.fiocruz.br/csp/logo.jpeg",
            "mission": [
                {
                    "language": "pt",
                    "value": "Publicar artigos originais que contribuam para o estudo da saúde pública em geral e disciplinas afins, como epidemiologia, nutrição, parasitologia, ecologia e controles de vetores, saúde ambiental, políticas públicas e planejamento em saúde, ciências sociais aplicadas à saúde, dentre outras.",
                },
                {
                    "language": "es",
                    "value": "Publicar artículos originales que contribuyan al estudio de la salud pública en general y de disciplinas afines como epidemiología, nutrición, parasitología, ecología y control de vectores, salud ambiental, políticas públicas y planificación en el ámbito de la salud, ciencias sociales aplicadas a la salud, entre otras.",
                },
                {
                    "language": "en",
                    "value": "To publish original articles that contribute to the study of public health in general and to related disciplines such as epidemiology, nutrition, parasitology,vector ecology and control, environmental health, public polices and health planning, social sciences applied to health, and others.",
                },
            ],
            "title": "Bla",
            "title_iso": "Cad. saúde pública",
            "short_title": "Cad. Saúde Pública",
            "acronym": "csp",
            "scielo_issn": "0102-311X",
            "print_issn": "0102-311X",
            "electronic_issn": "1678-4464",
            "status_history": [
                {
                    "status": "current",
                    "date": "1999-07-02T00:00:00.000000Z",
                    "reason": "",
                }
            ],
            "subject_areas": ["HEALTH SCIENCES"],
            "sponsors": [
                {
                    "name": "CNPq - Conselho Nacional de Desenvolvimento Científico e Tecnológico "
                }
            ],
            "subject_categories": ["Health Policy & Services"],
            "online_submission_url": "http://cadernos.ensp.fiocruz.br/csp/index.php",
            "contact": {
                "email": "cadernos@ensp.fiocruz.br",
                "address": "Rua Leopoldo Bulhões, 1480 , Rio de Janeiro, Rio de Janeiro, BR, 21041-210 , 55 21 2598-2511, 55 21 2598-2508",
            },
            "created": "1999-07-02T00:00:00.000000Z",
            "updated": "2019-07-19T20:33:17.102106Z",
        }

    def reset_lists(self):
        self.data["sponsors"] = []
        self.data["status_history"] = []
        self.data["mission"] = []

    def add_ids(self, journal_id):
        self.data["id"] = journal_id

    def add_acron(self, acron):
        self.data["acronym"] = acron

    def add_journal_titles(self, title, title_iso, short_title):
        self.data["title"] = title
        self.data["title_iso"] = title_iso
        self.data["short_title"] = short_title

    def add_journal_issns(self, scielo_issn, eletronic_issn, print_issn=None):
        self.data["scielo_issn"] = scielo_issn
        self.data["print_issn"] = print_issn
        self.data["eletronic_issn"] = eletronic_issn

    def add_thematic_scopes(self, subject_categories, subject_areas):
        # Subject Categories
        self.data["subject_categories"] = subject_categories

        # Study Area
        self.data["subject_areas"] = subject_areas

    # def add_issue_count(self, issue_count):
    #     # Issue count
    #     self.data["issue_count"] = issue_count

    def add_sponsor(self, sponsor):
        # Sponsors
        self.data["sponsors"].append({"name": sponsor})

    def add_contact(self, name, email, address, city, state, country):
        # email to contact
        # self.data["editor_email"] = email
        # self.data["publisher_address"] = address
        # self.data["publisher_name"] = name
        # self.data["publisher_city"] = city
        # self.data["publisher_state"] = state
        # self.data["publisher_country"] = country
        self.data["contact"] = {
            "email": email,
            "address": address,
        }

    def add_logo_url(self, logo_url):
        self.data["logo_url"] = logo_url

    def add_online_submission_url(self, online_submission_url):
        self.data["online_submission_url"] = online_submission_url

    def add_related_journals(self, previous_journal, next_journal_title):
        self.data["next_journal"] = {"name": next_journal_title}
        self.data["previous_journal"] = {"name": previous_journal}

    def add_event_to_timeline(self, status, since, reason):
        """
        Add item to self.data["timeline

        Parameters
        ----------
        status : StringField
        since : DateTimeField
        reason : StringField

        """
        if status and since:
            self.data["status_history"].append(
                {
                    "status": status or "",
                    "date": since or "",
                    "reason": reason or "",
                }
            )

    def add_mission(self, language, description):
        """
        Add item to self.data["mission

        Parameters
        ----------
        language : StringField
        description : StringField

        """
        if language and description:
            self.data["mission"].append(
                {
                    "language": language or "",
                    "value": description or "",
                }
            )

    # def add_metrics(self, total_h5_index, total_h5_median, h5_metric_year):
    #     """
    #     Add item to self.data["metrics

    #     Parameters
    #     ----------

    #     total_h5_index : IntField
    #     total_h5_median : IntField
    #     h5_metric_year : IntField

    #     """
    #     if all([total_h5_index, total_h5_median, h5_metric_year]):
    #         self.data["metrics"] = {
    #             "total_h5_index": total_h5_index or None,
    #             "total_h5_median": total_h5_median or None,
    #             "h5_metric_year": h5_metric_year or None,
    #         }

    def add_is_public(self, availability_status):
        self.data["is_public"] = availability_status == "C"

    def add_publisher(self, name):
        self.data.setdefault("institution_responsible_for", [])
        self.data["institution_responsible_for"].append({"name": name})
