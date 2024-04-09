import logging
import feedparser
from config import celery_app
from datetime import datetime
from django.db.models import Q

from core.utils.requester import fetch_data
from core.models import PressRelease
from collection.models import Language
from pid_provider.tasks import _get_user
from journal.models import Journal


RSS_PRESS_RELEASES_FEEDS_BY_CATEGORY = {
    'pt_BR': {
        'display_name': 'SciELO em Perspectiva Press Releases',
        'url': 'https://pressreleases.scielo.org/blog/category/{1}/feed/'
    },
    'es': {
        'display_name': 'SciELO en Perspectiva Press Releases',
        'url': 'https://pressreleases.scielo.org/{0}/category/press-releases/{1}/feed/',
    },
    'en': {
        'display_name': 'SciELO in Perspective Press Releases',
        'url': 'https://pressreleases.scielo.org/{0}/category/press-releases/{1}/feed/',
    },
}


@celery_app.task(bind=True)
def try_fetch_and_register_press_release(self, journal_acronym=None, pressrelease_lang=None, username=None, user_id=None):
    query_condition = Q(journal_acron=journal_acronym) if journal_acronym else Q()
    journals_query = Journal.objects.filter(query_condition)

    dict_aux = {}
    if pressrelease_lang and pressrelease_lang in RSS_PRESS_RELEASES_FEEDS_BY_CATEGORY:
        dict_aux[pressrelease_lang] = RSS_PRESS_RELEASES_FEEDS_BY_CATEGORY[pressrelease_lang]
        
    dict_aux = RSS_PRESS_RELEASES_FEEDS_BY_CATEGORY    
    for journal in journals_query:
        for lang, url in dict_aux.items():
            if journal.journal_acron:
                press_release_url_by_lang = url.get("url").format(lang, journal.journal_acron)

                response = fetch_data(press_release_url_by_lang, json=False, timeout=2, verify=False)
                content = feedparser.parse(response)

                if content.bozo:
                    logging.error(
                        "Could not parse feed content from '%s'. During processing this error '%s' was thrown.",
                        press_release_url_by_lang,
                        content.bozo_exception,
                    )
                
                for entry in content.get("entries", []):
                    register_press_release.apply_async(kwargs=dict(
                        journal_id=journal.id,
                        lang_code=lang,
                        entry=entry,
                        username=username,
                        user_id=user_id,
                    ))


@celery_app.task(bind=True)
def register_press_release(self, journal_id, lang_code, entry, username, user_id):
    user = _get_user(self.request, username, user_id)
    journal = Journal.objects.get(id=journal_id)
    lang = Language.get(code2=lang_code)
    published = entry.get("published") 
    publication_date = datetime.strptime(published, '%a, %d %b %Y %H:%M:%S %z')
    
    try:
        media_content = entry.get("media_content")[0].get("url")
    except AttributeError:
        pass

    PressRelease.create_or_update(
        url=entry.get("id"),
        journal=journal,
        language=lang,
        title=entry.get("title"),
        content=entry.get("summary"),
        media_content=media_content,
        publication_date=publication_date,
        user=user,
    )
