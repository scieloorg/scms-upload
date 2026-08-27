import pytest

from article.models import Article
from article.wagtail_hooks import (
    RelatedItemSnippetViewSet,
    RequestArticleChangeSnippetViewSet,
)
from issue.wagtail_hooks import IssueSnippetViewSet
from journal.models import Journal, OfficialJournal
from team.models import JournalTeamMember, TeamRole


@pytest.mark.django_db
def test_relational_forms_limit_articles_and_journals_to_membership(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="journal-member")
    official_journal_a = OfficialJournal.objects.create(
        title="Journal A",
        issn_electronic="1111-1111",
        creator=user,
    )
    journal_a = Journal.objects.create(
        official_journal=official_journal_a,
        journal_acron="ja",
        creator=user,
    )
    official_journal_b = OfficialJournal.objects.create(
        title="Journal B",
        issn_electronic="2222-2222",
        creator=user,
    )
    journal_b = Journal.objects.create(
        official_journal=official_journal_b,
        journal_acron="jb",
        creator=user,
    )
    JournalTeamMember.objects.create(
        user=user,
        journal=journal_a,
        role=TeamRole.MEMBER,
        creator=user,
    )
    article_a = Article.objects.create(journal=journal_a, creator=user)
    article_b = Article.objects.create(journal=journal_b, creator=user)

    issue_form = IssueSnippetViewSet().get_form_class()(for_user=user)
    change_form = RequestArticleChangeSnippetViewSet().get_form_class()(
        for_user=user
    )
    related_form = RelatedItemSnippetViewSet().get_form_class()(for_user=user)

    assert set(issue_form.fields["journal"].queryset) == {journal_a}
    assert set(change_form.fields["article"].queryset) == {article_a}
    assert set(related_form.fields["source_article"].queryset) == {article_a}
    assert set(related_form.fields["target_article"].queryset) == {article_a}
    assert article_b not in change_form.fields["article"].queryset
