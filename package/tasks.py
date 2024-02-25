import json

from celery.result import AsyncResult
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from packtools.sps import exceptions as sps_exceptions
from packtools.sps.models import package as sps_package
from packtools.sps.utils import file_utils as sps_file_utils
from packtools.sps.validation import article as sps_validation_article
from packtools.sps.validation import journal as sps_validation_journal
from packtools.validator import ValidationReportXML

from article.choices import AS_CHANGE_SUBMITTED
from article.controller import create_article_from_etree, update_article
from article.models import Article
from config import celery_app
from issue.models import Issue
from journal.controller import get_journal_dict_for_validation
from libs.dsm.publication.documents import get_document, get_similar_documents

from . import choices, controller, exceptions
from .utils import file_utils, package_utils, xml_utils
from upload.models import Package


User = get_user_model()


@celery_app.task(bind=True)
def task_validate(self, sps_pkg_id):

    task_validate_assets.apply_async(
        kwargs={
            "sps_pkg_id": sps_pkg_id,
        },
    )

    # Aciona validação de Renditions
    task_validate_renditions.apply_async(
        kwargs={
            "sps_pkg_id": sps_pkg_id,
        },
    )

    # Aciona validacao do conteudo do XML
    task_validate_content_xml.apply_async(
        kwargs={
            "sps_pkg_id": sps_pkg_id,
        },
    )


@celery_app.task(bind=True)
def task_validate_assets(self, sps_pkg_id):
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


@celery_app.task(bind=True)
def task_validate_renditions(self, sps_pkg_id):
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


@celery_app.task(bind=True)
def task_validate_content_xml(self, sps_pkg_id):
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
                    data=data,
                    status=status,
                )
