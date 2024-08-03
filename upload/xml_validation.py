import csv
import json
import logging
import os
import sys

from importlib_resources import files
from packtools.sps.models.dates import ArticleDates
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.sps.validation.aff import (
    AffiliationsListValidation,
    AffiliationValidation,
)
from packtools.sps.validation.alternatives import (
    AlternativesValidation,
    AlternativeValidation,
)
from packtools.sps.validation.article_abstract import (
    HighlightsValidation,
    VisualAbstractsValidation,
)
from packtools.sps.validation.article_and_subarticles import (
    ArticleAttribsValidation,
    ArticleIdValidation,
    ArticleLangValidation,
    ArticleTypeValidation,
)
from packtools.sps.validation.article_author_notes import AuthorNotesValidation
from packtools.sps.validation.article_citations import (
    ArticleCitationsValidation,
    ArticleCitationValidation,
)
from packtools.sps.validation.article_contribs import (
    ArticleContribsValidation,
    ContribsValidation,
    ContribValidation,
)
from packtools.sps.validation.article_data_availability import (
    DataAvailabilityValidation,
)
from packtools.sps.validation.article_doi import ArticleDoiValidation
from packtools.sps.validation.article_lang import (
    ArticleLangValidation as ArticleLangValidation2,
)
from packtools.sps.validation.article_license import ArticleLicenseValidation
from packtools.sps.validation.article_toc_sections import ArticleTocSectionsValidation
from packtools.sps.validation.article_xref import ArticleXrefValidation
from packtools.sps.validation.dates import ArticleDatesValidation
from packtools.sps.validation.fig import FigValidation
from packtools.sps.validation.footnotes import FootnoteValidation
from packtools.sps.validation.formula import FormulaValidation
from packtools.sps.validation.front_articlemeta_issue import IssueValidation, Pagination
from packtools.sps.validation.funding_group import FundingGroupValidation
from packtools.sps.validation.journal_meta import (
    AcronymValidation,
    ISSNValidation,
    JournalIdValidation,
    JournalMetaValidation,
    PublisherNameValidation,
    TitleValidation,
)
from packtools.sps.validation.peer_review import (
    AuthorPeerReviewValidation,
    CustomMetaPeerReviewValidation,
    DatePeerReviewValidation,
    PeerReviewsValidation,
    RelatedArticleValidation,
)
from packtools.sps.validation.preprint import PreprintValidation
from packtools.sps.validation.related_articles import RelatedArticlesValidation
from packtools.sps.validation.supplementary_material import (
    SupplementaryMaterialValidation,
)
from packtools.sps.validation.tablewrap import TableWrapValidation
from packtools.sps.validation.utils import get_doi_information


def get_data(filename, key, sps_version=None):
    sps_version = sps_version or "default"
    # Reads contents with UTF-8 encoding and returns str.
    content = (
        files(f"packtools.sps.sps_versions")
        .joinpath(f"{sps_version}")
        .joinpath(f"{filename}.json")
        .read_text()
    )
    x = " ".join(content.split())
    fixed = x.replace(", ]", "]").replace(", }", "}")
    data = json.loads(fixed)
    return data[key]


def create_report(report_file_path, xml_path, params, fieldnames=None):
    if not params:
        params = {
            # "get_doi_data": callable_get_doi_data,
            "doi_required": params.get("doi_required"),
            "expected_toc_sections": params.get("expected_toc_sections"),
            "journal_acron": params.get("journal_acron"),
            "publisher_name_list": params.get("publisher_name_list"),
            "nlm_ta": params.get("nlm_ta"),
        }
    for xml_with_pre in XMLWithPre.create(path=xml_path):
        rows = validate_xml_content(xml_with_pre.filename, xml_with_pre.xmltree, params)
        save_csv(report_file_path, rows, fieldnames)
        print(f"Created {report_file_path}")


def save_csv(filepath, rows, fieldnames=None):

    with open(filepath, "w", newline="") as csvfile:
        header = False
        for row in rows:
            try:
                logging.exception(row["exception"])
                continue
            except KeyError:
                if not fieldnames:
                    fieldnames = list(row.keys())
                if not header:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    header = True
            writer.writerow(row)


def validate_xml_content(sps_pkg_name, xmltree, params):
    logging.info("")
    # params = {
    #     "get_doi_data": callable_get_doi_data,
    #     "doi_required": params.get("doi_required"),
    #     "expected_toc_sections": params.get("expected_toc_sections"),
    #     "journal_acron": params.get("journal_acron"),
    #     "publisher_name_list": params.get("publisher_name_list"),
    #     "nlm_ta": params.get("nlm_ta"),
    # }

    validation_group_and_function_items = (
        ("journal", validate_journal),
        ("article attributes", validate_article_attributes),
        ("article attributes", validate_languages),
        ("article attributes", validate_article_type),
        ("article-id", validate_article_id_other),
        # ("article-id", validate_doi),
        # ("dates", validate_dates),
        ("author", validate_contribs),
        ("author affiliations", validate_affiliations),
        ("author notes", validate_author_notes),
        ("text languages", validate_toc_sections),
        ("text languages", validate_article_languages),
        ("text xref", validate_xref),
        ("open science", validate_data_availability),
        ("open science", validate_licenses),
        ("open science", validate_preprint),
        # ("open science peer review", validate_peer_review),
        ("references", validate_references),
        ("funding", validate_funding_group),
        ("related articles", validate_related_articles),
        ("special abstracts", validate_visual_abstracts),
        ("special abstracts", validate_highlights),
        ("footnotes", validate_footnotes),
        # ("table-wrap", validate_table_wrap),
        # ("figures", validate_figures),
        # ("formulas", validate_formulas),
        ("supplementary material", validate_supplementary_material),
    )

    sps_version = xmltree.find(".").get("specific-use")
    for validation_group, f in validation_group_and_function_items:
        try:
            items = f(xmltree, sps_version, params)
            for item in items:
                try:
                    item["group"] = validation_group
                    yield item
                except Exception as exc:
                    print(f"item: {item} / group: {validation_group}")
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    yield dict(
                        exception=exc,
                        exc_traceback=exc_traceback,
                        function=validation_group,
                        sps_pkg_name=sps_pkg_name,
                        item=item,
                    )
        except Exception as exc:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            yield dict(
                exception=exc,
                exc_traceback=exc_traceback,
                function=validation_group,
                sps_pkg_name=sps_pkg_name,
            )


def validate_affiliations(xmltree, sps_version, params):
    logging.info("validate_affiliations")
    validator = AffiliationsListValidation(xmltree)
    data = get_data("country_codes", "country_codes_list")
    yield from validator.validade_affiliations_list(data)


def validate_highlights(xmltree, sps_version, params):
    logging.info("validate_highlights")
    validator = HighlightsValidation(xmltree)
    yield from validator.highlight_validation()


def validate_visual_abstracts(xmltree, sps_version, params):
    logging.info("validate_visual_abstracts")
    validator = VisualAbstractsValidation(xmltree)
    yield from validator.visual_abstracts_validation()


def validate_languages(xmltree, sps_version, params):
    logging.info("validate_languages")
    validator = ArticleLangValidation(xmltree)
    yield from validator.validate_language(
        get_data("language_codes", "language_codes_list")
    )


def validate_article_attributes(xmltree, sps_version, params):
    logging.info("validate_article_attributes")
    validator = ArticleAttribsValidation(xmltree)
    yield from validator.validate_dtd_version(
        get_data("dtd_version", "dtd_version_list", sps_version)
    )
    yield from validator.validate_specific_use(
        get_data("specific_use", "specif_use_list")
    )


def validate_article_id_other(xmltree, sps_version, params):
    logging.info("validate_article_id_other")
    validator = ArticleIdValidation(xmltree)
    try:
        return validator.validate_article_id_other()
    except AttributeError:
        return None


def validate_article_type(xmltree, sps_version, params):
    logging.info("validate_article_type")
    validator = ArticleTypeValidation(xmltree)
    # FIXME validar article_type para sub-article
    try:
        yield from validator.validate_article_type(
            get_data("article_type", "article_type_list", sps_version)
        )
    except Exception as e:
        raise e

    # TODO
    # yield from validator.validate_article_type_vs_subject_similarity(
    #     subjects_list=None, expected_similarity=1, error_level=None, target_article_types=None
    # )


def validate_author_notes(xmltree, sps_version, params):
    logging.info("validate_author_notes")
    data = {"sps-1.9": ["conflict"], "sps-1.10": ["coi-statement"]}
    validator = AuthorNotesValidation(xmltree, data.get(sps_version))
    yield from validator.validate_author_note()


def validate_references(xmltree, sps_version, params):
    logging.info("validate_references")
    # FIXME criar json para a versão sps-1.9
    publication_type_list = get_data(
        "publication_types_references", "publication_type_list", sps_version
    )
    validator = ArticleCitationsValidation(xmltree, publication_type_list)
    start_year = None

    xml = ArticleDates(xmltree)
    end_year = int(xml.collection_date["year"] or xml.article_date["year"])

    # FIXME remover xmltree do método
    yield from validator.validate_article_citations(
        xmltree, publication_type_list, start_year, end_year
    )


def validate_contribs(xmltree, sps_version, params):
    logging.info("validate_contribs")
    data = {
        "credit_taxonomy_terms_and_urls": None,
        "callable_get_data": None,
    }
    validator = ArticleContribsValidation(xmltree, data)
    # FIXME
    yield from validator.validate_contribs_orcid_is_unique(error_level="CRITICAL")
    # for contrib in validator.contribs.contribs:
    #     yield from ContribsValidation(contrib, data, content_types).validate()


def validate_data_availability(xmltree, sps_version, params):
    logging.info("validate_data_availability")
    validator = DataAvailabilityValidation(xmltree)
    try:
        specific_use_list = get_data(
            "data_availability_specific_use", "specific_use", sps_version
        )
    except Exception as e:
        specific_use_list = None

    if specific_use_list:
        yield from validator.validate_data_availability(
            specific_use_list,
            error_level="ERROR",
        )


def validate_doi(xmltree, sps_version, params):
    logging.info("validate_doi")
    # FIXME falta de padrão
    validator = ArticleDoiValidation(xmltree)

    if params.get("doi_required"):
        error_level = "CRITICAL"
    else:
        error_level = "ERROR"
    yield from validator.validate_doi_exists(error_level=error_level)
    yield from validator.validate_all_dois_are_unique(error_level="ERROR")
    yield from validator.validate_doi_registered(get_doi_information)


def validate_article_languages(xmltree, sps_version, params):
    logging.info("validate_article_languages")
    # FIXME falta de padrão
    validator = ArticleLangValidation2(xmltree)
    yield from validator.validate_article_lang()


def validate_licenses(xmltree, sps_version, params):
    logging.info("validate_licenses")
    validator = ArticleLicenseValidation(xmltree)
    # yield from validator.validate_license(license_expected_value)
    # falta de json em sps-1.9
    yield from validator.validate_license_code(params.get("journal_license_code"))


def validate_toc_sections(xmltree, sps_version, params):
    logging.info("validate_toc_sections")
    validator = ArticleTocSectionsValidation(xmltree)
    yield from validator.validate_article_toc_sections(
        params.get("expected_toc_sections")
    )
    yield from validator.validade_article_title_is_different_from_section_titles()


def validate_xref(xmltree, sps_version, params):
    logging.info("validate_xref")
    validator = ArticleXrefValidation(xmltree)
    yield from validator.validate_id()
    yield from validator.validate_rid()


def validate_dates(xmltree, sps_version, params):
    logging.info("validate_dates")
    validator = ArticleDatesValidation(xmltree)
    order = get_data(
        "history_dates_order_of_events",
        "order",
        sps_version,
    )
    required_events = get_data(
        "history_dates_required_events",
        "required_events",
        sps_version,
    )
    yield from validator.validate_history_dates(order, required_events)
    yield from validator.validate_number_of_digits_in_article_date()

    # FIXME
    yield from validator.validate_article_date(future_date=None)
    yield from validator.validate_collection_date(future_date=None)


def validate_figures(xmltree, sps_version, params):
    logging.info("validate_figures")
    # FIXME faltam validações de label, caption, graphic ou alternatives
    validator = FigValidation(xmltree)
    yield from validator.validate_fig_existence()


def validate_footnotes(xmltree, sps_version, params):
    logging.info("validate_footnotes")
    # FIXME não existe somente um tipo de footnotes, faltam validações, error_level
    validator = FootnoteValidation(xmltree)
    yield from validator.fn_validation()


def validate_formulas(xmltree, sps_version, params):
    logging.info("validate_formulas")
    # FIXME faltam validações de label, caption, graphic ou alternatives
    validator = FormulaValidation(xmltree)
    yield from validator.validate_formula_existence()


def validate_funding_group(xmltree, sps_version, params):
    logging.info("validate_funding_group")
    # FIXME ? _callable_extern_validate_default
    # faltam validações
    validator = FundingGroupValidation(xmltree)
    yield from validator.funding_sources_exist_validation()
    # ??? yield from validator.award_id_format_validation(_callable_extern_validate_default)


def validate_journal(xmltree, sps_version, params):
    logging.info("validate_journal")

    validator = AcronymValidation(xmltree)
    yield from validator.acronym_validation(params["journal_acron"])

    validator = PublisherNameValidation(xmltree)
    yield from validator.validate_publisher_names(params["publisher_name_list"])

    try:
        if params["nlm_ta"]:
            validator = JournalIdValidation(xmltree)
            yield from validator.nlm_ta_id_validation(params["nlm_ta"])
    except KeyError:
        pass


def validate_peer_review(xmltree, sps_version, params):
    logging.info("validate_peer_review")
    # FIXME temos todos os json?

    validator = PeerReviewsValidation(
        xmltree,
        contrib_type_list=get_data(
            "specific_use_for_peer_reviews", "contrib_type_list", sps_version
        ),
        specific_use_list=get_data(
            "specific_use_for_peer_reviews", "specific_use_list", sps_version
        ),
        date_type_list=get_data(
            "specific_use_for_peer_reviews", "date_type_list", sps_version
        ),
        meta_value_list=get_data("meta_value", "meta_value_list", sps_version),
        related_article_type_list=get_data(
            "related_article_type", "related_article_type_list", sps_version
        ),
        link_type_list=get_data(
            "related_article__ext_link_type",
            "related_article__ext_link_type_list",
            sps_version,
        ),
    )
    yield from validator.validate()


def validate_preprint(xmltree, sps_version, params):
    logging.info("validate_preprint")
    # FIXME fora de padrão
    validator = PreprintValidation(xmltree)
    yield from validator.preprint_validation()


def validate_related_articles(xmltree, sps_version, params):
    logging.info("validate_related_articles")
    validator = RelatedArticlesValidation(xmltree)
    correspondence_list = get_data(
        "related_article",
        "correspondence_list",
        sps_version,
    )
    yield from validator.related_articles_matches_article_type_validation(
        correspondence_list
    )
    yield from validator.related_articles_doi()


def validate_supplementary_material(xmltree, sps_version, params):
    logging.info("validate_supplementary_material")
    # FIXME validações incompletas
    validator = SupplementaryMaterialValidation(xmltree)
    yield from validator.validate_supplementary_material_existence()


def validate_table_wrap(xmltree, sps_version, params):
    logging.info("validate_table_wrap")
    # FIXME validações incompletas
    validator = TableWrapValidation(xmltree)
    yield from validator.validate_tablewrap_existence()
