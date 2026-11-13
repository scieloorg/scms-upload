"""Validate and bind public-article changes before PID lookup or reception."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from lxml.etree import XMLSyntaxError
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError, GetXmlWithPreError

from article import choices as article_choices
from article.authorization import is_public_article
from article.models import Article, RequestArticleChange
from team.models import get_user_membership_ids
from upload import choices
from upload.models import PackageZip
from upload.validation.article_changes import (
    CHANGE_TYPES,
    normalize_doi,
    require_document_pdfs,
    validate_change_pair,
)

NOTICE_TYPES = {definition[0]: kind for kind, definition in CHANGE_TYPES.items()}


def _check_journal(document, article):
    official = article.journal.official_journal
    if official is None:
        raise ValidationError(_("The original journal must have registered ISSNs."))
    expected = {
        value.replace("-", "").strip()
        for value in (official.issn_electronic, official.issn_print)
        if value
    }
    submitted = {
        value.replace("-", "").strip()
        for value in (document.journal_issn_electronic, document.journal_issn_print)
        if value
    }
    if not expected or not expected.intersection(submitted):
        raise ValidationError(
            _("The notice and updated original must belong to the authorized journal.")
        )


@transaction.atomic
def prepare_change_requests(user, packages):
    """Validate the whole submission first; never mutate a previous package/article.

    Binding is idempotent within the same submission. A failed attempt can be
    replaced only after its packages leave the processing/review/publication states.
    """
    packages = list(packages)
    if not packages:
        return

    submission = packages[0].pkg_zip
    if submission is None or any(
        package.pkg_zip_id != submission.pk for package in packages
    ):
        raise ValidationError(
            _("Change documents must be received in one submitted package.")
        )
    if not user or not user.is_authenticated or not user.is_active:
        raise ValidationError(_("An authorized depositor is required."))

    # All batch preparation and retry paths acquire the submission lock first.
    PackageZip.objects.select_for_update().get(pk=submission.pk)

    finished = set()
    for request in RequestArticleChange.objects.filter(
        packages__in=packages
    ).distinct():
        members = request.packages.filter(pkg_zip=submission)
        member_ids = set(members.values_list("pk", flat=True))
        if request.submission_id != submission.pk:
            raise ValidationError(
                _("This submission no longer belongs to an active change request.")
            )
        if request.status == article_choices.RCS_RECEIVED:
            pass  # Revalidate authorization, XML and request compatibility below.
        elif (
            request.status == article_choices.RCS_COMPLETED
            and not members.exclude(public_ws_status=choices.PUBLISHED).exists()
        ):
            finished.update(member_ids)
        else:
            raise ValidationError(
                _("This submission no longer belongs to an active change request.")
            )
    if {package.pk for package in packages} <= finished:
        return
    packages = [package for package in packages if package.pk not in finished]

    documents = {}
    for package in packages:
        try:
            document = package.xml_with_pre
            if document is not None:
                documents[package.pk] = document
        except (
            OSError,
            ValueError,
            GetXMLItemsError,
            GetXmlWithPreError,
            XMLSyntaxError,
        ):
            # Ordinary malformed submissions retain the existing diagnostic path.
            continue
    if not documents:
        return

    by_doi = {}
    for package_id, document in documents.items():
        aliases = {
            normalize_doi(item["value"])
            for item in document.article_doi_with_lang
            if item["value"]
        }
        for doi in aliases - {""}:
            by_doi.setdefault(doi, []).append(package_id)
    registered = {
        pk: Article.identify(
            pid_v3=document.v3,
            pid_v2=document.v2,
            doi=normalize_doi(document.main_doi),
            collection_acron=document.collection,
        )
        for pk, document in documents.items()
    }
    membership = get_user_membership_ids(user)
    if not user.is_superuser and any(
        article is not None
        and article.journal_id not in membership.get("journal_list_ids", [])
        for article in registered.values()
    ):
        raise ValidationError(
            _("The depositor is not authorized for the original article.")
        )

    article_ids = {article.pk for article in registered.values() if article is not None}
    list(
        Article.objects.select_for_update(of=("self",))
        .filter(pk__in=article_ids)
        .order_by("pk")
    )

    records = {package.pk: package for package in packages}
    bindings = {}
    roles = {}
    paired = set()

    for notice_id, notice in documents.items():
        kind = NOTICE_TYPES.get(notice.xmltree.get("article-type"))
        if not kind:
            continue
        # An already published notice can itself be updated as an original.
        existing = registered[notice_id]
        if existing is not None and is_public_article(existing):
            continue
        relation_type = CHANGE_TYPES[kind][1]
        targets = {
            normalize_doi(item.get("href"))
            for item in notice.related_items
            if item.get("related-article-type") == relation_type
        }
        if not targets:
            raise ValidationError(
                _("A change notice must identify its original article by DOI.")
            )
        for target in sorted(targets):
            candidates = by_doi.get(target, [])
            if len(candidates) != 1 or candidates[0] == notice_id:
                raise ValidationError(
                    _(
                        "Submit the updated original XML together with its change notice."
                    )
                )
            original_id = candidates[0]
            original = documents[original_id]
            article = registered[original_id]
            if article is None or not is_public_article(article):
                raise ValidationError(
                    _("The notice must refer to an already public original article.")
                )

            request = RequestArticleChange.active_for_submission(article, submission)
            if request.change_type != kind:
                raise ValidationError(
                    _(
                        "The notice type does not match the active request on the original article."
                    )
                )
            _check_journal(original, article)
            _check_journal(notice, article)
            validate_change_pair(kind, original.xmltree, notice.xmltree)
            for package_id in (original_id, notice_id):
                document = documents[package_id]
                require_document_pdfs(
                    document.xmltree, document.filenames, document.filename
                )
            bindings.setdefault(request.pk, (request, set()))[1].update(
                (original_id, notice_id)
            )
            for package_id, role in (
                (original_id, choices.CPR_ORIGINAL),
                (notice_id, choices.CPR_NOTICE),
            ):
                if package_id in roles and roles[package_id] != role:
                    raise ValidationError(
                        _("A submitted document has conflicting change roles.")
                    )
                roles[package_id] = role
            paired.update((original_id, notice_id))

    for package_id, article in registered.items():
        if package_id in paired or article is None or not is_public_article(article):
            continue
        request = RequestArticleChange.active_for_submission(article, submission)
        if request.change_type != article_choices.RCT_UPDATE:
            raise ValidationError(
                _(
                    "This request requires both a change notice and the updated original, in XML and PDF."
                )
            )

        bindings[request.pk] = (request, {package_id})
        roles[package_id] = choices.CPR_ORIGINAL

    for request, members in bindings.values():
        request.receive_submission(user, submission)
        for package_id in members:
            records[package_id].bind_change_request(request, roles[package_id])
        if request.change_type != article_choices.RCT_UPDATE:
            original_ids = [pk for pk in members if roles[pk] == choices.CPR_ORIGINAL]
            for notice_id in members - set(original_ids):
                records[notice_id].linked.add(*(records[pk] for pk in original_ids))
