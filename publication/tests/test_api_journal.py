"""
Testes para o módulo de publicação de periódicos
(translate_status, JournalPayload, publish_journal).

AJUSTE NECESSÁRIO:
Não tenho certeza do caminho real deste módulo no projeto scms-upload.
O import abaixo assume `publication.api.journal`. Se o arquivo estiver em
outro lugar (ex: publication/tasks.py, publication/api/publish.py etc.),
ajuste apenas a linha de import — o resto dos testes não muda, pois usam
sempre `mod.<nome>`.

Baseado em unittest (unittest.TestCase + unittest.mock).
"""

import unittest
from unittest.mock import MagicMock, patch

import publication.api.journal as mod  # <-- ajuste este import se necessário

translate_status = mod.translate_status
JournalPayload = mod.JournalPayload
publish_journal = mod.publish_journal


# ---------------------------------------------------------------------------
# translate_status
# ---------------------------------------------------------------------------

class TestTranslateStatus(unittest.TestCase):

    def test_reason_mapeado_tem_prioridade_sobre_event_type(self):
        casos = [
            ("ceased", "deceased"),
            ("suspended-by-committee", "suspended"),
            ("suspended-by-editor", "suspended"),
            ("not-open-access", "suspended"),
        ]
        for reason, expected in casos:
            with self.subTest(reason=reason):
                # mesmo com event_type="ADMITTED" (que mapearia para
                # "current"), o reason mapeado deve prevalecer
                self.assertEqual(translate_status("ADMITTED", reason), expected)

    def test_reason_nao_mapeado_cai_no_fallback_inprogress(self):
        """
        Comportamento corrigido: se `interruption_reason` for truthy mas
        não estiver em REASON_MAP, a função cai no fallback único
        "inprogress" (não retorna mais None nesse caso).
        """
        self.assertEqual(translate_status("ADMITTED", "motivo-desconhecido"), "inprogress")
        self.assertEqual(translate_status("INTERRUPTED", "motivo-desconhecido"), "inprogress")

    def test_sem_reason_usa_event_map_admitted(self):
        self.assertEqual(translate_status("ADMITTED", None), "current")
        self.assertEqual(translate_status("ADMITTED", ""), "current")

    def test_sem_reason_usa_event_map_interrupted(self):
        self.assertEqual(translate_status("INTERRUPTED", None), "deceased")

    def test_sem_reason_event_type_desconhecido_retorna_inprogress(self):
        self.assertEqual(translate_status("QUALQUER_OUTRO", None), "inprogress")
        self.assertEqual(translate_status(None, None), "inprogress")

    def test_fallback_inprogress_nunca_retorna_none(self):
        """
        Garante que a função nunca retorna None: qualquer combinação sem
        mapeamento válido (reason ou event_type) cai em "inprogress".
        """
        casos = [
            ("ADMITTED", "motivo-desconhecido"),
            ("INTERRUPTED", "motivo-desconhecido"),
            ("EVENTO_QUALQUER", None),
            (None, None),
            (None, "motivo-desconhecido"),
        ]
        for event_type, reason in casos:
            with self.subTest(event_type=event_type, reason=reason):
                self.assertIsNotNone(translate_status(event_type, reason))


# ---------------------------------------------------------------------------
# JournalPayload
# ---------------------------------------------------------------------------

class TestJournalPayloadInit(unittest.TestCase):

    def test_reset_lists_no_init(self):
        payload = JournalPayload({})
        self.assertEqual(payload.data["sponsors"], [])
        self.assertEqual(payload.data["status_history"], [])
        self.assertEqual(payload.data["mission"], [])
        self.assertEqual(payload.data["institution_responsible_for"], [])

    def test_data_none_por_padrao(self):
        # cuidado: se data=None, reset_lists() vai falhar (None não suporta
        # atribuição de chave). Documentando esse comportamento.
        with self.assertRaises(TypeError):
            JournalPayload()


class TestJournalPayloadAddDates(unittest.TestCase):

    def test_add_dates_com_updated(self):
        payload = JournalPayload({})
        created = MagicMock()
        created.isoformat.return_value = "2020-01-01T00:00:00"
        updated = MagicMock()
        updated.isoformat.return_value = "2021-01-01T00:00:00"

        payload.add_dates(created, updated)

        self.assertEqual(payload.data["created"], "2020-01-01T00:00:00")
        self.assertEqual(payload.data["updated"], "2021-01-01T00:00:00")

    def test_add_dates_sem_updated_nao_seta_chave(self):
        payload = JournalPayload({})
        created = MagicMock()
        created.isoformat.return_value = "2020-01-01T00:00:00"

        payload.add_dates(created, None)

        self.assertEqual(payload.data["created"], "2020-01-01T00:00:00")
        self.assertNotIn("updated", payload.data)


class TestJournalPayloadSimpleSetters(unittest.TestCase):

    def test_add_ids(self):
        payload = JournalPayload({})
        payload.add_ids("1678-4463")
        self.assertEqual(payload.data["id"], "1678-4463")

    def test_add_acron(self):
        payload = JournalPayload({})
        payload.add_acron("csp")
        self.assertEqual(payload.data["acronym"], "csp")

    def test_add_journal_titles(self):
        payload = JournalPayload({})
        payload.add_journal_titles("Título Completo", "Tit. Iso", "T. Curto")
        self.assertEqual(payload.data["title"], "Título Completo")
        self.assertEqual(payload.data["title_iso"], "Tit. Iso")
        self.assertEqual(payload.data["short_title"], "T. Curto")

    def test_add_journal_issns(self):
        payload = JournalPayload({})
        payload.add_journal_issns("0102-311X", "1678-4464", "0102-3111")
        self.assertEqual(payload.data["scielo_issn"], "0102-311X")
        # a chave "eletronic_issn" (sem "c") é proposital: replica o typo
        # existente no campo Journal.eletronic_issn do opac_schema, para
        # manter compatibilidade com o schema de destino. Não é um bug.
        # ref: https://github.com/scieloorg/opac_schema/blob/26d4c63709f6ae5d43f6cae0ff9f21fe36f0107c/opac_schema/v1/models.py#L573
        self.assertEqual(payload.data["eletronic_issn"], "1678-4464")
        self.assertEqual(payload.data["print_issn"], "0102-3111")

    def test_add_journal_issns_print_issn_default_none(self):
        payload = JournalPayload({})
        payload.add_journal_issns("0102-311X", "1678-4464")
        self.assertIsNone(payload.data["print_issn"])

    def test_add_logo_url(self):
        payload = JournalPayload({})
        payload.add_logo_url("http://example.org/logo.png")
        self.assertEqual(payload.data["logo_url"], "http://example.org/logo.png")

    def test_add_online_submission_url(self):
        payload = JournalPayload({})
        payload.add_online_submission_url("http://example.org/submit")
        self.assertEqual(payload.data["online_submission_url"], "http://example.org/submit")

    def test_add_issue_count(self):
        payload = JournalPayload({})
        payload.add_issue_count(42)
        self.assertEqual(payload.data["issue_count"], 42)

    def test_add_related_journals(self):
        payload = JournalPayload({})
        payload.add_related_journals("Revista Anterior", "Revista Seguinte")
        self.assertEqual(payload.data["previous_journal"], {"name": "Revista Anterior"})
        self.assertEqual(payload.data["next_journal"], {"name": "Revista Seguinte"})

    def test_add_is_public_true_quando_status_c(self):
        payload = JournalPayload({})
        payload.add_is_public("C")
        self.assertTrue(payload.data["is_public"])

    def test_add_is_public_false_para_outros_status(self):
        for status in ["S", "D", "", None]:
            with self.subTest(status=status):
                payload = JournalPayload({})
                payload.add_is_public(status)
                self.assertFalse(payload.data["is_public"])


class TestJournalPayloadThematicScopes(unittest.TestCase):

    def test_add_thematic_scopes_filtra_valores_falsy(self):
        payload = JournalPayload({})
        payload.add_thematic_scopes(
            subject_categories=["Cat A", "", None, "Cat B"],
            subject_areas=["Area 1", None, "Area 2"],
        )
        self.assertEqual(payload.data["subject_categories"], ["Cat A", "Cat B"])
        self.assertEqual(payload.data["subject_areas"], ["Area 1", "Area 2"])

    def test_add_thematic_scopes_com_none(self):
        payload = JournalPayload({})
        payload.add_thematic_scopes(None, None)
        self.assertEqual(payload.data["subject_categories"], [])
        self.assertEqual(payload.data["subject_areas"], [])


class TestJournalPayloadSponsor(unittest.TestCase):

    def test_add_sponsor_ignora_valor_falsy(self):
        payload = JournalPayload({})
        payload.add_sponsor(None)
        payload.add_sponsor("")
        self.assertEqual(payload.data["sponsors"], [])

    def test_add_sponsor_adiciona_dict_com_name(self):
        payload = JournalPayload({})
        payload.add_sponsor("CNPq")
        payload.add_sponsor("CAPES")
        self.assertEqual(
            payload.data["sponsors"], [{"name": "CNPq"}, {"name": "CAPES"}]
        )


class TestJournalPayloadCleanBrTags(unittest.TestCase):

    def test_clean_br_tags(self):
        casos = [
            (None, None),
            ("", ""),
            ("Rua A, 123", "Rua A, 123"),
            ("Rua A<br>Bairro X", "Rua A, Bairro X"),
            ("Rua A<br/>Bairro X", "Rua A, Bairro X"),
            ("Rua A<br />Bairro X", "Rua A, Bairro X"),
            ("Rua A<BR>Bairro X", "Rua A, Bairro X"),
            ("Rua A<br>,<br>Bairro X", "Rua A, Bairro X"),
            (",Rua A<br>Bairro X,", "Rua A, Bairro X"),
            ("Rua A<br><br>Bairro X", "Rua A, Bairro X"),
        ]
        for raw, expected in casos:
            with self.subTest(raw=raw):
                self.assertEqual(JournalPayload._clean_br_tags(raw), expected)

    def test_add_contact_aplica_clean_br_tags_no_address(self):
        payload = JournalPayload({})
        payload.add_contact(
            name="Nome Editor",
            email="contato@example.org",
            address="Rua A<br>Bairro X<br>Cidade Y",
            city="Cidade Y",
            state="RJ",
            country="BR",
        )
        self.assertEqual(
            payload.data["contact"],
            {
                "email": "contato@example.org",
                "address": "Rua A, Bairro X, Cidade Y",
            },
        )
        # name/city/state/country não são persistidos atualmente (código comentado)
        self.assertNotIn("publisher_name", payload.data)
        self.assertNotIn("publisher_city", payload.data)


class TestJournalPayloadTimeline(unittest.TestCase):

    def test_add_event_to_timeline_com_event_e_since(self):
        payload = JournalPayload({})
        payload.add_event_to_timeline("ADMITTED", "1999-07-02", "")
        self.assertEqual(
            payload.data["status_history"],
            [{"status": "current", "date": "1999-07-02", "reason": ""}],
        )

    def test_add_event_to_timeline_reason_mapeado(self):
        payload = JournalPayload({})
        payload.add_event_to_timeline("INTERRUPTED", "2020-01-01", "ceased")
        self.assertEqual(
            payload.data["status_history"],
            [{"status": "deceased", "date": "2020-01-01", "reason": "ceased"}],
        )

    def test_add_event_to_timeline_sem_since_nao_adiciona(self):
        payload = JournalPayload({})
        payload.add_event_to_timeline("ADMITTED", None, "")
        self.assertEqual(payload.data["status_history"], [])

    def test_add_event_to_timeline_sem_event_nao_adiciona(self):
        payload = JournalPayload({})
        payload.add_event_to_timeline(None, "2020-01-01", "")
        self.assertEqual(payload.data["status_history"], [])

    def test_add_event_to_timeline_multiplos_eventos_acumulam(self):
        payload = JournalPayload({})
        payload.add_event_to_timeline("ADMITTED", "1999-01-01", "")
        payload.add_event_to_timeline("INTERRUPTED", "2020-01-01", "ceased")
        self.assertEqual(len(payload.data["status_history"]), 2)


class TestJournalPayloadMission(unittest.TestCase):

    def test_add_mission_com_language_e_description(self):
        payload = JournalPayload({})
        payload.add_mission("pt", "Descrição em português")
        self.assertEqual(
            payload.data["mission"],
            [{"language": "pt", "value": "Descrição em português"}],
        )

    def test_add_mission_sem_language_ou_description_nao_adiciona(self):
        casos = [(None, "Descrição"), ("pt", None), ("", "Descrição"), ("pt", "")]
        for language, description in casos:
            with self.subTest(language=language, description=description):
                payload = JournalPayload({})
                payload.add_mission(language, description)
                self.assertEqual(payload.data["mission"], [])


class TestJournalPayloadPublisher(unittest.TestCase):

    def test_add_publisher_ignora_nome_falsy(self):
        payload = JournalPayload({})
        payload.add_publisher(None)
        payload.add_publisher("")
        self.assertEqual(payload.data["institution_responsible_for"], [])

    def test_add_publisher_adiciona_instituicao(self):
        payload = JournalPayload({})
        payload.add_publisher("Fiocruz")
        payload.add_publisher("SciELO")
        self.assertEqual(
            payload.data["institution_responsible_for"],
            [{"name": "Fiocruz"}, {"name": "SciELO"}],
        )


class TestJournalPayloadDefault(unittest.TestCase):

    def test_default_contem_chaves_esperadas(self):
        payload = JournalPayload({})
        default = payload.default
        chaves_esperadas = (
            "id", "logo_url", "mission", "title", "title_iso", "short_title",
            "acronym", "scielo_issn", "print_issn", "electronic_issn",
            "status_history", "subject_areas", "sponsors", "subject_categories",
            "online_submission_url", "contact", "created", "updated",
        )
        for key in chaves_esperadas:
            with self.subTest(key=key):
                self.assertIn(key, default)


# ---------------------------------------------------------------------------
# publish_journal
# ---------------------------------------------------------------------------

def build_journal_proc():
    proc = MagicMock()
    proc.pid = "1678-4463"
    proc.acron = "csp"
    proc.availability_status = "C"
    proc.updated_by = "user_updated"
    proc.creator = "user_creator"

    journal = MagicMock()
    journal.core_synchronized = False
    journal.issn_print = "0102-311X"
    journal.issn_electronic = "1678-4464"
    proc.journal = journal

    collection = MagicMock()
    collection.acron = "scl"
    proc.collection = collection

    return proc


class TestPublishJournal(unittest.TestCase):

    def setUp(self):
        self.journal_proc = build_journal_proc()

        patcher_fetch = patch.object(mod, "fetch_and_create_journal")
        patcher_history = patch.object(mod, "JournalHistory")
        patcher_build = patch.object(mod, "build_journal")
        patcher_api = patch.object(mod, "PublicationAPI")

        self.mock_fetch = patcher_fetch.start()
        self.mock_journal_history = patcher_history.start()
        self.mock_build_journal = patcher_build.start()
        self.mock_api_cls = patcher_api.start()

        self.addCleanup(patcher_fetch.stop)
        self.addCleanup(patcher_history.stop)
        self.addCleanup(patcher_build.stop)
        self.addCleanup(patcher_api.stop)

    def test_nao_sincroniza_com_core_quando_ja_sincronizado(self):
        self.journal_proc.journal.core_synchronized = True
        mock_api_instance = self.mock_api_cls.return_value
        mock_api_instance.post_data.return_value = {"ok": True}

        result = publish_journal(self.journal_proc, {"config": "x"})

        self.mock_fetch.assert_not_called()
        self.assertEqual(result, {"ok": True})

    def test_sincroniza_com_core_quando_nao_sincronizado(self):
        publish_journal(self.journal_proc, {"config": "x"})

        self.mock_fetch.assert_called_once()
        _, kwargs = self.mock_fetch.call_args
        self.assertEqual(kwargs["user"], self.journal_proc.updated_by)
        self.assertEqual(kwargs["collection_acron"], "scl")
        self.assertTrue(kwargs["force_update"])
        # ATENÇÃO: nomes de parâmetros parecem trocados no código original:
        # issn_electronic recebe journal.issn_print e issn_print recebe
        # journal.issn_electronic. Este teste documenta o comportamento
        # ATUAL (possivelmente um bug) — se corrigirem o código, este
        # teste deve ser atualizado.
        self.assertEqual(kwargs["issn_electronic"], self.journal_proc.journal.issn_electronic)
        self.assertEqual(kwargs["issn_print"], self.journal_proc.journal.issn_print)

    def test_usa_creator_quando_updated_by_ausente(self):
        self.journal_proc.updated_by = None

        publish_journal(self.journal_proc, {"config": "x"})

        _, kwargs = self.mock_fetch.call_args
        self.assertEqual(kwargs["user"], self.journal_proc.creator)

    def test_exception_no_fetch_e_silenciosamente_ignorada(self):
        """
        Comportamento atual: qualquer exceção em fetch_and_create_journal
        é engolida por um `except: pass` sem log. O fluxo continua
        normalmente até postar o payload. Vale revisar se isso é desejado,
        pois erros de sincronização com o Core ficam invisíveis.
        """
        self.mock_fetch.side_effect = Exception("erro de rede")
        mock_api_instance = self.mock_api_cls.return_value
        mock_api_instance.post_data.return_value = {"ok": True}

        result = publish_journal(self.journal_proc, {"config": "x"})

        self.assertEqual(result, {"ok": True})
        self.mock_build_journal.assert_called_once()

    def test_filtra_journal_history_pela_collection_e_journal_corretos(self):
        publish_journal(self.journal_proc, {"config": "x"})

        self.mock_journal_history.objects.filter.assert_called_once_with(
            journal_collection__collection=self.journal_proc.collection,
            journal_collection__journal=self.journal_proc.journal,
        )

    def test_chama_build_journal_com_argumentos_corretos(self):
        mock_history_qs = self.mock_journal_history.objects.filter.return_value

        publish_journal(self.journal_proc, {"config": "x"})

        args, _ = self.mock_build_journal.call_args
        (
            payload_builder,
            journal,
            journal_pid,
            journal_acron,
            journal_history,
            availability_status,
        ) = args
        self.assertIsInstance(payload_builder, JournalPayload)
        self.assertEqual(journal, self.journal_proc.journal)
        self.assertEqual(journal_pid, self.journal_proc.pid)
        self.assertEqual(journal_acron, self.journal_proc.acron)
        self.assertEqual(journal_history, mock_history_qs)
        self.assertEqual(availability_status, self.journal_proc.availability_status)

    def test_instancia_publication_api_com_api_data_e_posta_payload(self):
        api_data = {"base_url": "http://example.org", "token": "abc"}
        mock_api_instance = self.mock_api_cls.return_value
        mock_api_instance.post_data.return_value = {"status": "published"}

        result = publish_journal(self.journal_proc, api_data)

        self.mock_api_cls.assert_called_once_with(**api_data)
        mock_api_instance.post_data.assert_called_once()
        self.assertEqual(result, {"status": "published"})


if __name__ == "__main__":
    unittest.main()