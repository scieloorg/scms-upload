import json
import sys
import logging

from celery.result import AsyncResult
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from packtools.sps import exceptions as sps_exceptions
from packtools.sps.models import package as sps_package
from packtools.sps.utils import file_utils as sps_file_utils
from packtools.sps.validation import article as sps_validation_article
from packtools.sps.validation import journal as sps_validation_journal
from packtools.validator import ValidationReportXML
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre

from article.choices import AS_CHANGE_SUBMITTED
from article.controller import create_article_from_etree, update_article
from article.models import Article
from config import celery_app
from issue.models import Issue
from journal.models import Journal
from journal.controller import get_journal_dict_for_validation
from libs.dsm.publication.documents import get_document, get_similar_documents

from tracker.models import UnexpectedEvent
from . import choices, controller, exceptions
from .utils import file_utils, package_utils, xml_utils
from upload.models import Package


User = get_user_model()


# TODO REMOVE
def run_validations(
    filename, package_id, package_category, article_id=None, issue_id=None
):
    file_path = file_utils.get_file_absolute_path(filename)

    # Obtém lista de paths de arquivos XML disponíveis no pacote
    xml_files = sps_file_utils.get_files_list_filtered(file_path, [".xml"])

    # Valida arquivos XML do pacote
    xml_validation_success = []
    for xml_path in xml_files:
        xml_validation_success.append(
            task_validate_xml_format(file_path, xml_path, package_id)
        )

    # Caso nenhum arquivo XML seja inválido, aciona outras validações
    if False not in xml_validation_success:
        # Gera versão otimizada do pacote
        optimised_filepath = task_optimise_package(file_path)

        # Para cada XML no pacote
        for xml_path in xml_files:
            # Aciona validação de Assets
            task_validate_assets.apply_async(
                kwargs={
                    "file_path": optimised_filepath,
                    "xml_path": xml_path,
                    "package_id": package_id,
                },
                countdown=10,
            )

            # Aciona validação de Renditions
            task_validate_renditions.apply_async(
                kwargs={
                    "file_path": optimised_filepath,
                    "xml_path": xml_path,
                    "package_id": package_id,
                },
                countdown=10,
            )

            # Aciona validacao do conteudo do XML
            task_validate_content_xml.apply_async(
                kwargs={
                    "file_path": file_path,
                    "xml_path": xml_path,
                    "package_id": package_id,
                },
                countdown=10,
            )

        # Aciona validação de compatibilidade entre dados do pacote e o Issue selecionado
        if issue_id is not None and package_category:
            task_validate_article_and_issue_data.apply_async(
                kwargs={
                    "file_path": optimised_filepath,
                    "package_id": package_id,
                    "issue_id": issue_id,
                },
                countdown=10,
            )

        # Aciona validação de compatibilidade entre dados do pacote e o Article selecionado
        if article_id is not None and package_category in (
            choices.PC_UPDATE,
            choices.PC_ERRATUM,
        ):
            task_validate_article_change(
                file_path,
                package_category,
                article_id,
            )


def get_or_create_package(pid_v3, user_id):
    return task_get_or_create_package(pid_v3, user_id)


@celery_app.task(bind=True, name="Validate article and issue data")
def task_validate_article_and_issue_data(self, file_path, package_id, issue_id):
    task_validate_article_and_journal_issue_compatibility.apply_async(
        kwargs={
            "package_id": package_id,
            "file_path": file_path,
            "issue_id": issue_id,
        }
    )
    task_validate_article_is_unpublished.apply_async(
        kwargs={
            "package_id": package_id,
            "file_path": file_path,
        }
    )


@celery_app.task(name="Validate article and journal issue compatibility")
def task_validate_article_and_journal_issue_compatibility(
    package_id, file_path, issue_id
):
    xmltree = sps_package.PackageArticle(file_path).xmltree_article
    issue = Issue.objects.get(pk=issue_id)
    journal_dict = get_journal_dict_for_validation(issue.official_journal.id)

    val = Package.add_validation_result(
        package_id=package_id,
        error_category=choices.VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR,
        status=choices.VS_CREATED,
    )

    try:
        sps_validation_journal.are_article_and_journal_data_compatible(
            xml_article=xmltree,
            journal_print_issn=journal_dict["print_issn"],
            journal_electronic_issn=journal_dict["electronic_issn"],
            journal_titles=journal_dict["titles"],
        )
        val.update(status=choices.VS_APPROVED)

        return True
    except sps_exceptions.ArticleIncompatibleDataError as e:
        if isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalISSNError):
            error_message = _("XML article has incompatible journal ISSN.")
        elif isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalTitleError):
            error_message = _("XML article has incompatible journal title.")
        elif isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalAcronymError):
            error_message = _("XML article has incompatible journal acronym.")
        else:
            error_message = _("XML article has incompatible journal data.")

        val.update(
            status=choices.VS_DISAPPROVED,
            message=error_message,
            data={"errors": e.data},
        )
        return False


@celery_app.task(name="Validate article is unpublished")
def task_validate_article_is_unpublished(file_path, package_id):
    xmltree = sps_package.PackageArticle(file_path).xmltree_article
    article_data = package_utils.get_article_data_for_comparison(xmltree)

    val = Package.add_validation_result(
        package_id=package_id,
        error_category=choices.VE_ARTICLE_IS_NOT_NEW_ERROR,
        status=choices.VS_CREATED,
    )

    try:
        controller.establish_site_connection()
        similar_docs = get_similar_documents(
            article_title=article_data["title"],
            journal_electronic_issn=article_data["journal_electronic_issn"],
            journal_print_issn=article_data["journal_print_issn"],
            authors=article_data["authors"],
        )
    except Exception:
        val.update(
            status=choices.VS_DISAPPROVED,
            message=_("It was not possible to connect to the site database."),
        )
        return False

    if len(similar_docs) > 1:
        val.update(
            status=choices.VS_DISAPPROVED,
            message=_("XML article refers to a existant document."),
            data={"similar_docs": [s.aid for s in similar_docs]},
        )
        return False

    val.update(
        status=choices.VS_APPROVED,
    )
    return True


@celery_app.task(name="Validate article change")
def task_validate_article_change(
    new_package_file_path, new_package_category, article_id
):
    last_valid_pkg = controller.get_last_package(
        article_id=article_id,
        status=choices.PS_PUBLISHED,
        category=choices.PC_SYSTEM_GENERATED,
    )
    last_valid_pkg_file_path = file_utils.get_file_absolute_path(
        last_valid_pkg.file.name
    )

    if new_package_category == choices.PC_UPDATE:
        task_validate_article_update.apply_async(
            kwargs={
                "new_package_file_path": new_package_file_path,
                "last_valid_package_file_path": last_valid_pkg_file_path,
            }
        )
    elif new_package_category == choices.PC_ERRATUM:
        task_result_ae = task_validate_article_erratum.apply_async(
            kwargs={"file_path": new_package_file_path}
        )
        task_result_cp = task_compare_packages.apply_async(
            kwargs={
                "package1_file_path": new_package_file_path,
                "package2_file_path": last_valid_pkg_file_path,
            }
        )
        task_update_article_status_by_validations.apply_async(
            kwargs={
                "task_id_article_erratum": task_result_ae.id,
                "task_id_compare_packages": task_result_cp.id,
                "article_id": article_id,
            }
        )


@celery_app.task(name="Update article status by validations")
def task_update_article_status_by_validations(
    task_id_article_erratum, task_id_compare_packages, article_id
):
    ar_article_erratum = AsyncResult(task_id_article_erratum)
    ar_compare_packages = AsyncResult(task_id_compare_packages)

    while not ar_article_erratum.ready() or not ar_compare_packages.ready():
        ...

    if ar_article_erratum.result and ar_compare_packages.result:
        update_article(article_id, status=AS_CHANGE_SUBMITTED)
        return True

    return False


@celery_app.task(name="Validate article update")
def task_validate_article_update(new_package_file_path, last_valid_package_file_path):
    new_pkg_xmltree = sps_package.PackageArticle(new_package_file_path).xmltree_article
    last_valid_pkg_xmltree = sps_package.PackageArticle(
        last_valid_package_file_path
    ).xmltree_article

    return sps_validation_article.are_similar_articles(
        new_pkg_xmltree, last_valid_pkg_xmltree
    )


@celery_app.task(name="Validate article erratum")
def task_validate_article_erratum(file_path):
    return sps_package.PackageWithErrata(file_path).is_valid()


@celery_app.task(name="Compare packages")
def task_compare_packages(package1_file_path, package2_file_path):
    pkg1_xmltree = sps_package.PackageWithErrata(package1_file_path).xmltree_article
    pkg2_xmltree = sps_package.PackageArticle(package2_file_path).xmltree_article

    return sps_validation_article.are_similar_articles(pkg1_xmltree, pkg2_xmltree)


@celery_app.task()
def task_validate_xml_format(file_path, xml_path, package_id):
    val = Package.add_validation_result(
        package_id=package_id,
        error_category=choices.VE_XML_FORMAT_ERROR,
        status=choices.VS_CREATED,
        data={"xml_path": xml_path},
    )

    try:
        xml_str = file_utils.get_xml_content_from_zip(file_path, xml_path)
        xml_utils.get_etree_from_xml_content(xml_str)
        val.update(status=choices.VS_APPROVED)
        return True

    except (file_utils.BadPackageFileError, file_utils.PackageWithoutXMLFileError):
        val.update(
            error_category=choices.VE_PACKAGE_FILE_ERROR,
            status=choices.VS_DISAPPROVED,
        )

    except xml_utils.XMLFormatError as e:
        data = {
            "xml_path": xml_path,
            "column": e.column,
            "row": e.start_row,
            "snippet": xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }
        val.update(
            error_category=choices.VE_XML_FORMAT_ERROR,
            message=e.message,
            data=data,
            status=choices.VS_DISAPPROVED,
        )

    return False


@celery_app.task()
def task_optimise_package(file_path):
    source = file_utils.get_file_absolute_path(file_path)
    target = file_utils.generate_filepath_with_new_extension(source, ".optz", True)
    package_utils.optimise_package(source, target)
    package_utils.unzip(target)

    return target


@celery_app.task()
def task_validate_assets(file_path, xml_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_assets = package_utils.get_article_assets_from_zipped_xml(
        file_path, xml_path
    )

    has_errors = False

    for asset_result in package_utils.evaluate_assets(article_assets, package_files):
        asset, is_present = asset_result

        if not is_present:
            has_errors = True
            Package.add_validation_result(
                package_id,
                error_category=choices.VE_ASSET_ERROR,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but not present in the package.")}',
                data={
                    "xml_path": xml_path,
                    "id": asset.id,
                    "type": asset.type,
                    "missing_file": asset.name,
                },
            )

            Package.add_validation_result(
                package_id,
                error_category=choices.VE_ASSET_ERROR,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but its optimised version not present in the package.")}',
                data={
                    "xml_path": xml_path,
                    "id": asset.id,
                    "type": "optimised",
                    "missing_file": file_utils.generate_filepath_with_new_extension(
                        asset.name, ".png"
                    ),
                },
            )

            Package.add_validation_result(
                package_id,
                error_category=choices.VE_ASSET_ERROR,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but its thumbnail version not present in the package.")}',
                data={
                    "xml_path": xml_path,
                    "id": asset.id,
                    "type": "thumbnail",
                    "missing_file": file_utils.generate_filepath_with_new_extension(
                        asset.name, ".thumbnail.jpg"
                    ),
                },
            )

    if not has_errors:
        Package.add_validation_result(
            package_id,
            error_category=choices.VE_ASSET_ERROR,
            status=choices.VS_APPROVED,
            data={"xml_path": xml_path},
        )
        return True


@celery_app.task()
def task_validate_renditions(file_path, xml_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_renditions = package_utils.get_article_renditions_from_zipped_xml(
        file_path, xml_path
    )

    has_errors = False

    for rendition_result in package_utils.evaluate_renditions(
        article_renditions, package_files
    ):
        rendition, expected_filename, is_present = rendition_result

        if not is_present:
            has_errors = True

            Package.add_validation_result(
                package_id=package_id,
                error_category=choices.VE_RENDITION_ERROR,
                status=choices.VS_DISAPPROVED,
                message=f'{rendition.language} {_("language is mentioned in the XML but its PDF file not present in the package.")}',
                data={
                    "xml_path": xml_path,
                    "language": rendition.language,
                    "is_main_language": rendition.is_main_language,
                    "missing_file": expected_filename,
                },
            )

    if not has_errors:
        Package.add_validation_result(
            package_id=package_id,
            error_category=choices.VE_RENDITION_ERROR,
            status=choices.VS_APPROVED,
            data={"xml_path": xml_path},
        )
        return True


# TODO REMOVE
@celery_app.task(name="Validate XML")
def task_validate_content_xml(file_path, xml_path, package_id):
    xml_str = file_utils.get_xml_content_from_zip(file_path)

    validations = ValidationReportXML(
        file_path=xml_str, data_file_path="validation_criteria_example.json"
    ).validation_report()

    # data = {}
    for result in validations:
        for key, value in result.items():
            for result_ind in value:
                string_validations = json.dumps(result_ind, default=str)
                json_validations = json.loads(string_validations)

                vr = Package.add_validation_result(
                    package_id=package_id,
                    error_category=choices.VE_DATA_CONSISTENCY_ERROR,
                    status=choices.VS_CREATED,
                    data=json_validations,
                )

                # # TODO
                # Realizar logica para verificar se a validacao passou ou nao
                ########
                try:
                    message = json_validations["message"]
                except Exception as e:
                    print(f"Error: {e}")
                    message = ""

                try:
                    valor = json_validations["result"]
                except Exception as e:
                    print(f"Error: {e}")
                    valor = False

                if valor == "success":
                    status = choices.VS_APPROVED
                else:
                    status = choices.VS_DISAPPROVED

                vr.update(
                    error_category=choices.VE_XML_FORMAT_ERROR,
                    message=_(message),
                    data=json_validations,
                    status=status,
                )


@celery_app.task(name="Get or create package")
def task_get_or_create_package(pid_v3, user_id):
    # Estabelece conexão com base de dados de artigos do site
    if not controller.establish_site_connection():
        raise exceptions.SiteDatabaseIsUnavailableError()

    # Obtém dados de artigo do site
    doc = get_document(aid=pid_v3)
    if doc.aid is None:
        raise exceptions.PIDv3DoesNotExistInSiteDatabase()

    try:
        # Obtém dados de artigo no sistema de upload a partir de PIDv3
        article_inst = Article.objects.get(pid_v3=doc.aid)
    except Article.DoesNotExist:
        # Cria artigo no sistema de upload com base no que existe no site
        try:
            xml_content = file_utils.get_xml_content_from_uri(doc.xml)
        except sps_exceptions.SPSHTTPResourceNotFoundError:
            raise exceptions.XMLUriIsUnavailableError(uri=doc.xml)

        xml_etree = package_utils.get_etree_from_xml_content(xml_content)
        article_inst = create_article_from_etree(xml_etree, user_id)
    try:
        # Obtém pacote relacionado ao PIDv3, caso exista
        return Package.objects.get(article__pid_v3=article_inst.pid_v3).id
    except Package.DoesNotExist:
        # Cria pacote novo, caso nenhum exista para o PIDv3 informado
        package_file_name = package_utils.create_package_file_from_site_doc(doc)

        # Cria registro de pacote em base de dados do sistema de upload e retorna seu id
        return controller.create_package(
            article_id=article_inst.id,
            user_id=user_id,
            file_name=package_file_name,
        ).id


def _get_user(request, user_id):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        return User.objects.get(pk=user_id)


@celery_app.task(bind=True, name="request_pid_for_accepted_packages")
def task_request_pid_for_accepted_packages(self, user_id):
    user = _get_user(self.request, user_id)
    controller.request_pid_for_accepted_packages(user)


@celery_app.task(bind=True)
def task_validate_original_zip_file(
    self, package_id, file_path, journal_id, issue_id, article_id
):

    for xml_with_pre in XMLWithPre.create(path=file_path):
        xml_path = xml_with_pre.filename

        # FIXME nao usar o otimizado neste momento
        optimised_filepath = task_optimise_package(file_path)

        # Aciona validação de Assets
        task_validate_assets.apply_async(
            kwargs={
                "file_path": optimised_filepath,
                "xml_path": xml_path,
                "package_id": package_id,
            },
        )

        # Aciona validação de Renditions
        task_validate_renditions.apply_async(
            kwargs={
                "file_path": optimised_filepath,
                "xml_path": xml_path,
                "package_id": package_id,
            },
        )

        # Aciona validacao do conteudo do XML
        task_validate_xml_content.apply_async(
            kwargs={
                "file_path": file_path,
                "xml_path": xml_path,
                "package_id": package_id,
                "journal_id": journal_id,
                "issue_id": issue_id,
                "article_id": article_id,
            },
        )


@celery_app.task(bind=True)
def task_validate_xml_content(
    self, file_path, xml_path, package_id, journal_id, issue_id, article_id
):
    try:
        package = Package.objects.get(pk=package_id)
        if journal_id:
            journal = Journal.objects.get(pk=journal_id)
        else:
            journal = None

        if issue_id:
            issue = Issue.objects.get(pk=issue_id)
        else:
            issue = None

        controller.validate_xml_content(package, journal, issue)

    except Exception as e:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        UnexpectedEvent.create(
            exception=e,
            exc_traceback=exc_traceback,
            detail={
                "operation": "upload.tasks.task_validate_xml_content",
                "detail": dict(file_path=file_path, xml_path=xml_path),
            },
        )
