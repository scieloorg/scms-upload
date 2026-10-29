"""Exercise 0012's data callbacks on the final schema, without rewinding it."""

from datetime import date
from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.db.migrations.state import ProjectState
from django.test import TestCase

from article.models import Article, ArticleWebPage, RequestArticleChange
from package.models import SPSPkg
from upload.models import Package

migration = import_module(
    "article.migrations.0012_requestarticlechange_status_and_more"
)


class ChangeMigrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="change-migration")
        cls.historical_apps = ProjectState.from_apps(apps).apps

    def article(self, status="required-update", **fields):
        return Article.objects.create(creator=self.user, status=status, **fields)

    def request(
        self, article, change_type="update", comment="Legacy justification", **fields
    ):
        # Multiple completed rows represent pre-0012 history without violating
        # the final schema's unique-active-request constraint.
        return RequestArticleChange.objects.create(
            creator=self.user,
            article=article,
            change_type=change_type,
            comment=comment,
            status="completed",
            **fields,
        )

    def preserve(self):
        # These callbacks only use the editor's connection alias. Do not enter
        # its DDL context (or change migration state) inside TestCase's atomic.
        migration.preserve_legacy_requests(self.historical_apps, connection.schema_editor())

    def test_public_evidence_reopens_only_latest_matching_request_and_is_repeatable(
        self,
    ):
        for evidence in ("package", "page", "migrated"):
            for kind in ("update", "erratum"):
                with self.subTest(evidence=evidence, kind=kind):
                    article = self.article(status=f"required-{kind}")
                    if evidence == "package":
                        Package.objects.create(
                            creator=self.user,
                            article=article,
                            public_ws_status="published",
                        )
                    elif evidence == "page":
                        ArticleWebPage.objects.create(
                            creator=self.user,
                            article=article,
                            purpose="PUBLIC",
                            status="available",
                        )
                    else:
                        article.sps_pkg = SPSPkg.objects.create(
                            creator=self.user, origin="MIGRATION"
                        )
                        article.first_pubdate_iso = "2000-01-01"
                        article.save()
                    earlier = self.request(article, kind)
                    latest = self.request(article, kind)
                    # Equal timestamps still have deterministic latest-by-PK order.
                    RequestArticleChange.objects.filter(pk=latest.pk).update(
                        created=earlier.created
                    )
                    self.request(article, "erratum" if kind == "update" else "update")
                    before_article = (
                        Article.objects.filter(pk=article.pk).values().get()
                    )
                    before_requests = list(
                        RequestArticleChange.objects.filter(article=article)
                        .order_by("pk")
                        .values()
                    )

                    for attempt in range(2):
                        with self.subTest(attempt=attempt):
                            # The second call starts with an active request: the
                            # reset must happen before reopening, not duplicate it.
                            self.preserve()
                            after = list(
                                RequestArticleChange.objects.filter(article=article)
                                .order_by("pk")
                                .values()
                            )
                            expected = [dict(row) for row in before_requests]
                            for row in expected:
                                row["status"] = (
                                    "pending" if row["id"] == latest.pk else "completed"
                                )
                                row["was_public"] = row["id"] == latest.pk
                            self.assertEqual(after, expected)
                            self.assertEqual(
                                Article.objects.filter(pk=article.pk).values().get(),
                                before_article,
                            )

    def test_migrated_date_fallback_does_not_write_publication_fields(self):
        article = self.article(
            sps_pkg=SPSPkg.objects.create(creator=self.user, origin="MIGRATION"),
            first_pubdate_iso=None,
            first_publication_date=date(2000, 1, 1),
        )
        request = self.request(article)
        before = Article.objects.filter(pk=article.pk).values().get()
        self.preserve()
        request.refresh_from_db()
        self.assertEqual((request.status, request.was_public), ("pending", True))
        self.assertEqual(Article.objects.filter(pk=article.pk).values().get(), before)

    def test_no_public_evidence_or_no_matching_required_status_keeps_history_completed(
        self,
    ):
        cases = (
            ("date-only", "required-update", "update"),
            ("qa-only", "required-erratum", "erratum"),
            ("public-wrong-status", "published", "update"),
            ("public-wrong-kind", "required-update", "erratum"),
        )
        requests = []
        for evidence, status, kind in cases:
            with self.subTest(evidence=evidence):
                article = self.article(status=status, first_pubdate_iso="2000-01-01")
                if evidence == "qa-only":
                    Package.objects.create(
                        creator=self.user, article=article, qa_ws_status="published"
                    )
                    ArticleWebPage.objects.create(
                        creator=self.user,
                        article=article,
                        purpose="QA",
                        status="available",
                    )
                elif evidence.startswith("public-"):
                    Package.objects.create(
                        creator=self.user, article=article, public_ws_status="published"
                    )
                request = self.request(article, kind, was_public=True)
                # Check normalization of old active/snapshot values, too.
                RequestArticleChange.objects.filter(pk=request.pk).update(
                    status="received"
                )
                requests.append(request)
        requests.append(self.request(None, was_public=True))
        self.preserve()
        for request in requests:
            with self.subTest(request=request.pk):
                request.refresh_from_db()
                self.assertEqual(
                    (request.status, request.was_public), ("completed", False)
                )

    def test_blank_latest_justification_does_not_reopen_an_older_request(self):
        for comment in (None, "", " \n\t"):
            with self.subTest(comment=comment):
                article = self.article()
                Package.objects.create(
                    creator=self.user, article=article, public_ws_status="published"
                )
                earlier = self.request(article)
                latest = self.request(article, comment=comment)
                self.preserve()
                self.assertEqual(
                    list(
                        RequestArticleChange.objects.filter(
                            pk__in=(earlier.pk, latest.pk)
                        )
                        .order_by("pk")
                        .values_list("status", "was_public")
                    ),
                    [("completed", False), ("completed", False)],
                )
                latest.refresh_from_db()
                self.assertEqual(latest.comment, comment)

    def test_permission_is_granted_only_to_the_four_editorial_groups(self):
        editorial = (
            "COLLECTION_TEAM_ADMIN",
            "COLLECTION_TEAM_MEMBER",
            "JOURNAL_TEAM_ADMIN",
            "JOURNAL_TEAM_MEMBER",
        )
        excluded = ("COMPANY_TEAM_ADMIN", "COMPANY_TEAM_MEMBER", "OTHER")
        # The normal post_migrate handler must already have created this custom
        # permission; do not manufacture it in the test fixture.
        permission = Permission.objects.get(
            content_type__app_label="article",
            content_type__model="article",
            codename="request_article_change",
        )
        groups = [
            Group.objects.get_or_create(name=name)[0] for name in editorial + excluded
        ]
        # Seed the pre-migration relation directly: live canonical-group signals
        # intentionally forbid edits, while historical migration models have none.
        Group.permissions.through.objects.filter(
            group_id__in=[group.pk for group in groups], permission_id=permission.pk
        ).delete()
        before = Permission.objects.count()
        for attempt in range(2):
            migration.grant_editorial_requests(self.historical_apps, connection.schema_editor())
            with self.subTest(attempt=attempt):
                self.assertEqual(Permission.objects.count(), before)
                for group in groups:
                    with self.subTest(group=group.name):
                        self.assertEqual(
                            group.permissions.filter(pk=permission.pk).exists(),
                            group.name in editorial,
                        )
