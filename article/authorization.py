from datetime import date

from django.utils import timezone

from article import choices
from journal.models import JournalCollection
from package.choices import PKG_ORIGIN_MIGRATION
from team.authorization import get_user_permission_journal_ids
from team.models import CollectionTeamMember, TeamRole


def is_public_article(article):
    """Require public evidence, never treating a QA-only publication as public."""
    if not article or not article.pk or not getattr(article, "is_active", True):
        return False

    if article.package_set.filter(public_ws_status="published").exists():
        return True
    if article.pages.filter(
        purpose__in=(
            choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC,
            choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
        ),
        status__in=(
            choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE,
            choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
            choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH,
        ),
    ).exists():
        return True
    if article.requestarticlechange_set.filter(was_public=True).exists():
        return True
    if not article.sps_pkg_id or article.sps_pkg.origin != PKG_ORIGIN_MIGRATION:
        return False
    try:
        value = article.first_pubdate_iso
        published = (
            date.fromisoformat(value[:10]) if value else article.first_publication_date
        )
        return bool(published and published <= timezone.now().date())
    except (ValueError, TypeError):
        return False


def allowed_article_change_types(user, article):
    """Return authorized choice values, in declaration order, for this journal."""
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or not is_public_article(article)
    ):
        return ()
    if user.is_superuser:
        return tuple(value for value, label in choices.REQUEST_CHANGE_TYPE)

    allowed = set()
    if user.has_perm("article.add_requestarticlechange"):
        collections = CollectionTeamMember.objects.filter(
            user=user,
            is_active_member=True,
            role__in=(TeamRole.MANAGER, TeamRole.MEMBER),
        ).values_list("collection_id", flat=True)
        if JournalCollection.objects.filter(
            journal_id=article.journal_id,
            collection_id__in=collections,
        ).exists():
            allowed.add(choices.RCT_UPDATE)

    if article.journal_id in get_user_permission_journal_ids(
        user, "article", "request_article_change"
    ):
        allowed.update(
            value
            for value, label in choices.REQUEST_CHANGE_TYPE
            if value != choices.RCT_UPDATE
        )
    return tuple(
        value for value, label in choices.REQUEST_CHANGE_TYPE if value in allowed
    )


def can_request_article_change(user, article, change_type=None):
    """With no type, report whether at least one change type is permitted."""
    allowed = allowed_article_change_types(user, article)
    return bool(allowed) if change_type is None else change_type in allowed
