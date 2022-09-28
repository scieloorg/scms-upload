from packtools.sps.models import (
    article_and_subarticles as sps_articles_and_subarticles,
    article_ids as sps_article_ids,
    article_titles as sps_article_titles,
    article_authors as sps_article_authors,
    article_doi_with_lang as sps_article_doi_with_lang,
    front_articlemeta_issue as sps_front_articlemeta_issue,
    front_journal_meta as sps_front_journal_meta,
    related_articles as sps_related_articles,
)


def get_article_data_for_comparison(xmltree, remove_null_values=True):
    article_data = {}

    # ArticleIds
    obj_aid = sps_article_ids.ArticleIds(xmltree)
    article_data['aid'] = obj_aid.v3
    article_data['pid'] = obj_aid.v2
    article_data['aop_pid'] = obj_aid.aop_pid

    # ArticleMetaIssue
    obj_amissue = sps_front_articlemeta_issue.ArticleMetaIssue(xmltree)
    article_data['fpage'] = obj_amissue.fpage
    article_data['lpage'] = obj_amissue.lpage
    article_data['elocation'] = obj_amissue.elocation_id
    article_data['fpage_sequence'] = obj_amissue.fpage_seq

    # ISSN (front_journal_meta)
    obj_journal_issn = sps_front_journal_meta.ISSN(xmltree)

    # FIXME: qual é o issn de opac.article.journal?
    # article_data['journal'] = {
    #     'print_issn': obj_journal_issn.ppub,
    #     'eletronic_issn': obj_journal_issn.epub,
    # }
    article_data['journal'] = obj_journal_issn.ppub

    # FIXME: substituir por método/propriedade de packtools.sps.models.front_articlemeta_issue    
    article_data['issue'] = f'{obj_journal_issn.ppub}-{obj_amissue.collection_date["year"]}-v{obj_amissue.volume}-n{obj_amissue.number}'

    # ArticleTitles
    obj_titles = sps_article_titles.ArticleTitles(xmltree)
    article_data['title'] = obj_titles.article_title['text']
    article_data['translated_titles'] = []
    for t in obj_titles.trans_titles:
        article_data['translated_titles'].append(
            {'name': t['text'], 'lang': t['lang']},
        )

    # ArticleAuthors
    obj_authors = sps_article_authors.Authors(xmltree)

    # FIXME: substir authors por authors_meta assim que houver affiliation em packtools.sps.models.authors
    # article_data['authors_meta'] = []
    # for c in obj_authors.contribs:
    #     article_data['authors_meta'].append({
    #         'name': f'{c.get("surname", "")}, {c.get("given_names", "")}',
    #         'affiliation': c.get('affiliation', ""),
    #         'orcid': c.get('orcid', ""),
    #     })
    article_data['authors'] = []
    for c in obj_authors.contribs:
        article_data['authors'].append(
            f'{c.get("surname")}, {c.get("given_names")}'
        )

    # DoiWithLang
    obj_dwl = sps_article_doi_with_lang.DoiWithLang(xmltree)
    article_data['doi'] = obj_dwl.main_doi
    article_data['doi_with_lang'] = []
    for lv in obj_dwl.data:
        article_data['doi_with_lang'].append({
            'doi': lv['value'],
            'language': lv['lang'],
        })

    # ArticleAndSubArticles
    obj_asa = sps_articles_and_subarticles.ArticleAndSubArticles(xmltree)
    article_data['original_language'] = obj_asa.main_lang
    article_data['languages'] = [d['lang'] for d in obj_asa.data]
    article_data['type'] = obj_asa.main_article_type

    # RelatedArticles
    obj_rels = sps_related_articles.RelatedItems(xmltree)
    article_data['related_articles'] = []
    for r in obj_rels.related_articles:
        article_data['related_articles'].append({
            'ref_id': r['id'],
            'doi' : r['href'],
            'related_type' : r['related-article-type'],
        })

    if remove_null_values:
        for k, v in article_data.copy().items():
            if v is None or len(v) == 0:
                del article_data[k]

    return article_data
