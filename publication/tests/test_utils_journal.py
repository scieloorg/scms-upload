import unittest
from datetime import datetime
from unittest.mock import MagicMock

import publication.utils.journal as mod

build_journal = mod.build_journal


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def build_fake_official_journal(**overrides):
    official_journal = MagicMock()
    official_journal.issn_electronic = "1678-4464"
    official_journal.issn_print = "0102-311X"
    official_journal.title = "Título Oficial"
    official_journal.title_iso = "Tit. Iso"
    official_journal.previous_journal_title = "Revista Anterior"
    official_journal.next_journal_title = "Revista Seguinte"
    for key, value in overrides.items():
        setattr(official_journal, key, value)
    return official_journal


def build_fake_journal(**overrides):
    journal = MagicMock()
    journal.official_journal = build_fake_official_journal()
    journal.issue_count = 10

    created = MagicMock()
    created.isoformat.return_value = "2020-01-01T00:00:00"
    journal.created = created

    updated = MagicMock()
    updated.isoformat.return_value = "2021-01-01T00:00:00"
    journal.updated = updated

    journal.contact = {
        "name": "Editor Responsável",
        "email": "contato@example.org",
        "address": "Rua A, 123",
        "city": "Rio de Janeiro",
        "state": "RJ",
        "country": "BR",
    }

    journal.mission.all.return_value = []
    journal.sponsor.all.return_value = []
    journal.owner.all.return_value = []
    journal.publisher.all.return_value = []

    journal.title = "Título do Periódico"
    journal.short_title = "T. Curto"
    journal.logo_url = "http://example.org/logo.png"
    journal.submission_online_url = "http://example.org/submit"
    journal.wos_areas = ["Health Sciences"]
    journal.subject_areas = ["Public Health"]

    for key, value in overrides.items():
        setattr(journal, key, value)
    return journal


def build_fake_journal_history(events=None):
    history = MagicMock()
    history.all.return_value = events or []
    return history


def build_fake_mission(code2, text):
    mission = MagicMock()
    mission.language.code2 = code2
    mission.text = text
    return mission


def build_fake_event(event_type, date, interruption_reason=None):
    event = MagicMock()
    event.event_type = event_type
    event.date = date
    event.interruption_reason = interruption_reason
    return event


def build_fake_institution_item(name):
    item = MagicMock()
    item.institution.name = name
    return item


def build_fake_builder():
    builder = MagicMock()
    builder.data = {}
    return builder


# ---------------------------------------------------------------------------
# Campos básicos: issue_count, ids, dates, acron, contact
# ---------------------------------------------------------------------------

class TestBuildJournalBasicFields(unittest.TestCase):

    def setUp(self):
        self.builder = build_fake_builder()
        self.journal = build_fake_journal()
        self.journal_history = build_fake_journal_history()

    def test_chama_add_issue_count(self):
        build_journal(
            self.builder, self.journal, "1678-4463", "csp",
            self.journal_history, "C",
        )
        self.builder.add_issue_count.assert_called_once_with(self.journal.issue_count)

    def test_chama_add_ids_com_journal_id(self):
        build_journal(
            self.builder, self.journal, "1678-4463", "csp",
            self.journal_history, "C",
        )
        self.builder.add_ids.assert_called_once_with("1678-4463")

    def test_chama_add_dates_com_created_e_updated(self):
        build_journal(
            self.builder, self.journal, "1678-4463", "csp",
            self.journal_history, "C",
        )
        self.builder.add_dates.assert_called_once_with(
            self.journal.created, self.journal.updated
        )

    def test_chama_add_acron(self):
        build_journal(
            self.builder, self.journal, "1678-4463", "csp",
            self.journal_history, "C",
        )
        self.builder.add_acron.assert_called_once_with("csp")

    def test_chama_add_contact_com_kwargs_do_journal_contact(self):
        build_journal(
            self.builder, self.journal, "1678-4463", "csp",
            self.journal_history, "C",
        )
        self.builder.add_contact.assert_called_once_with(**self.journal.contact)


# ---------------------------------------------------------------------------
# Laços: mission e journal_history (timeline)
# ---------------------------------------------------------------------------

class TestBuildJournalMissionAndTimeline(unittest.TestCase):

    def test_adiciona_mission_para_cada_item(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal.mission.all.return_value = [
            build_fake_mission("pt", "Missão em português"),
            build_fake_mission("en", "Mission in english"),
        ]
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        self.assertEqual(builder.add_mission.call_count, 2)
        builder.add_mission.assert_any_call("pt", "Missão em português")
        builder.add_mission.assert_any_call("en", "Mission in english")

    def test_sem_missoes_nao_chama_add_mission(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_mission.assert_not_called()

    def test_adiciona_evento_timeline_para_cada_historico(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history([
            build_fake_event("ADMITTED", "1999-01-01", None),
            build_fake_event("INTERRUPTED", "2020-01-01", "ceased"),
        ])

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        self.assertEqual(builder.add_event_to_timeline.call_count, 2)
        builder.add_event_to_timeline.assert_any_call("ADMITTED", "1999-01-01", None)
        builder.add_event_to_timeline.assert_any_call("INTERRUPTED", "2020-01-01", "ceased")

    def test_sem_historico_nao_chama_add_event_to_timeline(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_event_to_timeline.assert_not_called()


# ---------------------------------------------------------------------------
# Cálculo de current_status e tratamento de force_update
# ---------------------------------------------------------------------------

class TestBuildJournalCurrentStatus(unittest.TestCase):

    def test_chama_add_current_status(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_current_status.assert_called_once()

    def test_chama_add_forced_current_status_com_force_update_default_false(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_forced_current_status.assert_called_once_with(False)

    def test_chama_add_forced_current_status_com_force_update_true(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(
            builder, journal, "1678-4463", "csp", journal_history, "C", force_update=True
        )

        builder.add_forced_current_status.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# ISSNs e títulos (com fallback para official_journal)
# ---------------------------------------------------------------------------

class TestBuildJournalIssnsAndTitles(unittest.TestCase):

    def test_add_journal_issns_usa_journal_id_como_scielo_issn(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_journal_issns.assert_called_once_with(
            scielo_issn="1678-4463",
            eletronic_issn=journal.official_journal.issn_electronic,
            print_issn=journal.official_journal.issn_print,
        )

    def test_add_journal_titles_usa_titulo_do_journal_quando_presente(self):
        builder = build_fake_builder()
        journal = build_fake_journal(title="Título Próprio")
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_journal_titles.assert_called_once_with(
            title="Título Próprio",
            title_iso=journal.official_journal.title_iso,
            short_title=journal.short_title,
        )

    def test_add_journal_titles_usa_titulo_do_official_journal_como_fallback(self):
        builder = build_fake_builder()
        journal = build_fake_journal(title=None)
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_journal_titles.assert_called_once_with(
            title=journal.official_journal.title,
            title_iso=journal.official_journal.title_iso,
            short_title=journal.short_title,
        )

    def test_add_journal_titles_fallback_tambem_para_titulo_vazio(self):
        builder = build_fake_builder()
        journal = build_fake_journal(title="")
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_journal_titles.assert_called_once_with(
            title=journal.official_journal.title,
            title_iso=journal.official_journal.title_iso,
            short_title=journal.short_title,
        )


# ---------------------------------------------------------------------------
# Logo (com o try/except AttributeError)
# ---------------------------------------------------------------------------

class TestBuildJournalLogoUrl(unittest.TestCase):

    def test_usa_logo_url_do_journal_quando_presente(self):
        builder = build_fake_builder()
        journal = build_fake_journal(logo_url="http://example.org/logo.png")
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_logo_url.assert_called_once_with("http://example.org/logo.png")

    def test_fallback_quando_logo_url_e_falsy(self):
        for logo_url in ["", None]:
            with self.subTest(logo_url=logo_url):
                builder = build_fake_builder()
                journal = build_fake_journal(logo_url=logo_url)
                journal_history = build_fake_journal_history()

                build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

                builder.add_logo_url.assert_called_once_with(
                    "https://www.scielo.org/journal_logo_missing.gif"
                )

    def test_fallback_quando_atributo_logo_url_nao_existe(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        del journal.logo_url
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_logo_url.assert_called_once_with(
            "https://www.scielo.org/journal_logo_missing.gif"
        )


# ---------------------------------------------------------------------------
# Related journals e submissão online
# ---------------------------------------------------------------------------

class TestBuildJournalRelatedAndSubmission(unittest.TestCase):

    def test_add_online_submission_url(self):
        builder = build_fake_builder()
        journal = build_fake_journal(submission_online_url="http://example.org/submit")
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_online_submission_url.assert_called_once_with(
            "http://example.org/submit"
        )

    def test_add_related_journals_usa_previous_e_next_do_official_journal(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_related_journals.assert_called_once_with(
            previous_journal=journal.official_journal.previous_journal_title,
            next_journal_title=journal.official_journal.next_journal_title,
        )


# ---------------------------------------------------------------------------
# Sponsors, owners e publishers
# ---------------------------------------------------------------------------

class TestBuildJournalSponsorsAndPublishers(unittest.TestCase):

    def test_adiciona_sponsor_para_cada_item(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal.sponsor.all.return_value = [
            build_fake_institution_item("CNPq"),
            build_fake_institution_item("CAPES"),
        ]
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        self.assertEqual(builder.add_sponsor.call_count, 2)
        builder.add_sponsor.assert_any_call("CNPq")
        builder.add_sponsor.assert_any_call("CAPES")

    def test_sem_sponsors_nao_chama_add_sponsor(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_sponsor.assert_not_called()

    def test_add_publisher_uniao_de_owner_e_publisher(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal.owner.all.return_value = [
            build_fake_institution_item("Fiocruz"),
            build_fake_institution_item("SciELO"),
        ]
        journal.publisher.all.return_value = [
            build_fake_institution_item("SciELO"),  # duplicado propositalmente
            build_fake_institution_item("Faperj"),
        ]
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        # union de owner + publisher, sem duplicar "SciELO"
        chamados = {c.args[0] for c in builder.add_publisher.call_args_list}
        self.assertEqual(chamados, {"Fiocruz", "SciELO", "Faperj"})
        self.assertEqual(builder.add_publisher.call_count, 3)

    def test_add_publisher_ignora_nomes_falsy(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal.owner.all.return_value = [
            build_fake_institution_item(""),
            build_fake_institution_item(None),
            build_fake_institution_item("Fiocruz"),
        ]
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_publisher.assert_called_once_with("Fiocruz")


# ---------------------------------------------------------------------------
# Escopos temáticos e visibilidade
# ---------------------------------------------------------------------------

class TestBuildJournalThematicScopesAndVisibility(unittest.TestCase):

    def test_add_thematic_scopes_usa_wos_areas_e_subject_areas(self):
        builder = build_fake_builder()
        journal = build_fake_journal(
            wos_areas=["Health Sciences"],
            subject_areas=["Public Health"],
        )
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "C")

        builder.add_thematic_scopes.assert_called_once_with(
            subject_categories=["Health Sciences"],
            subject_areas=["Public Health"],
        )

    def test_add_is_public_recebe_availability_status_repassado(self):
        builder = build_fake_builder()
        journal = build_fake_journal()
        journal_history = build_fake_journal_history()

        build_journal(builder, journal, "1678-4463", "csp", journal_history, "S")

        builder.add_is_public.assert_called_once_with("S")


if __name__ == "__main__":
    unittest.main()