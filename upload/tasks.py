from tempfile import NamedTemporaryFile
from lxml import etree

from celery.result import AsyncResult
from django.utils.translation import gettext as _

from packtools.sps.utils import file_utils as sps_file_utils
from packtools.sps.libs.async_download import download_files as sps_libs_download_files
from packtools.sps import sps_maker

from packtools.sps.models import package as sps_package
from packtools.sps.models import article_assets as sps_article_assets
from packtools.sps import exceptions as sps_exceptions
from packtools.sps.validation import (
    article as sps_validation_article,
    journal as sps_validation_journal,
)

from article.controller import create_article_from_etree, update_article
from article.choices import AS_CHANGE_SUBMITTED
from article.models import Article
from config import celery_app
from issue.models import Issue
from journal.controller import get_journal_dict_for_validation
from libs.dsm.publication.documents import get_similar_documents
from libs.dsm.publication.documents import get_document

from .utils import file_utils, package_utils, xml_utils
from . import choices, controller, exceptions, models


def run_validations(filename, package_id, package_category, article_id=None, issue_id=None):
    file_path = file_utils.get_file_absolute_path(filename)

    # Obtém lista de paths de arquivos XML disponíveis no pacote
    xml_files = sps_file_utils.get_files_list_filtered(file_path, ['.xml'])

    # Valida arquivos XML do pacote
    xml_validation_success = []
    for xml_path in xml_files:
        xml_validation_success.append(
            task_validate_xml_format(file_path, xml_path, package_id)
        )
        optimised_filepath = task_optimise_package(file_path)

        task_validate_assets.apply_async(kwargs={'file_path': optimised_filepath, 'package_id': package_id}, countdown=10)
        task_validate_renditions.apply_async(kwargs={'file_path': optimised_filepath, 'package_id': package_id}, countdown=10)
    
        if issue_id is not None and package_category:
            task_validate_article_and_issue_data.apply_async(kwargs={
                'file_path': optimised_filepath,
                'package_id': package_id,
                'issue_id': issue_id,
            },
            countdown=10)

        if article_id is not None and package_category in (choices.PC_CORRECTION,  choices.PC_ERRATUM):
            task_validate_article_change(file_path, package_category, article_id)


def check_resolutions(package_id):
    task_check_resolutions.apply_async(kwargs={'package_id': package_id}, countdown=3)


def check_opinions(package_id):
    task_check_opinions.apply_async(kwargs={'package_id': package_id}, countdown=3)


def get_or_create_package(pid_v3, user_id):
    return task_get_or_create_package(pid_v3, user_id)


@celery_app.task(bind=True, name='Validate article and issue data')
def task_validate_article_and_issue_data(self, file_path, package_id, issue_id):
    task_validate_article_and_journal_issue_compatibility.apply_async(kwargs={
        'package_id': package_id,
        'file_path': file_path,
        'issue_id': issue_id,
    })
    task_validate_article_is_unpublished.apply_async(kwargs={
        'package_id': package_id,
        'file_path': file_path,
    })


@celery_app.task(name='Validate article and journal issue compatibility')
def task_validate_article_and_journal_issue_compatibility(package_id, file_path, issue_id):
    xmltree = sps_package.PackageArticle(file_path).xmltree_article
    issue = Issue.objects.get(pk=issue_id)
    journal_dict = get_journal_dict_for_validation(issue.official_journal.id)

    val = controller.add_validation_result(
        error_category=choices.VE_ARTICLE_JOURNAL_INCOMPATIBILITY_ERROR,
        package_id=package_id,
        status=choices.VS_CREATED,
    )

    try:
        sps_validation_journal.are_article_and_journal_data_compatible(
            xml_article=xmltree, 
            journal_print_issn=journal_dict['print_issn'], 
            journal_electronic_issn=journal_dict['electronic_issn'],
            journal_titles=journal_dict['titles'],
        )
        controller.update_validation_result(
            validation_result_id=val.id,
            status=choices.VS_APPROVED
        )
        return True
    except sps_exceptions.ArticleIncompatibleDataError as e:
        if isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalISSNError):
            error_message = _('XML article has incompatible journal ISSN.')
        elif isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalTitleError):
            error_message = _('XML article has incompatible journal title.')
        elif isinstance(e, sps_exceptions.ArticleHasIncompatibleJournalAcronymError):
            error_message = _('XML article has incompatible journal acronym.')
        else:
            error_message = _('XML article has incompatible journal data.')

        controller.update_validation_result(
            validation_result_id=val.id,
            status=choices.VS_DISAPPROVED,
            message=error_message,
            data={'errors': e.data},
        )
        return False


@celery_app.task(name='Validate article is unpublished')
def task_validate_article_is_unpublished(file_path, package_id):
    xmltree = sps_package.PackageArticle(file_path).xmltree_article
    article_data = package_utils.get_article_data_for_comparison(xmltree)

    val = controller.add_validation_result(
        error_category=choices.VE_ARTICLE_IS_NOT_NEW_ERROR,
        package_id=package_id,
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
        controller.update_validation_result(
            validation_result_id=val.id,
            status=choices.VS_DISAPPROVED,
            message=_('It was not possible to connect to the site database.'),
        )
        return False

    if len(similar_docs) > 1: 
        controller.update_validation_result(
            validation_result_id=val.id,
            status=choices.VS_DISAPPROVED,
            message=_('XML article refers to a existant document.'),
            data={'similar_docs': [s.aid for s in similar_docs]},
        )
        return False

    controller.update_validation_result(
        validation_result_id=val.id,
        status=choices.VS_APPROVED,
    )
    return True


@celery_app.task(name='Validate article change')
def task_validate_article_change(new_package_file_path, new_package_category, article_id):
    last_valid_pkg = controller.get_last_package(
        article_id=article_id, 
        status=choices.PS_PUBLISHED, 
        category=choices.PC_SYSTEM_GENERATED
    )
    last_valid_pkg_file_path = file_utils.get_file_absolute_path(last_valid_pkg.file.name)

    if new_package_category == choices.PC_CORRECTION:
        task_validate_article_correction.apply_async(kwargs={
            'new_package_file_path': new_package_file_path,
            'last_valid_package_file_path': last_valid_pkg_file_path,
        })
    elif new_package_category == choices.PC_ERRATUM:
        task_result_ae = task_validate_article_erratum.apply_async(kwargs={
            'file_path': new_package_file_path
        })
        task_result_cp = task_compare_packages.apply_async(kwargs={
            'package1_file_path': new_package_file_path, 
            'package2_file_path': last_valid_pkg_file_path
        })
        task_update_article_status_by_validations.apply_async(kwargs={
            'task_id_article_erratum': task_result_ae.id, 
            'task_id_compare_packages': task_result_cp.id,
            'article_id': article_id
        })


@celery_app.task(name='Update article status by validations')
def task_update_article_status_by_validations(task_id_article_erratum, task_id_compare_packages, article_id):
    ar_article_erratum = AsyncResult(task_id_article_erratum)
    ar_compare_packages = AsyncResult(task_id_compare_packages)
    
    while not ar_article_erratum.ready() or not ar_compare_packages.ready():
        ...

    if ar_article_erratum.result and ar_compare_packages.result:
        update_article(article_id, status=AS_CHANGE_SUBMITTED)
        return True

    return False


@celery_app.task(name='Validate article correction')
def task_validate_article_correction(new_package_file_path, last_valid_package_file_path):
    new_pkg_xmltree = sps_package.PackageArticle(new_package_file_path).xmltree_article
    last_valid_pkg_xmltree = sps_package.PackageArticle(last_valid_package_file_path).xmltree_article

    return sps_validation_article.are_similar_articles(new_pkg_xmltree, last_valid_pkg_xmltree)


@celery_app.task(name='Validate article erratum')
def task_validate_article_erratum(file_path):
    return sps_package.PackageWithErrata(file_path).is_valid()


@celery_app.task(name='Compare packages')
def task_compare_packages(package1_file_path, package2_file_path):
    pkg1_xmltree = sps_package.PackageWithErrata(package1_file_path).xmltree_article
    pkg2_xmltree = sps_package.PackageArticle(package2_file_path).xmltree_article

    return sps_validation_article.are_similar_articles(pkg1_xmltree, pkg2_xmltree)


@celery_app.task()
def task_validate_xml_format(file_path, package_id):
    val = controller.add_validation_result(
        error_category=choices.VE_XML_FORMAT_ERROR,
        package_id=package_id,
        status=choices.VS_CREATED,
    )

    try:
        xml_str = file_utils.get_xml_content_from_zip(file_path)
        xml_utils.get_etree_from_xml_content(xml_str)
        controller.update_validation_result(
            validation_result_id=val.id,
            status=choices.VS_APPROVED
        )
        return True

    except (file_utils.BadPackageFileError, file_utils.PackageWithoutXMLFileError):
        controller.update_validation_result(
            validation_result_id=val.id,
            error_category=choices.VE_PACKAGE_FILE_ERROR,
            status=choices.VS_DISAPPROVED,
        )

    except xml_utils.XMLFormatError as e:
        data = {
            'column': e.column,
            'row': e.start_row,
            'snippet': xml_utils.get_snippet(xml_str, e.start_row, e.end_row),
        }

        controller.update_validation_result(
            validation_result_id=val.id,
            error_category=choices.VE_XML_FORMAT_ERROR,
            message=e.message,
            data=data,
            status=choices.VS_DISAPPROVED,
        )

    return False


@celery_app.task()
def task_optimise_package(file_path):
    source = file_utils.get_file_absolute_path(file_path)
    target = file_utils.generate_filepath_with_new_extension(source, '.optz', True)
    package_utils.optimise_package(source, target)
    package_utils.unzip(target)

    return target


@celery_app.task()
def task_validate_assets(file_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_assets = package_utils.get_article_assets_from_zipped_xml(file_path)

    has_errors = False

    for asset_result in package_utils.evaluate_assets(article_assets, package_files):
        asset, is_present = asset_result

        if not is_present:
            has_errors = True
            controller.add_validation_result(
                choices.VE_ASSET_ERROR,
                package_id,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': asset.type,
                    'missing_file': asset.name,
                },
            )

            controller.add_validation_result(
                choices.VE_ASSET_ERROR,
                package_id,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but its optimised version not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': 'optimised',
                    'missing_file': file_utils.generate_filepath_with_new_extension(asset.name, '.png'),
                },
            )

            controller.add_validation_result(
                choices.VE_ASSET_ERROR,
                package_id,
                status=choices.VS_DISAPPROVED,
                message=f'{asset.name} {_("file is mentioned in the XML but its thumbnail version not present in the package.")}',
                data={
                    'id': asset.id,
                    'type': 'thumbnail',
                    'missing_file': file_utils.generate_filepath_with_new_extension(asset.name, '.thumbnail.jpg'),
                },
            )
        
    if not has_errors:
        controller.add_validation_result(
            choices.VE_ASSET_ERROR,
            package_id,
            status=choices.VS_APPROVED,
        )
        return True


@celery_app.task()
def task_validate_renditions(file_path, package_id):
    package_files = file_utils.get_file_list_from_zip(file_path)
    article_renditions = package_utils.get_article_renditions_from_zipped_xml(file_path)

    has_errors = False

    for rendition_result in package_utils.evaluate_renditions(article_renditions, package_files):
        rendition, expected_filename, is_present = rendition_result

        if not is_present:
            has_errors = True

            controller.add_validation_result(
                package_id=package_id,
                error_category=choices.VE_RENDITION_ERROR,
                status=choices.VS_DISAPPROVED,
                message=f'{rendition.language} {_("language is mentioned in the XML but its PDF file not present in the package.")}',
                data={
                    'language': rendition.language,
                    'is_main_language': rendition.is_main_language,
                    'missing_file': expected_filename,
                },
            )

    if not has_errors:
        controller.add_validation_result(
           error_category=choices.VE_RENDITION_ERROR,
            package_id=package_id,
            status=choices.VS_APPROVED,
        )
        return True


@celery_app.task(bind=True, name='Check validation error resolutions')
def task_check_resolutions(self, package_id):
    controller.update_package_check_errors(package_id)
    return controller.compute_package_validation_result_error_resolution_stats(package_id)


@celery_app.task(bind=True, name='Check validation error resolutions opinions')
def task_check_opinions(self, package_id):
    return controller.update_package_check_opinions(package_id)


@celery_app.task(name='Get or create package')
def task_get_or_create_package(pid_v3, user_id):
    if not controller.establish_site_connection():
        raise exceptions.SiteDatabaseIsUnavailableError()

    doc = get_document(aid=pid_v3)
    if doc.aid is None:
        raise exceptions.PIDv3DoesNotExistInSiteDatabase()

    try:
        article_inst = Article.objects.get(pid_v3=doc.aid)
    except Article.DoesNotExist:
        try:
            xml_content = file_utils.get_xml_content_from_uri(doc.xml)
        except sps_exceptions.SPSHTTPResourceNotFoundError:
            raise exceptions.XMLUriIsUnavailableError(uri=doc.xml)

        xml_etree = package_utils.get_etree_from_xml_content(xml_content)
        article_inst = create_article_from_etree(xml_etree, user_id)

    try:
        return models.Package.objects.get(article__pid_v3=article_inst.pid_v3).id
    except models.Package.DoesNotExist:
        # Retrieves PDF uris and names
        rend_uris_names = []
        for rend in doc.pdfs:
            rend_uris_names.append({
                'uri': rend['url'],
                'name': rend['filename'],
            })

        # Creates a zip file
        pkg_metadata = sps_maker.make_package_from_uris(
            xml_uri=doc.xml,
            renditions_uris_and_names=rend_uris_names, 
            zip_folder=file_utils.FileSystemStorage().base_location,
        )

        # TODO: trocar nomes dos assets pelos nomes canônicos

        # Creates a package record
        pkg = controller.create_package(
            article_id=article_inst.id, 
            user_id=user_id, 
            file_name=file_utils.os.path.basename(pkg_metadata['zip']),
        )

        return pkg.id
