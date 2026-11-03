"""Validate and bind public-article changes before PID lookup or reception."""

import os

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from lxml import etree
from lxml.etree import XMLSyntaxError
from packtools.sps.pid_provider.xml_sps_lib import GetXMLItemsError

from article import choices as article_choices
from article.authorization import is_public_article
from article.models import Article, RequestArticleChange
from team.models import get_user_membership_ids
from upload import choices
from upload.models import Package
from upload.validation.article_changes import (
    CHANGE_TYPES,
    XLINK_HREF,
    normalize_doi,
    require_document_pdfs,
    validate_change_pair,
)

NOTICE_TYPES = {definition[0]: kind for kind, definition in CHANGE_TYPES.items()}


def _root(document):
    tree = document.xmltree
    return tree.getroot() if hasattr(tree, "getroot") else tree


def _doi(document):
    return normalize_doi(
        _root(document).findtext("front/article-meta/article-id[@pub-id-type='doi']")
    )


def _article(document):
    pid = document.v3
    if pid:
        try:
            return Article.objects.get(pid_v3=pid)
        except Article.DoesNotExist:
            pass
    doi = _doi(document)
    matches = (
        Article.objects.filter(doi_with_lang__doi__iexact=doi).distinct()
        if doi
        else Article.objects.none()
    )
    try:
        return matches.get()
    except Article.DoesNotExist:
        name = os.path.splitext(os.path.basename(document.filename))[0]
        candidates = Article.objects.filter(
            sps_pkg__sps_pkg_name=name,
            requestarticlechange__change_type=article_choices.RCT_ERRATUM,
            requestarticlechange__status__in=(
                article_choices.RCS_PENDING,
                article_choices.RCS_RECEIVED,
            ),
        ).distinct()
        try:
            return candidates.get()
        except Article.DoesNotExist:
            return None
        except Article.MultipleObjectsReturned:
            raise ValidationError(
                _("The submitted XML identifies more than one article.")
            )
    except Article.MultipleObjectsReturned:
        raise ValidationError(_("The submitted XML identifies more than one article."))


def _active_request(article, submission, user):
    try:
        change_request = RequestArticleChange.objects.select_for_update(
            of=("self",)
        ).get(
            article=article,
            status__in=(article_choices.RCS_PENDING, article_choices.RCS_RECEIVED),
        )
    except RequestArticleChange.DoesNotExist:
        raise ValidationError(
            _(
                "The original article needs an active, compatible change request before reception."
            )
        )
    if change_request.submission_id and change_request.submission_id != submission.pk:
        if change_request.packages.filter(
            pkg_zip_id=change_request.submission_id,
            status__in=(*choices.PS_WIP, choices.PS_PUBLISHED),
        ).exists():
            raise ValidationError(
                _("This change request already has a submission in progress.")
            )
    return change_request


def _published_xml(article, change_request):
    try:
        if change_request.original_xml:
            parser = etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True
            )
            return etree.fromstring(change_request.original_xml.encode("utf-8"), parser)
        previous = (
            article.package_set.filter(
                public_ws_status=choices.PUBLISHED,
            )
            .exclude(file="")
            .order_by("-pk")
            .first()
        )
        if previous is not None:
            document = previous.xml_with_pre
        elif article.sps_pkg_id:
            document = article.sps_pkg.xml_with_pre
        else:
            raise ValueError("missing published package")
        if document is None:
            raise ValueError("missing published XML")
        return document.xmltree
    except (
        AttributeError,
        OSError,
        ValueError,
        GetXMLItemsError,
        XMLSyntaxError,
    ) as error:
        raise ValidationError(
            _(
                "The published XML could not be verified. The previous submission was preserved."
            )
        ) from error


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
        node.text.replace("-", "").strip()
        for node in _root(document).findall("front/journal-meta/issn")
        if node.text
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
    covered = set()
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
            covered.update(member_ids)
        elif (
            request.status == article_choices.RCS_COMPLETED
            and not members.exclude(public_ws_status=choices.PUBLISHED).exists()
        ):
            finished.update(member_ids)
        else:
            raise ValidationError(
                _("This submission no longer belongs to an active change request.")
            )
    if {package.pk for package in packages} <= covered | finished:
        return
    packages = [package for package in packages if package.pk not in finished]

    documents = {}
    for package in packages:
        try:
            document = package.xml_with_pre
            if document is not None:
                documents[package.pk] = document
        except (OSError, ValueError, GetXMLItemsError, XMLSyntaxError):
            # Ordinary malformed submissions retain the existing diagnostic path.
            continue
    if not documents:
        return

    by_doi = {}
    for package_id, document in documents.items():
        aliases = {_doi(document)}
        aliases.update(
            normalize_doi("".join(node.itertext()))
            for node in _root(document).findall(
                ".//sub-article[@article-type='translation']/front-stub/article-id[@pub-id-type='doi']"
            )
        )
        for doi in aliases - {""}:
            by_doi.setdefault(doi, []).append(package_id)
    registered = {pk: _article(document) for pk, document in documents.items()}
    if not user or not user.is_authenticated or not user.is_active:
        raise ValidationError(_("An authorized depositor is required."))
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
    snapshots = {}
    roles = {}
    paired = set()

    for notice_id, notice in documents.items():
        kind = NOTICE_TYPES.get(_root(notice).get("article-type"))
        if not kind:
            continue
        # An already published notice can itself be updated as an original.
        existing = registered[notice_id]
        if existing is not None and is_public_article(existing):
            continue
        relation_type = CHANGE_TYPES[kind][1]
        relations = _root(notice).findall("front/article-meta/related-article")
        targets = {
            normalize_doi(node.get(XLINK_HREF))
            for node in relations
            if node.get("related-article-type") == relation_type
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
            request = _active_request(article, submission, user)
            if request.change_type != kind:
                raise ValidationError(
                    _(
                        "The notice type does not match the active request on the original article."
                    )
                )
            _check_journal(original, article)
            _check_journal(notice, article)
            original_name = os.path.splitext(os.path.basename(original.filename))[0]
            if not article.sps_pkg_id or original_name != article.sps_pkg.sps_pkg_name:
                raise ValidationError(
                    _(
                        "Keep the previously published original filename in the change package."
                    )
                )
            published = _published_xml(article, request)
            validate_change_pair(kind, original.xmltree, notice.xmltree, published)
            snapshots[request.pk] = etree.tostring(published, encoding="unicode")
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
        request = _active_request(article, submission, user)
        if request.change_type != article_choices.RCT_UPDATE:
            raise ValidationError(
                _(
                    "This request requires both a change notice and the updated original, in XML and PDF."
                )
            )
        bindings[request.pk] = (request, {package_id})
        roles[package_id] = choices.CPR_ORIGINAL

    for request, members in bindings.values():
        request.submission = submission
        request.status = article_choices.RCS_RECEIVED
        request.updated_by = user
        request.was_public = True
        fields = ["submission", "status", "was_public", "updated_by", "updated"]
        if request.pk in snapshots and not request.original_xml:
            request.original_xml = snapshots[request.pk]
            fields.append("original_xml")
        request.save(update_fields=fields)
        for package_id in members:
            package = records[package_id]
            package.change_requests.add(request)
            package.change_role = roles[package_id]
            package.category = request.change_type
            Package.objects.filter(pk=package_id).update(
                change_role=package.change_role, category=package.category
            )
        if request.change_type != article_choices.RCT_UPDATE:
            original_ids = [pk for pk in members if roles[pk] == choices.CPR_ORIGINAL]
            for notice_id in members - set(original_ids):
                records[notice_id].linked.add(*(records[pk] for pk in original_ids))
