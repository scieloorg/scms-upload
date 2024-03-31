import logging
import os
import sys
from copy import deepcopy
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED

from django.utils.translation import gettext_lazy as _
from scielo_classic_website import classic_ws

from htmlxml.models import HTMLXML
from migration.models import MigratedFile
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.sps.models.article_and_subarticles import ArticleAndSubArticles
from packtools.sps.models.v2.article_assets import ArticleAssets

from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback

from .models import ClassicWebsiteConfiguration


class XMLVersionXmlWithPreError(Exception):
    ...


def get_classic_website(collection_acron):
    try:
        config = ClassicWebsiteConfiguration.objects.get(
            collection__acron=collection_acron
        )
        return classic_ws.ClassicWebsite(
            bases_path=os.path.join(os.path.dirname(config.bases_work_path), "bases"),
            bases_work_path=config.bases_work_path,
            bases_translation_path=config.bases_translation_path,
            bases_pdf_path=config.bases_pdf_path,
            bases_xml_path=config.bases_xml_path,
            htdocs_img_revistas_path=config.htdocs_img_revistas_path,
            serial_path=config.serial_path,
            cisis_path=config.cisis_path,
            title_path=config.title_path,
            issue_path=config.issue_path,
        )
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            e=e,
            exc_traceback=exc_traceback,
            detail={
                "function": "migration.controller.get_classic_website",
                "collection_acron": collection_acron,
            },
        )


def import_one_issue_files(user, issue_proc, force_update):
    importer = IssueFolderImporter(user, force_update)
    return importer.import_issue_files(issue_proc)


class IssueFolderImporter:
    def __init__(self, user, force_update):
        self.force_update = force_update
        self.user = user

    @staticmethod
    def _get_classic_website_rel_path(file_path):
        if "htdocs" in file_path:
            return file_path[file_path.find("htdocs") :]
        if "bases" in file_path:
            return file_path[file_path.find("bases") :]

    @staticmethod
    def check_component_type(file):
        if file["type"] == "pdf":
            check = file["name"]
            try:
                check = check.replace(file["lang"] + "_", "")
            except (KeyError, TypeError):
                pass
            try:
                check = check.replace(file["key"], "")
            except (KeyError, TypeError):
                pass
            if check == ".pdf":
                return "rendition"
            return "supplmat"
        return file["type"]

    def import_issue_files(self, issue_proc):
        """
        Migra os arquivos do fascículo (pdf, img, xml ou html)
        """

        collection = issue_proc.collection
        classic_website = get_classic_website(collection.acron)
        journal_acron = issue_proc.journal_proc.acron

        failures = []
        migrated = []
        files_and_exceptions = classic_website.get_issue_files_and_exceptions(
            journal_acron,
            issue_proc.issue_folder,
        )

        classic_issue_files = files_and_exceptions["files"]
        exceptions = files_and_exceptions["exceptions"]
        # {"message": e.message, "type": str(type(e))}

        try:
            for file in classic_issue_files:
                # {"type": "pdf", "key": name, "path": path, "name": basename, "lang": lang}
                # {"type": "xml", "key": name, "path": path, "name": basename, }
                # {"type": "html", "key": name, "path": path, "name": basename, "lang": lang, "part": label}
                # {"type": "asset", "path": item, "name": os.path.basename(item)}
                try:
                    component_type = IssueFolderImporter.check_component_type(file)

                    part = file.get("part")
                    if part == "before":
                        # html antes das referencias
                        part = "1"
                    elif part == "after":
                        # html após das referencias
                        part = "2"

                    migrated_file = MigratedFile.create_or_update(
                        user=self.user,
                        collection=collection,
                        original_path=IssueFolderImporter._get_classic_website_rel_path(
                            file["path"]
                        ),
                        source_path=file["path"],
                        component_type=component_type,
                        lang=file.get("lang"),
                        part=part,
                        pkg_name=file.get("key"),
                        force_update=self.force_update,
                    )
                    migrated.append(migrated_file)
                except Exception as e:
                    failures.append(
                        {"file": file, "message": str(e), "type": str(type(e))}
                    )
        except Exception as e:
            failures.append({
                "files from": f"{journal_acron} {issue_proc.issue_folder}",
                "message": str(e), "type": str(type(e))}
            )
        return {"migrated": migrated, "failures": failures, "exceptions": exceptions}


def get_article_records_from_classic_website(
    user,
    issue_proc,
    ArticleProcClass,
    force_update=False,
):
    """
    Cria registros ArticleProc com dados obtidos de base de dados ISIS
    de artigos
    """
    importer = DocumentRecordsImporter(user, issue_proc, ArticleProcClass, force_update)
    return importer.import_documents_records()


class DocumentRecordsImporter:
    def __init__(self, user, issue_proc, ArticleProcClass, force_update=False):
        self.user = user
        self.force_update = force_update

        self.issue_proc = issue_proc
        self.issue_folder = issue_proc.issue_folder
        self.issue_pid = issue_proc.pid
        self.collection = issue_proc.collection

        self.classic_website = get_classic_website(self.collection.acron)

        j = issue_proc.journal_proc
        self.journal_issue_and_doc_data = {"title": j.migrated_data.data}
        self.journal_acron = j.acron
        self.ArticleProcClass = ArticleProcClass

    def import_documents_records(self):
        migrated = []
        failures = []
        for doc_id, doc_records in self.classic_website.get_documents_pids_and_records(
            self.journal_acron,
            self.issue_folder,
            self.issue_pid,
        ):
            try:

                if len(doc_records) == 1:
                    # é possível que em source_file_path exista registro tipo i
                    self.journal_issue_and_doc_data["issue"] = doc_records[0]
                    continue

                article_proc = self.import_document_records(doc_id, doc_records)
                migrated.append({
                    "pid": article_proc.pid,
                    "pkg_name": article_proc.pkg_name,
                    "records": list(article_proc.migrated_data.document.document_records.stats),
                })
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                failures.append(
                    {
                        "doc_id": doc_id,
                        "exc_traceback": format_traceback(exc_traceback),
                    }
                )

        return {"migrated": migrated, "failures": failures}

    def import_document_records(self, doc_id, doc_records):
        # une os dados de journal, issue e docs
        records = self.merge_journal_issue_and_docs_records(doc_records)

        # instancia Document com os dados de journal, issue e docs
        classic_ws_doc = classic_ws.Document(records)

        # verifica se pid do documento pertence ao issue,
        # levanta exceção caso não seja
        pid = self.get_valid_pid(classic_ws_doc)

        if classic_ws_doc.scielo_pid_v2 != pid:
            classic_ws_doc.scielo_pid_v2 = pid

        # obtém os registros de parágrafo
        pid_, p_records = self.classic_website.get_p_records(pid)
        p_records = list(p_records or [])
        if p_records:
            records["article"].extend(p_records)
            # instancia novamente Document com os dados de journal, issue e docs
            classic_ws_doc = classic_ws.Document(records)

        # cria o registro de migração
        return self.create_scielo_data_record_and_article_proc(classic_ws_doc, records)

    def merge_journal_issue_and_docs_records(self, doc_records):
        if not self.journal_issue_and_doc_data.get("issue"):
            self.journal_issue_and_doc_data[
                "issue"
            ] = self.issue_proc.migrated_data.data

        records = deepcopy(self.journal_issue_and_doc_data)
        records["article"] = doc_records
        return records

    def get_valid_pid(self, classic_ws_doc):
        pid = classic_ws_doc.scielo_pid_v2 or (
            "S" + self.issue_pid + classic_ws_doc.order.zfill(5)
        )
        if len(pid) != 23:
            info = {
                "classic_ws_doc.scielo_pid_v2": classic_ws_doc.scielo_pid_v2,
                "order": classic_ws_doc.order,
                "issue_pid": self.issue_pid,
            }
            raise ValueError(
                f"Expected 23-characters pid. Found {pid} ({len(pid)}) {info}"
            )

        if self.issue_pid not in pid:
            raise ValueError(
                f"Article data {pid} does not belong to "
                f"{self.issue_proc} {self.issue_pid}"
            )
        return pid

    def create_scielo_data_record_and_article_proc(self, classic_ws_doc, records):
        article_proc = self.ArticleProcClass.register_classic_website_data(
            user=self.user,
            collection=self.collection,
            pid=classic_ws_doc.scielo_pid_v2,
            data=records,
            content_type="article",
            force_update=self.force_update,
        )

        if article_proc.migration_status != tracker_choices.PROGRESS_STATUS_TODO:
            return article_proc

        article_proc.update(
            issue_proc=self.issue_proc,
            pkg_name=classic_ws_doc.filename_without_extension,
            migration_status=tracker_choices.PROGRESS_STATUS_TODO,
            user=self.user,
            main_lang=classic_ws_doc.original_language,
            force_update=self.force_update,
        )
        if classic_ws_doc.file_type == "html":
            HTMLXML.create_or_update(
                user=self.user,
                migrated_article=article_proc.migrated_data,
                n_references=len(classic_ws_doc.citations or []),
                record_types="|".join(classic_ws_doc.record_types or []),
            )
        return article_proc


class PkgZipBuilder:
    def __init__(self, xml_with_pre):
        self.xml_with_pre = xml_with_pre
        self.sps_pkg_name = xml_with_pre.sps_pkg_name
        self.components = {}
        self.texts = {}

    def build_sps_package(
        self,
        output_folder,
        renditions,
        translations,
        main_paragraphs_lang,
        issue_proc,
    ):
        """
        A partir do XML original ou gerado a partir do HTML, e
        dos ativos digitais, todos registrados em MigratedFile,
        cria o zip com nome no padrão SPS (ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE) e
        o armazena em SPSPkg.not_optimised_zip_file.
        Neste momento o XML não contém pid v3.
        """
        # gera nome de pacote padrão SPS ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE

        sps_pkg_zip_path = os.path.join(output_folder, f"{self.sps_pkg_name}.zip")

        # cria pacote zip
        with ZipFile(sps_pkg_zip_path, "w", compression=ZIP_DEFLATED) as zf:

            # A partir do XML, obtém os nomes dos arquivos dos ativos digitais
            self._build_sps_package_add_assets(zf, issue_proc)

            # add renditions (pdf) to zip
            result = self._build_sps_package_add_renditions(
                zf, renditions, translations, main_paragraphs_lang
            )
            self.texts.update(result)

            # adiciona XML em zip
            self._build_sps_package_add_xml(zf)

        return sps_pkg_zip_path

    def _build_sps_package_add_renditions(
        self, zf, renditions, translations, main_paragraphs_lang
    ):
        xml = ArticleAndSubArticles(self.xml_with_pre.xmltree)
        xml_langs = []
        for item in xml.data:
            if item.get("lang"):
                xml_langs.append(item.get("lang"))

        pdf_langs = []

        logging.info(renditions)
        for rendition in renditions:
            try:
                if rendition.lang:
                    sps_filename = f"{self.sps_pkg_name}-{rendition.lang}.pdf"
                    pdf_langs.append(rendition.lang)
                else:
                    sps_filename = f"{self.sps_pkg_name}.pdf"
                    pdf_langs.append(xml_langs[0])

                zf.write(rendition.file.path, arcname=sps_filename)

                self.components[sps_filename] = {
                    "lang": rendition.lang,
                    "legacy_uri": rendition.original_href,
                    "component_type": "rendition",
                }
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                self.components[rendition.original_name] = {
                    "failures": format_traceback(exc_traceback),
                }
        html_langs = list(translations.keys())
        try:
            if main_paragraphs_lang:
                html_langs.append(main_paragraphs_lang)
        except Exception as e:
            pass

        return {
            "xml_langs": xml_langs,
            "pdf_langs": pdf_langs,
            "html_langs": html_langs,
        }

    def _build_sps_package_add_assets(self, zf, issue_proc):
        replacements = {}
        subdir = os.path.join(
            issue_proc.journal_proc.acron,
            issue_proc.issue_folder,
        )
        xml_assets = ArticleAssets(self.xml_with_pre.xmltree)
        for xml_graphic in xml_assets.items:
            try:
                if replacements.get(xml_graphic.xlink_href):
                    continue

                basename = os.path.basename(xml_graphic.xlink_href)
                name, ext = os.path.splitext(basename)

                found = False

                # procura a "imagem" no contexto do "issue"
                for asset in issue_proc.find_asset(basename, name):
                    found = True
                    self._build_sps_package_add_asset(
                        zf,
                        asset,
                        xml_graphic,
                        replacements,
                    )
                if not found:
                    # procura a "imagem" no contexto da coleção
                    for asset in MigratedFile.find(
                        collection=issue_proc.collection,
                        xlink_href=xml_graphic.xlink_href,
                        subdir=subdir,
                    ):
                        found = True
                        self._build_sps_package_add_asset(
                            zf,
                            asset,
                            xml_graphic,
                            replacements,
                        )

                if not found:
                    self.components[xml_graphic.xlink_href] = {
                        "failures": "Not found",
                    }

            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                self.components[xml_graphic.xlink_href] = {
                    "failures": format_traceback(exc_traceback),
                }
        xml_assets.replace_names(replacements)

    def _build_sps_package_add_asset(
        self,
        zf,
        asset,
        xml_graphic,
        replacements,
    ):
        try:
            # obtém o nome do arquivo no padrão sps
            sps_filename = xml_graphic.name_canonical(self.sps_pkg_name)

            # indica a troca de href original para o padrão SPS
            replacements[xml_graphic.xlink_href] = sps_filename

            # adiciona arquivo ao zip
            zf.write(asset.file.path, arcname=sps_filename)

            component_type = (
                "supplementary-material"
                if xml_graphic.is_supplementary_material
                else "asset"
            )
            self.components[sps_filename] = {
                "xml_elem_id": xml_graphic.id,
                "legacy_uri": asset.original_href,
                "component_type": component_type,
            }
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.components[xml_graphic.xlink_href] = {
                "failures": format_traceback(exc_traceback),
            }

    def _build_sps_package_add_xml(self, zf):
        try:
            sps_xml_name = self.sps_pkg_name + ".xml"
            zf.writestr(sps_xml_name, self.xml_with_pre.tostring(pretty_print=True))
            self.components[sps_xml_name] = {"component_type": "xml"}
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.components[sps_xml_name] = {
                "component_type": "xml",
                "failures": format_traceback(exc_traceback),
            }


def get_migrated_xml_with_pre(article_proc):
    origin = None
    try:
        obj = HTMLXML.get(migrated_article=article_proc.migrated_data)
        origin = "html"
    except HTMLXML.DoesNotExist:
        obj = article_proc.migrated_xml
        origin = "xml"

    try:
        xml_file_path = None
        xml_file_path = obj.file.path
        for item in XMLWithPre.create(path=xml_file_path):
            if article_proc.pid and item.v2 != article_proc.pid:
                # corrige ou adiciona pid v2 no XML nativo ou obtido do html
                # usando o valor do pid v2 do site clássico
                item.v2 = article_proc.pid

            order = str(int(article_proc.pid[-5:]))
            if not item.order or str(int(item.order)) != order:
                # corrige ou adiciona other pid no XML nativo ou obtido do html
                # usando o valor do "order" do site clássico
                item.order = article_proc.pid[-5:]
            return item
    except Exception as e:
        raise XMLVersionXmlWithPreError(
            _("Unable to get xml with pre from migrated article ({}) {}: {} {}").format(
                origin, xml_file_path, type(e), e
            )
        )
