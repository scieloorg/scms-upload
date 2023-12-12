import logging
import os
import sys
from copy import deepcopy
from datetime import datetime

from django.utils.translation import gettext_lazy as _
from scielo_classic_website import classic_ws

from htmlxml.models import HTMLXML
from migration.models import MigratedFile
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback

from .models import ClassicWebsiteConfiguration


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
        classic_issue_files = classic_website.get_issue_files(
            journal_acron,
            issue_proc.issue_folder,
        )
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
                exc_type, exc_value, exc_traceback = sys.exc_info()
                failures.append(
                    {"file": file, "exc_traceback": format_traceback(exc_traceback)}
                )
        return {"migrated": migrated, "failures": failures}


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

                migrated.append(self.import_document_records(doc_id, doc_records))
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
            force_update=self.force_update,
        )
        if classic_ws_doc.file_type == "html":
            HTMLXML.create_or_update(
                user=self.user,
                article_proc=article_proc,
                n_paragraphs=len(classic_ws_doc.p_records or []),
                n_references=len(classic_ws_doc.citations or []),
                record_types="|".join(classic_ws_doc.record_types or []),
            )
        return article_proc
