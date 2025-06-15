import logging

from packtools.sps.models.article_abstract import Abstract
from packtools.sps.models.article_and_subarticles import ArticleAndSubArticles
from packtools.sps.models.article_contribs import ArticleContribs
from packtools.sps.models.article_doi_with_lang import DoiWithLang
from packtools.sps.models.article_ids import ArticleIds
from packtools.sps.models.article_renditions import ArticleRenditions
from packtools.sps.models.article_titles import ArticleTitles
from packtools.sps.models.article_toc_sections import ArticleTocSections
from packtools.sps.models.front_articlemeta_issue import ArticleMetaIssue
from packtools.sps.models.kwd_group import KwdGroup
from packtools.sps.models.related_articles import RelatedItems

from publication.utils.issue import get_bundle_id


def build_article(builder, article, journal_id, order, pub_date, is_public=True):
    sps_pkg = article.sps_pkg
    xml_with_pre = sps_pkg.xml_with_pre

    article_xml = XMLArticle(xml_with_pre)

    # TODO other_pids
    builder.add_identifiers(
        v3=xml_with_pre.v3,
        v2=xml_with_pre.v2,
        aop_pid=xml_with_pre.aop_pid,
        other_pids=None,
    )

    builder.add_dates(article.created, article.updated)
    builder.add_issue(
        get_bundle_id(
            issn_id=journal_id,
            year=article.issue.publication_year,
            volume=article.issue.volume,
            number=article.issue.number,
            supplement=article.issue.supplement,
        )
    )

    builder.add_xml(xml=sps_pkg.xml_uri)

    metadata = article_xml.get_main_metadata()
    for item in sps_pkg.htmls:
        builder.add_html(language=item["lang"], uri=item.get("url"))
    for item in sps_pkg.pdfs:
        # {"lang": item.lang, "url": item.uri, "legacy_uri": item.legacy_uri}
        lang = item.get("lang") or metadata.get("lang")
        builder.add_pdf(
            lang=lang,
            url=item["url"],
            filename=item["basename"],
            type=item.get("component_type"),
            classic_uri=item.get("legacy_uri"),
        )
    for item in sps_pkg.supplementary_materials:
        builder.add_mat_suppl(
            **{
                "ref_id": item["xml_elem_id"],
                "lang": item["lang"],
                "url": item["url"],
                "filename": item["basename"],
                "classic_uri": item["legacy_uri"],
            }
        )

    builder.add_main_metadata(**metadata)
    builder.add_document_type(article_xml.main_article_type)

    builder.add_in_issue(**article_xml.get_in_issue(order))

    builder.add_publication_date(**article_xml.get_publication_date(pub_date))

    contribs = article_xml.get_contribs()
    for item in contribs.get("names") or []:
        builder.add_author(**item)

    for item in contribs.get("collabs") or []:
        builder.add_collab(**item)

    for item in article_xml.get_translated_title():
        builder.add_translated_title(**item)

    for language, text in article.multilingual_sections.items():
        # pega as seções a partir do Article
        builder.add_section(language=language, text=text, code=None)

    for item in article_xml.get_keywords():
        builder.add_keywords(**item)

    for item in article_xml.get_doi_with_lang():
        builder.add_doi_with_lang(**item)

    for item in article_xml.get_related_articles():
        builder.add_related_article(**item)

    builder.add_status(is_public)

    for item in article_xml.get_abstracts():
        builder.add_abstract(**item)


class XMLArticle:
    def __init__(self, xml_with_pre):
        self.xmltree = xml_with_pre.xmltree

    def get_publication_date(self, pub_date):
        return {
            "year": str(pub_date.year),
            "month": str(pub_date.month).zfill(2),
            "day": str(pub_date.day).zfill(2),
        }

    def get_contribs(self):
        authors = ArticleContribs(self.xmltree)

        names = []
        collabs = []
        for item in authors.contribs:
            if item.get("parent") != "article":
                break

            if contrib := item.get("contrib_name"):
                try:
                    affs = item.get("affs") or []
                    affiliation = ", ".join(
                        [a.get("original") or a.get("orgname") for a in affs]
                    )
                except KeyError:
                    affiliation = None
                contrib_ids = item.get("contrib_ids") or {}
                names.append(
                    dict(
                        surname=contrib.get("surname"),
                        given_names=contrib.get("given-names"),
                        suffix=contrib.get("suffix"),
                        affiliation=affiliation,
                        orcid=contrib_ids.get("orcid"),
                    )
                )
            if collab := item.get("collab"):
                collabs.append({"name": collab})
        return {"names": names, "collabs": collabs}

    def get_related_articles(self):
        items = RelatedItems(self.xmltree)
        for item in items.related_articles:
            yield {
                "ext_link_type": item.get("ext-link-type"),
                "ref_id": item.get("id"),
                "href": item.get("href"),
                "related_type": item.get("related-article-type"),
            }

    def get_translated_title(self):
        xml_article_titles = ArticleTitles(self.xmltree)
        for item in xml_article_titles.article_title_list[1:]:
            yield {"language": item["lang"], "text": item["text"]}

    def get_section(self):
        xml_toc_sections = ArticleTocSections(self.xmltree)
        for item in xml_toc_sections.article_section:
            yield {"language": item["lang"], "text": item["text"]}
        for item in xml_toc_sections.sub_article_section:
            yield {"language": item["lang"], "text": item["text"]}

    def get_abstracts(self):
        try:
            for item in Abstract(self.xmltree).get_abstracts(style="only_p"):
                yield {"language": item["lang"], "text": item["abstract"]}
        except Exception as e:
            return []

    def get_keywords(self):
        for lang, keywords in (
            KwdGroup(self.xmltree).extract_kwd_extract_data_by_lang(True).items()
        ):
            yield {"language": lang, "keywords": keywords}

    def get_doi_with_lang(self):
        doi_with_lang = DoiWithLang(self.xmltree)
        for item in doi_with_lang.data:
            yield {"language": item["lang"], "doi": item["value"]}

    def get_renditions(self):
        root = ArticleAndSubArticles(self.xmltree)
        for item in ArticleRenditions(self.xmltree).article_renditions:
            yield {
                "language": item["language"] or root.main_lang,
                "uri": item.get("uri"),
            }

    def get_main_metadata(self):
        xml_article_titles = ArticleTitles(self.xmltree)
        xml_toc_section = ArticleTocSections(self.xmltree)
        xml_abstracts = Abstract(self.xmltree)
        root = ArticleAndSubArticles(self.xmltree)
        xml_doi = DoiWithLang(self.xmltree)

        return dict(
            title=xml_article_titles.article_title["text"],
            section=xml_toc_section.article_section[0]["text"],
            abstract=None,
            lang=root.main_lang,
            doi=xml_doi.main_doi,
        )

    @property
    def main_article_type(self):
        root = ArticleAndSubArticles(self.xmltree)
        return root.main_article_type

    def get_htmls(self):
        root = ArticleAndSubArticles(self.xmltree)
        for item in root.data:
            yield {"language": item["lang"]}

    def get_in_issue(self, order):
        aids = ArticleIds(self.xmltree)
        article_meta_issue = ArticleMetaIssue(self.xmltree)
        return dict(
            order=order,
            fpage=article_meta_issue.fpage,
            fpage_seq=article_meta_issue.fpage_seq,
            lpage=article_meta_issue.lpage,
            elocation=article_meta_issue.elocation_id,
        )
