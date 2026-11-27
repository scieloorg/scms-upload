from datetime import date

from django.contrib.auth import get_user_model
from lxml import etree

from article import choices
from article.models import Article, ArticleCollection
from collection.models import Collection
from issue.models import Issue
from journal.models import Journal

User = get_user_model()


def make_xmltree(back="", sub_article=""):
    xml = (
        '<article article-type="research-article">'
        f"<body/><back>{back}</back>{sub_article}</article>"
    )
    return etree.ElementTree(etree.fromstring(xml))


class ReportDataMixin:
    """
    Artigos:
        1. data-available, legenda 2023, online 2022-12-01, coleções aaa e bbb, periódico X
        2. absent,         legenda 2023, online 2023-02-01, coleção aaa, periódico X
        3. data-available, legenda 2024, online 2023-11-01, coleção aaa, periódico Y
        4. não processado, legenda 2024, online 2024-03-01, coleção bbb, periódico Z
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username="report_user")
        cls.col_a = Collection.objects.create(acron="aaa", creator=cls.user)
        cls.col_b = Collection.objects.create(acron="bbb", creator=cls.user)
        cls.issue_2023 = Issue.objects.create(publication_year="2023", creator=cls.user)
        cls.issue_2024 = Issue.objects.create(publication_year="2024", creator=cls.user)
        cls.journal_x = Journal.objects.create(title="Journal X", creator=cls.user)
        cls.journal_y = Journal.objects.create(title="Journal Y", creator=cls.user)
        cls.journal_z = Journal.objects.create(title="Journal Z", creator=cls.user)

        def make(status, issue, pub_date, collections, journal):
            article = Article.objects.create(
                creator=cls.user,
                issue=issue,
                journal=journal,
                first_publication_date=pub_date,
                data_availability_status=status,
            )
            for col in collections:
                ArticleCollection.objects.create(
                    creator=cls.user, article=article, collection=col
                )
            return article

        cls.articles = [
            make(choices.DAS_DATA_AVAILABLE, cls.issue_2023, date(2022, 12, 1), [cls.col_a, cls.col_b], cls.journal_x),
            make(choices.DAS_ABSENT, cls.issue_2023, date(2023, 2, 1), [cls.col_a], cls.journal_x),
            make(choices.DAS_DATA_AVAILABLE, cls.issue_2024, date(2023, 11, 1), [cls.col_a], cls.journal_y),
            make(None, cls.issue_2024, date(2024, 3, 1), [cls.col_b], cls.journal_z),
        ]

    @staticmethod
    def cell(row, status):
        return next(c for c in row["cells"] if c["status"] == status)
