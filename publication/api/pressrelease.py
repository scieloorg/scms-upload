import logging

from django.utils.translation import gettext_lazy as _

from publication.api.publication import PublicationAPI
from publication.utils.pressrelease import build_pressrelease


def publish_pressrelease(pressrelease, api_data):
    payload = {}
    builder = PressReleasePayload(data=payload)
    build_pressrelease(pressrelease, builder)
    api = PublicationAPI(**api_data)
    return api.post_data(payload, {"journal_acronym": pressrelease.journal.journal_acron})


class PressReleasePayload:
    """
    {
        "journal_id": "",
        "title": "",
        "language": "",
        "doi": "",
        "content": "",
        "url": "",
        "publication_date": "",
    }
    
    """

    def __init__(self, data=None):
        self.data = data

    def add_journal_title(self, issn):
        self.data["journal_id"] = issn

    def add_title_pressrelease(self, title):
        self.data["title"] = title

    def add_language(self, lang_code2):
        self.data["language"] = lang_code2

    def add_doi(self, doi):
        if doi:
            self.data["doi"] = doi

    def add_content(self, content):
        self.data["content"] = content

    def add_url(self, url):
        self.data["url"] = url

    def add_media_content(self, media_content):
        self.data["media_content"] = media_content

    def add_publication_data(self, publication_data):
        self.data["publication_data"] = publication_data

