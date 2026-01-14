import logging
import os
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from zipfile import ZIP_DEFLATED, ZipFile

from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from packtools.sps.models.article_and_subarticles import ArticleAndSubArticles
from packtools.sps.models.v2.article_assets import ArticleAssets
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from article.models import Article
from collection.models import Language
from core.controller import parse_yyyymmdd
from htmlxml.models import HTMLXML
from institution.models import Institution
from issue.models import TOC, Issue, TocSection
from journal.models import (
    Journal,
    JournalCollection,
    JournalHistory,
    Mission,
    OfficialJournal,
    Owner,
    Publisher,
    Subject,
)
from location.models import Location
from migration.models import IdFileRecord, JournalAcronIdFile, MigratedFile
from scielo_classic_website import classic_ws
from scielo_classic_website.iid2json.id2json3 import get_doc_records
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback

from .models import ClassicWebsiteConfiguration


class IdFileRecordIsAlreadyUptodate(Exception):
    pass

def get_classic_website_config(collection_acron):
    return ClassicWebsiteConfiguration.objects.get(collection__acron=collection_acron)


def create_or_update_journal(
    user,
    journal_proc,
    force_update,
    **kwargs,
):
    """
    Create/update OfficialJournal, JournalProc e Journal
    """
    params = {}
    try:
        journal_proc_event = journal_proc.start(user, "create_or_update_journal")
        collection = journal_proc.collection
        journal_data = journal_proc.migrated_data.data

        # obtém classic website journal
        classic_website_journal = classic_ws.Journal(journal_data)

        year, month, day = parse_yyyymmdd(classic_website_journal.first_year)
    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 1: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        journal_proc_event.finish(
            user,
            completed=False,
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        eissn = classic_website_journal.electronic_issn
        pissn = classic_website_journal.print_issn
        params = dict(
            issn_electronic=eissn,
            issn_print=pissn,
            title=classic_website_journal.title,
            title_iso=classic_website_journal.title_iso,
            foundation_year=year,
        )
        if not eissn and not pissn:
            raise ValueError(
                f"Before migrating, use Title Manager or SciELO Manager to complete print ISSN and/or electronic ISSN for {classic_website_journal.title}"
            )
        official_journal = OfficialJournal.create_or_update(user=user, **params)
        official_journal.add_related_journal(
            classic_website_journal.previous_title,
            classic_website_journal.next_title,
        )

    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 2: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        params["event"] = "OfficialJournal.create_or_update"
        journal_proc_event.finish(
            user,
            completed=False,
            detail=params,
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        params = dict(
            short_title=classic_website_journal.abbreviated_title,
            title=classic_website_journal.title,
            journal_acron=classic_website_journal.acronym,
        )
        journal = Journal.create_or_update(
            user=user,
            official_journal=official_journal,
            **params,
        )
        journal.license_code = classic_website_journal.permissions
        journal.nlm_title = classic_website_journal.title_nlm
        journal.doi_prefix = None
        raw_names = classic_website_journal.raw_publisher_names or []
        journal.contact_name = "; ".join([str(name) for name in raw_names if name])
        journal.contact_location = Location.create_or_update(
            user=user,
            city_name=classic_website_journal.publisher_city,
            state_acronym=classic_website_journal.publisher_state,
            country_acronym=classic_website_journal.publisher_country,
        )
        journal.contact_address = ", ".join(classic_website_journal.publisher_address)
        journal.add_email(classic_website_journal.publisher_email)
        # core wos_areas
        journal.wos_areas = classic_website_journal.wos_subject_areas
        journal.save()

    except Exception as e:
        try:
            if journal and hasattr(journal, 'contact_address') and journal.contact_address:
                logging.info(len(journal.contact_address))
        except:
            pass
        logging.exception(f"Exception: create_or_update_journal: 3: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        params["event"] = "Journal.create_or_update"
        journal_proc_event.finish(
            user,
            completed=False,
            detail=params,
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        missions = {}
        for item in classic_website_journal.mission:
            text = item["text"]
            lang = item["language"]
            missions.setdefault(lang, [])
            missions[lang].append(text)

            for lang, text in missions.items():
                language = Language.get_or_create(name=None, code2=lang, creator=user)
                journal.mission.add(
                    Mission.create_or_update(user, journal, language, "\n".join(text))
                )
    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 4: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        journal_proc_event.finish(
            user,
            completed=False,
            detail={"missions": missions, "advice": "Remove line breaks"},
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        for code in classic_website_journal.subject_areas:
            journal.subject.add(Subject.create_or_update(user, code))
    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 5: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        journal_proc_event.finish(
            user,
            completed=False,
            detail={"subject_areas": classic_website_journal.subject_areas},
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        for publisher_name in (classic_website_journal.raw_publisher_names or []):
            institution = Institution.get_or_create(
                inst_name=publisher_name,
                inst_acronym=None,
                level_1=None,
                level_2=None,
                level_3=None,
                location=None,
                user=user,
            )
            journal.owner.add(Owner.create_or_update(user, journal, institution))
            journal.publisher.add(
                Publisher.create_or_update(user, journal, institution)
            )
    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 6: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        journal_proc_event.finish(
            user,
            completed=False,
            detail={"publisher_name": classic_website_journal.raw_publisher_names},
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        jc = JournalCollection.create_or_update(user, collection, journal)
        create_journal_history(user, jc, classic_website_journal)
    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 7: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        journal_proc_event.finish(
            user,
            completed=False,
            detail={"status_history": classic_website_journal.status_history},
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e

    try:
        params = dict(
            acron=classic_website_journal.acronym,
            title=classic_website_journal.title,
            availability_status=classic_website_journal.current_status,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            force_update=force_update,
        )
        journal_proc.update(user=user, journal=journal, **params)
        journal_proc_event.finish(user, completed=True, detail=params)

    except Exception as e:
        logging.exception(f"Exception: create_or_update_journal: 8: {e}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        params["event"] = "journal_proc.update"
        journal_proc_event.finish(
            user,
            completed=False,
            detail=params,
            exception=e,
            exc_traceback=exc_traceback,
        )
        raise e
    return journal


def create_journal_history(user, jc, classic_website_journal):
    status_items = {
        "D": "INTERRUPTED",
        "S": "INTERRUPTED",
        "C": "ADMITTED",
    }
    for event in classic_website_journal.status_history:
        # obtém year, month, day
        _date = event["date"]
        year, month, day = parse_yyyymmdd(_date)

        # obtém event_type
        _status = event["status"]
        event_type = status_items.get(_status)

        # obtém interruption_reason
        _reason = event.get("reason")
        interruption_reason = None
        if _status == "D":
            interruption_reason = "ceased"
        else:
            interruption_reason = _reason

        JournalHistory.create_or_update(
            user, jc, event_type, year, month, day, interruption_reason
        )


def create_or_update_issue(
    user,
    issue_proc,
    force_update,
    JournalProc,
):
    """
    Create/update Issue
    """
    classic_website_issue = classic_ws.Issue(issue_proc.migrated_data.data)

    try:
        journal_proc = JournalProc.get(
            collection=issue_proc.collection,
            pid=classic_website_issue.journal,
        )
    except JournalProc.DoesNotExist:
        raise ValueError(
            f"Unable to get journal_proc for issue_proc: collection={issue_proc.collection}, pid={classic_website_issue.journal}"
        )
    if not journal_proc.journal:
        raise ValueError(f"Missing JournalProc.journal for {journal_proc}")

    issue = Issue.get_or_create(
        journal=journal_proc.journal,
        publication_year=classic_website_issue.publication_year,
        volume=classic_website_issue.volume,
        number=classic_website_issue.number,
        supplement=classic_website_issue.supplement,
        user=user,
        is_continuous_publishing_model=bool(
            not classic_website_issue.number and not classic_website_issue.supplement
        ),
        total_documents=classic_website_issue.total_documents,
        order=int(classic_website_issue.order[-4:]),
        issue_pid_suffix=classic_website_issue.order[-4:],
    )
    issue_proc.update(
        user=user,
        journal_proc=journal_proc,
        issue_folder=classic_website_issue.issue_label,
        issue=issue,
        migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        force_update=force_update,
    )

    toc = TOC.create_or_update(
        user,
        issue,
        ordered=True,
    )
    languages = {}
    for code, sections in classic_website_issue.sections_by_code.items():
        issue_section = None
        for section in sections:
            lang_code = section.get("language")
            text = section.get("text")
            # reduz consulta em banco de dados
            try:
                language = languages[lang_code]
            except KeyError:
                language = Language.get_or_create(
                    creator=user, 
                    code2=lang_code, 
                    text_to_detect_language=text,
                )
                languages[lang_code] = language
            sec = issue.journal.add_section(
                user,
                language=language,
                code=section.get("code"),
                text=text,
            )
            TocSection.create_or_update(user, toc, section.get("code"), sec)
    return issue


def create_or_update_article(
    user,
    article_proc,
    force_update,
    **kwargs,
):
    """
    Create/update Issue
    """
    article = Article.create_or_update(
        user,
        article_proc.sps_pkg,
        issue=article_proc.issue_proc.issue,
        journal=article_proc.issue_proc.journal_proc.journal,
    )
    article_proc.migrated_data.migration_status = tracker_choices.PROGRESS_STATUS_DONE
    article_proc.migration_status = tracker_choices.PROGRESS_STATUS_DONE
    article_proc.updated_by = user
    article_proc.save()
    return article


class XMLVersionXmlWithPreError(Exception): ...


def get_classic_website(collection_acron):
    try:
        config = ClassicWebsiteConfiguration.objects.get(
            collection__acron=collection_acron
        )
        bases_path = ""
        if config.bases_work_path:
            bases_path = os.path.join(os.path.dirname(config.bases_work_path), "bases")
        return classic_ws.ClassicWebsite(
            bases_path=bases_path,
            bases_work_path=config.bases_work_path,
            bases_translation_path=config.bases_translation_path,
            bases_pdf_path=config.bases_pdf_path,
            bases_xml_path=config.bases_xml_path,
            htdocs_img_revistas_path=config.htdocs_img_revistas_path,
            serial_path=config.serial_path,
            cisis_path=None,
            title_path=config.title_path,
            issue_path=config.issue_path,
            alternative_paths=config.alternative_htdocs_img_revistas_path,
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


def migrate_issue_files(user, collection, journal_acron, issue_folder, force_update):
    exceptions = []
    migrated_ids = []
    try:
        PARTS = {
            "before": "1",
            "after": "2",
        }
        classic_website = get_classic_website(collection.acron)
        if not classic_website:
            exceptions.append({
                "error": f"Classic website not found for collection {collection.acron}",
                "type": "ValueError"
            })
            return {"exceptions": exceptions, "migrated": migrated_ids}
        
        files_and_exceptions = classic_website.get_issue_folder_content(
            journal_acron,
            issue_folder,
        )
        for file in files_and_exceptions:
            try:
                if not file:
                    continue
                if file.get("error"):
                    exceptions.append(file)
                    continue

                component_type = check_component_type(file)
                part = file.get("part")

                migrated_ids.append(
                    MigratedFile.create_or_update(
                        user=user,
                        collection=collection,
                        original_path=file["relative_path"],
                        source_path=file["path"],
                        component_type=component_type,
                        lang=file.get("lang"),
                        part=part and PARTS.get(part),
                        pkg_name=file.get("key"),
                        force_update=force_update,
                        content=file.get("content"),
                        file_datetime_iso=file.get("modified_date"),
                        basename=file.get("name"),
                    ).id
                )

            except Exception as e:
                exceptions.append({"error": str(e), "type": str(type(e)), "file": file})

    except Exception as e:
        exceptions.append(
            {
                "files from": f"{journal_acron} {issue_folder}",
                "error": str(e),
                "type": str(type(e)),
            }
        )
    return {"exceptions": exceptions, "migrated": migrated_ids}


class PkgZipBuilder:
    def __init__(self, xml_with_pre):
        self.xml_with_pre = xml_with_pre
        self.sps_pkg_name = xml_with_pre.sps_pkg_name
        self.components = {}
        self.texts = {}
        self.replacements = {}

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

        pdf_langs = set()

        for rendition in renditions:
            try:
                if rendition.lang:
                    sps_filename = f"{self.sps_pkg_name}-{rendition.lang}.pdf"
                    pdf_langs.add(rendition.lang)
                else:
                    sps_filename = f"{self.sps_pkg_name}.pdf"
                    pdf_langs.add(xml_langs[0])

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
        html_langs = list(set(translations.keys()))
        try:
            if main_paragraphs_lang:
                html_langs.append(main_paragraphs_lang)
        except Exception as e:
            pass

        return {
            "xml_langs": xml_langs,
            "pdf_langs": list(pdf_langs),
            "html_langs": html_langs,
        }

    def _build_sps_package_add_assets(self, zf, issue_proc):
        self.replacements = {}
        not_found = []
        xml_assets = ArticleAssets(self.xml_with_pre.xmltree)
        for xml_graphic in xml_assets.items:
            try:
                if self.replacements.get(xml_graphic.xlink_href):
                    continue
                basename = os.path.basename(xml_graphic.xlink_href)
                name, ext = os.path.splitext(basename)                
                items = issue_proc.find_asset(basename, name)

                if not items.exists():
                    not_found.append(xml_graphic.xlink_href)
                    continue

                component_type = (
                    "supplementary-material"
                    if xml_graphic.is_supplementary_material
                    else "asset"
                )

                for asset in items:
                    # obtém o nome do arquivo no padrão sps
                    sps_filename = xml_graphic.name_canonical(self.sps_pkg_name).lower()

                    # indica a troca de href original para o padrão SPS
                    self.replacements[xml_graphic.xlink_href] = sps_filename

                    # adiciona arquivo ao zip
                    zf.write(asset.file.path, arcname=sps_filename)

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

        xml_assets.replace_names(self.replacements)
        if not_found:
            logging.exception(f"build_sps_package not found {not_found}")
        for item in not_found:
            self.components[item] = {"failures": "Not found"}

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


def register_acron_id_file_content(
    user,
    journal_proc,
    force_update,
):
    """
    Para um dado JournalAcronIdFile, criar itens em IdFileRecord
    """
    detail = {}
    stats = {}
    output = {}

    try:
        detail["params"] = {
            "journal_acron": journal_proc.acron,
            "force_update": force_update,
        }
        
        collection = journal_proc.collection
        journal_acron = journal_proc.acron
        collection_acron = collection.acron

        classic_website = get_classic_website(collection_acron)
        source_path = os.path.join(
            classic_website.classic_website_paths.bases_work_path,
            journal_acron,
            journal_acron + ".id",
        )
        
        datetime_now = datetime.now(timezone.utc).isoformat()
        logging.info(f"Processing {source_path} at {datetime_now}")
        journal_id_file = JournalAcronIdFile.create_or_update(
            user=user,
            collection=collection,
            journal_acron=journal_acron,
            source_path=source_path,
            force_update=force_update,
        )
        
        if not force_update and not id_file_record_need_to_be_updated(
            journal_id_file, datetime_now, output, stats
        ):
            raise IdFileRecordIsAlreadyUptodate(
                _("IdFileRecord is already up-to-date with acron.id")
            )
        logging.info(f"Updating IdFileRecord from {source_path}")
        latest = journal_id_file.id_file_records.order_by("-updated").first()
        t1 = latest.updated.isoformat()
    
        for item in get_bases_work_acron_id_file_records(
            user,
            source_path,
            classic_website,
            journal_proc,
        ):
            item["force_update"] = force_update
            item["todo"] = True
            IdFileRecord.create_or_update(
                user,
                journal_id_file,
                **item,
            )
        t2 = latest.updated.isoformat()
        if t1 == t2:
            latest.updated = datetime.now(timezone.utc).isoformat()
            latest.save()

        qs = journal_id_file.id_file_records.filter(item_type="article")
        total_document_records = qs.count()
        article_pids = list(qs.filter(todo=True).values_list("item_pid", flat=True).distinct())
        
        stats["total_document_records_after"] = total_document_records
        stats["total_document_records_to_migrate_after"] = len(article_pids)
        stats["total_document_records_new"] = journal_id_file.id_file_records.filter(
            updated__gte=datetime_now,
        ).count()
        detail["article_pids"] = article_pids
        detail["stats"] = stats
        detail["output"] = output
        return detail
    except FileNotFoundError as e:
        raise FileNotFoundError(f"File not found: {source_path}")
    except IdFileRecordIsAlreadyUptodate as e:
        output["message"] = str(e)
        detail["stats"] = stats
        detail["output"] = output
        return detail
    except Exception as e:
        output["traceback"] = traceback.format_exc()
        detail["output"] = output
        return detail


def id_file_record_need_to_be_updated(journal_id_file, datetime_now, output, stats):
    output["datetime_now"] = datetime_now
    
    journal_id_file_updated = journal_id_file.updated.isoformat()
    logging.info(f"journal_id_file.updated: {journal_id_file_updated}")
    output["journal_id_file_updated"] = journal_id_file_updated

    journal_id_file_changed = datetime_now < journal_id_file_updated
    
    qs = journal_id_file.id_file_records.filter(item_type="article")
    total_document_records = qs.count()
    total_document_records_to_migrate = qs.filter(todo=True).count()
    
    stats["total_document_records_before"] = total_document_records
    stats["total_document_records_to_migrate_before"] = total_document_records_to_migrate
    stats["total_document_records"] = total_document_records

    if total_document_records == 0:
        return True
    
    id_file_record_last_updated = qs.order_by("-updated").first().updated.isoformat()
    logging.info(f"id_file_record_last_updated: {id_file_record_last_updated}")
    if journal_id_file_updated > id_file_record_last_updated:
        return True
    return False


def get_bases_work_acron_id_file_records(
    user, source_path, classic_website, journal_proc
):
    try:
        event = None
        event = journal_proc.start(user, "get_bases_work_acron_id_file_records")
        for item in get_doc_records(source_path):
            try:
                issue_id = item.get("issue_id")
                doc_id = item.get("doc_id")
                if doc_id:
                    yield dict(
                        item_type="article",
                        item_pid=doc_id,
                        data=item["doc_data"],
                    )

                elif issue_id:
                    yield dict(
                        item_type="issue",
                        item_pid=issue_id,
                        data=item["issue_data"],
                    )

                if not doc_id:
                    continue

                # se houver bases-work/p/<pid>, obtém os registros de parágrafo
                ign_pid, p_records = classic_website.get_p_records(doc_id)
                p_records = list(p_records)
                if p_records:
                    # adiciona registros p aos registros do artigo
                    # info["external_p_records_count"] = len(p_records)
                    yield dict(
                        item_type="paragraph",
                        item_pid=doc_id,
                        data=p_records,
                    )
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                subevent = journal_proc.start(
                    user, "get_bases_work_acron_id_file_records item"
                )
                subevent.finish(
                    user,
                    completed=False,
                    detail=item,
                    exception=e,
                    exc_traceback=exc_traceback,
                )

        event.finish(user, completed=True)
    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if event:
            event.finish(
                user,
                completed=False,
                detail=None,
                exception=e,
                exc_traceback=exc_traceback,
            )


def id_file_has_changes(user, collection, id_path, force_update):
    return MigratedFile.has_changes(user, collection, id_path, force_update)
