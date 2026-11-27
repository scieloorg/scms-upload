import os
import shutil
import tempfile
from unittest.mock import MagicMock, PropertyMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from proc.models import ArticleProc


class SaveProcessedXmlNameTest(TestCase):
    """
    O nome do arquivo de processed_xml é o nome do pacote nas leituras
    seguintes; save_processed_xml apaga o arquivo atual do próprio
    ArticleProc antes de salvar, para que o storage não acrescente um
    sufixo aleatório (ex.: 0034-8910-rsp-38-02-24_Ba7KXdi).
    """

    PID = "S0034-89102004000200024"
    SPS_PKG_NAME = "0034-8910-rsp-38-02-24"
    TARGET = "proc/0034/8910/rsp/38/02/24/0034-8910-rsp-38-02-24.xml"

    def setUp(self):
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, True)
        settings_override = override_settings(MEDIA_ROOT=media_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.media_root = media_root
        self.user = get_user_model().objects.create(username="u")

        # relações usadas por save_processed_xml, sem depender do banco
        for name, value in (
            ("collection", MagicMock(acron="scl")),
            ("journal_proc", MagicMock(acron="rsp")),
            ("sps_pkg", None),
        ):
            patcher = patch.object(
                ArticleProc, name, new_callable=PropertyMock, return_value=value
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_file(self, content="<article/>"):
        path = os.path.join(self.media_root, self.TARGET)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fp:
            fp.write(content)

    def read_file(self):
        with open(os.path.join(self.media_root, self.TARGET)) as fp:
            return fp.read()

    def make_xml_with_pre(self):
        xml_with_pre = MagicMock()
        xml_with_pre.v2 = self.PID
        xml_with_pre.order = "24"
        xml_with_pre.article_publication_date = "2004-04-01"
        xml_with_pre.collection = "scl"
        xml_with_pre.journal_acron = "rsp"
        xml_with_pre.build_sps_pkg_name.return_value = self.SPS_PKG_NAME
        xml_with_pre.data = {}
        xml_with_pre.tostring.return_value = "<article>novo</article>"
        return xml_with_pre

    def save(self, article_proc):
        article_proc.save_processed_xml(self.make_xml_with_pre(), {}, None)
        return article_proc.processed_xml.name

    def test_caminho_livre(self):
        article_proc = ArticleProc.objects.create(creator=self.user, pid=self.PID)

        self.assertEqual(self.save(article_proc), self.TARGET)
        self.assertEqual(self.read_file(), "<article>novo</article>")

    def test_arquivo_do_proprio_article_proc_e_substituido(self):
        self.write_file()
        article_proc = ArticleProc.objects.create(
            creator=self.user, pid=self.PID, processed_xml=self.TARGET
        )

        self.assertEqual(self.save(article_proc), self.TARGET)
        self.assertEqual(self.read_file(), "<article>novo</article>")

    def test_arquivo_de_outro_article_proc_e_mantido(self):
        self.write_file()
        ArticleProc.objects.create(creator=self.user, processed_xml=self.TARGET)
        article_proc = ArticleProc.objects.create(creator=self.user, pid=self.PID)

        name = self.save(article_proc)

        self.assertNotEqual(name, self.TARGET)
        self.assertEqual(self.read_file(), "<article/>")
