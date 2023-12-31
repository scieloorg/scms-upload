import logging
import os
import sys
from datetime import datetime
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.models.article_and_subarticles import ArticleAndSubArticles
from packtools.sps.models.v2.article_assets import ArticleAssets
from scielo_classic_website.htmlbody.html_body import HTMLContent
from wagtail.admin.panels import (
    FieldPanel,
    InlinePanel,
    MultiFieldPanel,
    ObjectList,
    TabbedInterface,
)
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article.models import Article
from collection import choices as collection_choices
from collection.models import Collection
from core.models import CommonControlField
from issue.models import Issue
from journal.choices import JOURNAL_AVAILABILTY_STATUS
from journal.models import Journal
from migration.models import (
    MigratedArticle,
    MigratedData,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)
from package import choices as package_choices
from package.models import BasicXMLFile, SPSPkg
from proc import exceptions
from proc.forms import ProcAdminModelForm
from tracker import choices as tracker_choices
from tracker.models import Event, UnexpectedEvent, format_traceback


class HTMLXMLCreateOrUpdateError(Exception):
    ...


class JournalEventCreateError(Exception):
    ...


class JournalEventReportCreateError(Exception):
    ...


class OperationStartError(Exception):
    ...


class OperationFinishError(Exception):
    ...


class Operation(CommonControlField):

    name = models.CharField(
        _("Name"),
        max_length=64,
        null=True,
        blank=True,
    )
    completed = models.BooleanField(null=True, blank=True, default=False)
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)

    base_form_class = ProcAdminModelForm

    panels = [
        FieldPanel("name"),
        FieldPanel("created", read_only=True),
        FieldPanel("updated", read_only=True),
        FieldPanel("completed"),
        FieldPanel("detail"),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} {self.started} {self.finished} {self.completed}"

    @property
    def started(self):
        return self.created and self.created.isoformat() or ""

    @property
    def finished(self):
        return self.updated and self.updated.isoformat() or ""

    @classmethod
    def start(
        cls,
        user,
        proc,
        name=None,
    ):
        try:
            obj = cls()
            obj.proc = proc
            obj.name = name
            obj.creator = user
            obj.save()
            return obj
        except Exception as exc:
            raise OperationStartError(
                f"Unable to create Operation ({name}). EXCEPTION: {type(exc)}  {exc}"
            )

    def finish(
        self,
        user,
        completed=False,
        exception=None,
        message_type=None,
        message=None,
        exc_traceback=None,
        detail=None,
    ):
        try:
            if not message_type:
                if not completed:
                    message_type = "ERROR"

            if message_type or exception or exc_traceback:
                self.event = Event.create(
                    user=user,
                    message_type=message_type,
                    message=message,
                    e=exception,
                    exc_traceback=exc_traceback,
                    detail=detail,
                )
                detail = self.event.data
            self.detail = detail
            self.completed = completed
            self.updated_by = user
            self.save()
            return self
        except Exception as exc:
            data = dict(
                completed=completed,
                exception=exception,
                message_type=message_type,
                message=message,
                exc_traceback=exc_traceback,
                detail=detail,
            )
            raise OperationFinishError(
                f"Unable to finish ({self.name}). Input: {data}. EXCEPTION: {type(exc)} {exc}"
            )


class JournalProcResult(Operation, Orderable):
    proc = ParentalKey("JournalProc", related_name="journal_proc_result")


class IssueProcResult(Operation, Orderable):
    proc = ParentalKey("IssueProc", related_name="issue_proc_result")


class ArticleProcResult(Operation, Orderable):
    proc = ParentalKey("ArticleProc", related_name="article_proc_result")


class BaseProc(CommonControlField):
    """ """

    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)

    migrated_data = models.ForeignKey(
        MigratedData, on_delete=models.SET_NULL, null=True, blank=True
    )
    migration_status = models.CharField(
        _("Status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )

    qa_ws_status = models.CharField(
        _("QA Website Status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )
    public_ws_status = models.CharField(
        _("Public Website Status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["pid"]),
        ]

    MigratedDataClass = MigratedData
    base_form_class = ProcAdminModelForm

    panel_status = [
        FieldPanel("migration_status"),
        FieldPanel("qa_ws_status"),
        FieldPanel("public_ws_status"),
    ]
    panel_proc_result = [
        # InlinePanel("proc_result"),
    ]
    # panel_events = [
    #     AutocompletePanel("events"),
    # ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_proc_result, heading=_("Result")),
        ]
    )

    def __unicode__(self):
        return f"{self.collection} {self.pid}"

    def __str__(self):
        return f"{self.collection} {self.pid}"

    @classmethod
    def get(cls, collection, pid):
        if collection and pid:
            return cls.objects.get(collection=collection, pid=pid)
        raise ValueError("BaseProc.get requires collection and pid")

    @classmethod
    def get_or_create(cls, user, collection, pid):
        try:
            obj = cls.get(collection, pid)
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.collection = collection
            obj.pid = pid
            obj.public_ws_status = tracker_choices.PROGRESS_STATUS_PENDING
            obj.save()
        return obj

    def start(self, user, name):
        # self.save()
        # operation = Operation.start(user, name)
        # self.operations.add(operation)
        # return operation
        return self.ProcResult.start(user, self, name)

    @classmethod
    def register_classic_website_data(
        cls,
        user,
        collection,
        pid,
        data,
        content_type,
        force_update=False,
    ):
        try:
            obj = None
            operation = None
            obj = cls.get_or_create(user, collection, pid)
            if (
                obj.migration_status != tracker_choices.PROGRESS_STATUS_TODO
                and not force_update
            ):
                return obj

            operation = obj.start(user, "get data from classic website")
            obj.migrated_data = cls.MigratedDataClass.register_classic_website_data(
                user,
                collection,
                pid,
                data,
                content_type,
                force_update,
            )
            obj.migration_status = obj.migrated_data.migration_status
            obj.save()
            operation.finish(
                user,
                completed=(
                    obj.migration_status == tracker_choices.PROGRESS_STATUS_TODO
                ),
                message=None,
            )
            return obj
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if operation:
                operation.finish(user, exc_traceback=exc_traceback, exception=e)
            else:
                UnexpectedEvent.create(
                    e=e,
                    exc_traceback=exc_traceback,
                    detail={
                        "task": "proc.BaseProc.register_classic_website_data",
                        "username": user.username,
                        "collection": collection.acron,
                        "pid": pid,
                    },
                )

    @classmethod
    def items_to_register(cls, collection, content_type, force_update):
        """
        Muda o migration_status de REPROC para TODO
        E se force_update = True, muda o migration_status de DONE para TODO
        """
        logging.info(f"items_to_register: {collection}")
        logging.info(f"items_to_register: {content_type}")
        logging.info(f"items_to_register: {force_update}")

        params = dict(
            collection=collection,
            migrated_data__content_type=content_type,
        )
        if content_type == "article":
            params["xml_status"] = tracker_choices.PROGRESS_STATUS_DONE

        q = Q(migration_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(migration_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                migration_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(
            q,
            **params,
        ).update(migration_status=tracker_choices.PROGRESS_STATUS_TODO)

        # seleciona os registros MigratedData
        count = cls.objects.filter(
            migration_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        ).count()
        logging.info(f"count: {count}")
        return cls.objects.filter(
            migration_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        ).iterator()

    def create_or_update_item(
        self,
        user,
        force_update,
        callable_register_data,
    ):
        try:
            try:
                item_name = self.migrated_data.content_type
            except AttributeError:
                item_name = ""

            operation = self.start(user, f"create or update {item_name}")

            callable_register_data(user, self, force_update)

            operation.finish(
                user,
                completed=(
                    self.migration_status == tracker_choices.PROGRESS_STATUS_DONE
                ),
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation.finish(user, exc_traceback=exc_traceback, exception=e)

    @classmethod
    def items_to_publish_on_qa(cls, user, content_type, force_update=None, params=None):
        """
        BaseProc
        """
        params = params or {}
        params["migrated_data__content_type"] = content_type
        params["migration_status"] = tracker_choices.PROGRESS_STATUS_DONE

        q = Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q = Q(qa_ws_status__isnull=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                qa_ws_status__isnull=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(q, **params).update(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
        )

        items = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        # seleciona itens para publicar em produção
        return items.iterator()

    def publish(self, user, callable_publish, website_kind, api_data):
        operation = self.start(user, f"publication on {website_kind}")
        response = callable_publish(user, self, api_data)
        if response.get("id") or response.get("result") == "OK":
            self.update_publication_stage()
        operation.finish(user, completed=bool(response.get("id")))

    def update_publication_stage(self):
        """
        Estabele o próxim estágio, após ser publicado no QA ou no Público
        """
        if self.public_ws_status == tracker_choices.PROGRESS_STATUS_TODO:
            self.public_ws_status = tracker_choices.PROGRESS_STATUS_DONE
            self.save()
        elif self.qa_ws_status == tracker_choices.PROGRESS_STATUS_TODO:
            self.qa_ws_status = tracker_choices.PROGRESS_STATUS_DONE
            if self.migrated_data:
                self.public_ws_status = tracker_choices.PROGRESS_STATUS_TODO
            self.save()

    @classmethod
    def items_to_publish(
        cls,
        user,
        website_kind,
        content_type,
        collection=None,
        force_update=None,
        params=None,
    ):
        params = params or {}
        if collection:
            params["collection"] = collection

        if website_kind == collection_choices.QA:
            return cls.items_to_publish_on_qa(user, content_type, force_update, params)
        return cls.items_to_publish_on_public(user, content_type, force_update, params)

    @classmethod
    def items_to_publish_on_public(
        cls, user, content_type, force_update=None, params=None
    ):
        params = params or {}
        params["migrated_data__content_type"] = content_type
        params["qa_ws_status"] = tracker_choices.PROGRESS_STATUS_DONE

        q = Q(public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)

        if force_update:
            q |= Q(public_ws_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                public_ws_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(q, **params).update(
            public_ws_status=tracker_choices.PROGRESS_STATUS_TODO
        )

        items = cls.objects.filter(
            public_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        # seleciona itens para publicar em produção
        return items.iterator()


class JournalProc(BaseProc, ClusterableModel):
    """ """

    acron = models.CharField(_("Acronym"), max_length=25, null=True, blank=True)
    title = models.TextField(_("Title"), null=True, blank=True)
    availability_status = models.CharField(
        _("Availability Status"),
        max_length=10,
        null=True,
        blank=True,
        choices=JOURNAL_AVAILABILTY_STATUS,
    )
    journal = models.ForeignKey(Journal, on_delete=models.SET_NULL, null=True)

    ProcResult = JournalProcResult
    base_form_class = ProcAdminModelForm

    panel_proc_result = [
        InlinePanel("journal_proc_result", label=_("Proc result")),
    ]
    MigratedDataClass = MigratedJournal

    edit_handler = TabbedInterface(
        [
            ObjectList(BaseProc.panel_status, heading=_("Status")),
            ObjectList(panel_proc_result, heading=_("Result")),
        ]
    )

    class Meta:
        indexes = [
            models.Index(fields=["acron"]),
        ]

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return IssueProc.objects.filter(
            Q(acron__icontains=search_term)
            | Q(collection__acron__icontains=search_term)
        )

    def autocomplete_label(self):
        return f"{self.collection} {self.acron}"

    def update(
        self,
        user=None,
        migration_status=None,
        journal=None,
        acron=None,
        title=None,
        availability_status=None,
        force_update=None,
    ):
        try:
            self.updated_by = user
            self.journal = journal or self.journal
            self.acron = acron or self.acron
            self.title = title or self.title
            self.availability_status = availability_status or self.availability_status

            self.migration_status = migration_status or self.migration_status
            self.qa_ws_status = tracker_choices.PROGRESS_STATUS_TODO
            self.save()
        except Exception as e:
            raise exceptions.JournalProcUpdateError(
                _("Unable to update journal {} {} {} {}").format(
                    self.collection, acron, type(e), e
                )
            )


################################################
class IssueGetOrCreateError(Exception):
    ...


class IssueProcGetOrCreateError(Exception):
    ...


class IssueEventCreateError(Exception):
    ...


class IssueEventReportCreateError(Exception):
    ...


def modified_date(file_path):
    s = os.stat(file_path)
    return datetime.fromtimestamp(s.st_mtime)


def is_out_of_date(file_path, file_date):
    if not file_date:
        return True
    return file_date.isoformat() < modified_date(file_path).isoformat()


class IssueProc(BaseProc, ClusterableModel):
    """ """

    def __unicode__(self):
        return f"{self.journal_proc} {self.issue_folder}"

    def __str__(self):
        return f"{self.journal_proc} {self.issue_folder}"

    journal_proc = models.ForeignKey(
        JournalProc, on_delete=models.SET_NULL, null=True, blank=True
    )
    issue = models.ForeignKey(Issue, on_delete=models.SET_NULL, null=True)
    issue_folder = models.CharField(
        _("Issue Folder"), max_length=23, null=False, blank=False
    )
    issue_files = models.ManyToManyField(MigratedFile)
    files_status = models.CharField(
        _("Files migration status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )

    # situacao dos registros de documentos
    docs_status = models.CharField(
        _("Document records migration status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )

    MigratedDataClass = MigratedIssue
    base_form_class = ProcAdminModelForm
    ProcResult = IssueProcResult

    panel_status = [
        FieldPanel("migration_status"),
        FieldPanel("files_status"),
        FieldPanel("docs_status"),
        FieldPanel("qa_ws_status"),
        FieldPanel("public_ws_status"),
    ]
    panel_files = [
        AutocompletePanel("issue_files"),
    ]
    panel_proc_result = [
        InlinePanel("issue_proc_result"),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_proc_result, heading=_("Result")),
        ]
    )

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return IssueProc.objects.filter(
            Q(journal_proc__acron__icontains=search_term)
            | Q(issue_folder__icontains=search_term)
        )

    def autocomplete_label(self):
        return f"{self.journal_proc} {self.issue_folder}"

    @property
    def status(self):
        return dict(
            migration_status=self.migration_status,
            docs_status=self.docs_status,
            files_status=self.files_status,
            qa_ws_status=self.qa_ws_status,
            public_ws_status=self.public_ws_status,
        )

    class Meta:
        indexes = [
            models.Index(fields=["issue_folder"]),
            models.Index(fields=["docs_status"]),
            models.Index(fields=["files_status"]),
        ]

    def update(
        self,
        user=None,
        journal_proc=None,
        issue_folder=None,
        issue=None,
        migration_status=None,
        force_update=None,
    ):
        try:
            self.updated_by = user

            self.journal_proc = journal_proc or self.journal_proc
            self.issue_folder = issue_folder or self.issue_folder
            self.issue = issue or self.issue
            self.migration_status = migration_status or self.migration_status
            self.save()
        except Exception as e:
            raise exceptions.IssueProcUpdateError(
                _("Unable to update issue {} {} {} {}").format(
                    journal_proc, issue_folder, type(e), e
                )
            )

    @classmethod
    def files_to_migrate(cls, collection, force_update):
        """
        Muda o status de PROGRESS_STATUS_REPROC para PROGRESS_STATUS_TODO
        E se force_update = True, muda o status de PROGRESS_STATUS_DONE para PROGRESS_STATUS_TODO
        """
        q = Q(files_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(files_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                files_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(
            q,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).update(files_status=tracker_choices.PROGRESS_STATUS_TODO)

        return cls.objects.filter(
            files_status=tracker_choices.PROGRESS_STATUS_TODO,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).iterator()

    def get_files_from_classic_website(
        self, user, force_update, f_get_files_from_classic_website
    ):
        try:
            if (
                self.files_status != tracker_choices.PROGRESS_STATUS_TODO
                and not force_update
            ):
                return
            operation = self.start(user, "get_files_from_classic_website")

            self.files_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            result = f_get_files_from_classic_website(user, self, force_update)
            failures = result.get("failures")
            migrated = result.get("migrated")

            for item in migrated:
                self.issue_files.add(item)

            self.files_status = (
                tracker_choices.PROGRESS_STATUS_PENDING
                if failures
                else tracker_choices.PROGRESS_STATUS_DONE
            )
            self.save()
            operation.finish(
                user,
                completed=(self.files_status == tracker_choices.PROGRESS_STATUS_DONE),
                message="Files",
                detail=failures,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.files_status = tracker_choices.PROGRESS_STATUS_PENDING
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )

    @classmethod
    def docs_to_migrate(cls, collection, force_update):
        """
        Muda o status de PROGRESS_STATUS_REPROC para PROGRESS_STATUS_TODO
        E se force_update = True, muda o status de PROGRESS_STATUS_DONE para PROGRESS_STATUS_TODO
        """
        q = Q(docs_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(docs_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                docs_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(
            q,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).update(docs_status=tracker_choices.PROGRESS_STATUS_TODO)

        return cls.objects.filter(
            docs_status=tracker_choices.PROGRESS_STATUS_TODO,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).iterator()

    def get_article_records_from_classic_website(
        self, user, force_update, f_get_article_records_from_classic_website
    ):
        if self.docs_status != tracker_choices.PROGRESS_STATUS_TODO:
            if not force_update:
                logging.warning(
                    f"No document records will be migrated. {self} "
                    f"docs_status='{self.docs_status}' and force_update=False"
                )
                return
        try:
            operation = self.start(user, "get_article_records_from_classic_website")

            self.docs_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            result = f_get_article_records_from_classic_website(
                user, self, ArticleProc, force_update
            )
            failures = result.get("failures")
            migrated = result.get("migrated")

            self.docs_status = (
                tracker_choices.PROGRESS_STATUS_PENDING
                if failures
                else tracker_choices.PROGRESS_STATUS_DONE
            )
            self.save()
            operation.finish(
                user,
                completed=(self.docs_status == tracker_choices.PROGRESS_STATUS_DONE),
                message="article records",
                detail=failures,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.docs_status = tracker_choices.PROGRESS_STATUS_PENDING
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )

    def find_asset(self, basename, name=None):
        if not name:
            name, ext = os.path.splitext(basename)
        # procura a "imagem" no contexto do "issue"
        return self.issue_files.filter(
            Q(original_name=basename) | Q(original_name__startswith=name + ".")
        ).iterator()


class ArticleEventCreateError(Exception):
    ...


class ArticleEventReportCreateError(Exception):
    ...


class ArticleProc(BaseProc, BasicXMLFile, ClusterableModel):
    # Armazena os IDs dos artigos no contexto de cada coleção
    # serve para conseguir recuperar artigos pelo ID do site clássico
    issue_proc = models.ForeignKey(
        IssueProc, on_delete=models.SET_NULL, null=True, blank=True
    )
    pkg_name = models.TextField(_("Package name"), null=True, blank=True)
    main_lang = models.CharField(
        _("Main lang"),
        max_length=2,
        blank=True,
        null=True,
    )
    # article = models.ForeignKey(
    #     "Article", on_delete=models.SET_NULL, null=True, blank=True
    # )

    sps_pkg = models.ForeignKey(
        SPSPkg, on_delete=models.SET_NULL, null=True, blank=True
    )
    # renditions = models.ManyToManyField("Rendition")
    xml_status = models.CharField(
        _("XML status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
        blank=True,
        null=True,
    )
    sps_pkg_status = models.CharField(
        _("SPS Pkg status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
        blank=True,
        null=True,
    )

    ProcResult = ArticleProcResult
    panel_files = [
        FieldPanel("file"),
        AutocompletePanel("sps_pkg"),
    ]
    panel_status = [
        FieldPanel("xml_status"),
        FieldPanel("sps_pkg_status"),
        FieldPanel("migration_status"),
        FieldPanel("qa_ws_status"),
        FieldPanel("public_ws_status"),
    ]
    # panel_events = [
    #     AutocompletePanel("events"),
    # ]
    panel_proc_result = [
        InlinePanel("article_proc_result"),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_files, heading=_("Files")),
            ObjectList(panel_proc_result, heading=_("Result")),
        ]
    )

    MigratedDataClass = MigratedArticle

    class Meta:
        indexes = [
            models.Index(fields=["pkg_name"]),
            models.Index(fields=["xml_status"]),
            models.Index(fields=["sps_pkg_status"]),
        ]

    @property
    def identification(self):
        return f"{self.issue_proc} {self.pkg_name}"

    def __str__(self):
        return self.identification

    def autocomplete_label(self):
        return self.identification

    def update(
        self,
        issue_proc=None,
        pkg_name=None,
        migration_status=None,
        user=None,
        main_lang=None,
        force_update=None,
    ):
        try:
            self.updated_by = user
            self.issue_proc = issue_proc
            self.pkg_name = pkg_name
            self.main_lang = main_lang
            self.migration_status = migration_status or self.migration_status
            self.save()

        except Exception as e:
            raise exceptions.ArticleProcUpdateError(
                _("Unable to update article_proc{} {} {} {}").format(
                    issue_proc, pkg_name, type(e), e
                )
            )

    def get_xml(self, user, htmlxml, body_and_back_xml):
        try:
            operation = self.start(user, "get xml")
            self.xml_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            if htmlxml:
                self.html_to_xml(user, htmlxml, body_and_back_xml)
            else:
                self.add_xml(user, source_path=self.migrated_xml.file.path)

            operation.finish(user, completed=bool(self.file.path))

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.xml_status = tracker_choices.PROGRESS_STATUS_PENDING
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )

    def html_to_xml(self, user, htmlxml, body_and_back_xml):

        operation = self.start(user, "generate xml from html")

        xml_content = htmlxml.html_to_xml(user, body_and_back_xml)
        self.add_xml(user=user, xml_content=xml_content)
        htmlxml.generate_report(user, xml_content)

        operation.finish(
            user,
            completed=(htmlxml.html2xml_status == tracker_choices.PROGRESS_STATUS_DONE),
        )

    @classmethod
    def items_to_get_xml(
        cls,
        collection_acron=None,
        journal_acron=None,
        publication_year=None,
        issue_folder=None,
        force_update=None,
    ):
        """
        Muda o status de REPROC para TODO
        E se force_update = True, muda o status de DONE para TODO
        """
        params = {}
        params["issue_proc__files_status"] = tracker_choices.PROGRESS_STATUS_DONE
        params["issue_proc__docs_status"] = tracker_choices.PROGRESS_STATUS_DONE

        if collection_acron:
            params["collection__acron"] = collection_acron
        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder

        q = Q(xml_status=tracker_choices.PROGRESS_STATUS_REPROC)

        if force_update:
            q |= Q(xml_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                xml_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(
            q,
            **params,
        ).update(
            xml_status=tracker_choices.PROGRESS_STATUS_TODO,
        )

        return cls.objects.filter(
            xml_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        ).iterator()

    @classmethod
    def items_to_build_sps_pkg(
        cls,
        collection_acron,
        journal_acron,
        publication_year,
        issue_folder,
        force_update,
    ):
        """
        Muda o status de REPROC para TODO
        E se force_update = True, muda o status de DONE para TODO
        """
        params = {}
        if collection_acron:
            params["collection__acron"] = collection_acron
        if journal_acron:
            params["issue_proc__journal_proc__acron"] = journal_acron
        if publication_year:
            params["issue_proc__issue__publication_year"] = publication_year
        if issue_folder:
            params["issue_proc__issue_folder"] = issue_folder

        q = Q(sps_pkg_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(sps_pkg_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                sps_pkg_status=tracker_choices.PROGRESS_STATUS_PENDING
            )
        cls.objects.filter(
            q,
            xml_status=tracker_choices.PROGRESS_STATUS_DONE,
            **params,
        ).update(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
        )
        return cls.objects.filter(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
            xml_status=tracker_choices.PROGRESS_STATUS_DONE,
            **params,
        ).iterator()

    @classmethod
    def items_to_publish_on_qa(cls, user, content_type, force_update=None, params=None):
        """
        ArtcleProc
        """
        params = params or {}
        params["migrated_data__content_type"] = content_type
        params["migration_status"] = tracker_choices.PROGRESS_STATUS_DONE
        params["sps_pkg__isnull"] = False

        q = Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                qa_ws_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(q, **params,).update(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO,
        )
        items = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        return items.iterator()

    @classmethod
    def items_to_publish_on_public(
        cls, user, content_type, force_update=None, params=None
    ):
        params = params or {}
        params["migrated_data__content_type"] = content_type
        params["sps_pkg__isnull"] = False
        params["qa_ws_status"] = tracker_choices.PROGRESS_STATUS_DONE

        q = Q(public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= Q(public_ws_status=tracker_choices.PROGRESS_STATUS_DONE) | Q(
                public_ws_status=tracker_choices.PROGRESS_STATUS_PENDING
            )

        cls.objects.filter(q, **params,).update(
            public_ws_status=tracker_choices.PROGRESS_STATUS_TODO,
        )
        items = cls.objects.filter(
            public_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        return items.iterator()

    @property
    def renditions(self):
        return self.issue_proc.issue_files.filter(
            pkg_name=self.pkg_name, component_type="rendition"
        ).iterator()

    def add_xml(self, user, source_path=None, xml_content=None):
        if source_path:
            with open(source_path) as fp:
                xml_content = fp.read()
        if xml_content:
            self.save_file(self.pkg_name + ".xml", xml_content)
            self.xml_status = tracker_choices.PROGRESS_STATUS_DONE
            self.save()

    @property
    def migrated_xml(self):
        for item in self.issue_proc.issue_files.filter(
            pkg_name=self.pkg_name, component_type="xml"
        ).iterator():
            return item

    @property
    def translation_files(self):
        logging.info(
            dict(
                component_type="html",
                pkg_name=self.pkg_name,
            )
        )
        items = self.issue_proc.issue_files.filter(
            component_type="html",
            pkg_name=self.pkg_name,
        )
        count = items.count()
        logging.info(count)
        if count > 0:
            for item in self.issue_proc.issue_files.filter(
                component_type="html",
                pkg_name=self.pkg_name,
            ):
                logging.info(f"{self.pkg_name} {item.part} {item.original_path}")
        return self.issue_proc.issue_files.filter(
            component_type="html",
            pkg_name=self.pkg_name,
        )

    @property
    def translations(self):
        """
        {
            "pt": {1: "", 2: ""},
            "es": {1: "", 2: ""},
        }
        """
        part = {"1": "before references", "2": "after references"}
        xhtmls = {}
        items = self.translation_files
        for item in items.iterator():
            hc = HTMLContent(item.text)
            lang = item.lang
            xhtmls.setdefault(lang, {})
            xhtmls[lang][part[item.part]] = hc.content
            logging.info(f"{lang} {part[item.part]}")
        return xhtmls

    def build_sps_package(self, user, output_folder, components, texts):
        """
        A partir do XML original ou gerado a partir do HTML, e
        dos ativos digitais, todos registrados em MigratedFile,
        cria o zip com nome no padrão SPS (ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE) e
        o armazena em SPSPkg.not_optimised_zip_file.
        Neste momento o XML não contém pid v3.
        """
        # gera nome de pacote padrão SPS ISSN-ACRON-VOL-NUM-SUPPL-ARTICLE
        xml_with_pre = self.xml_with_pre
        sps_pkg_name = xml_with_pre.sps_pkg_name

        sps_pkg_zip_path = os.path.join(output_folder, f"{sps_pkg_name}.zip")

        # cria pacote zip
        with ZipFile(sps_pkg_zip_path, "w") as zf:

            # A partir do XML, obtém os nomes dos arquivos dos ativos digitais
            self._build_sps_package_add_assets(
                zf, user, xml_with_pre, sps_pkg_name, components
            )

            # add renditions (pdf) to zip
            result = self._build_sps_package_add_renditions(
                zf, user, xml_with_pre, sps_pkg_name, components
            )
            texts.update(result)

            # adiciona XML em zip
            self._build_sps_package_add_xml(
                zf, user, xml_with_pre, sps_pkg_name, components
            )

        return sps_pkg_zip_path

    def _build_sps_package_add_renditions(
        self, zf, user, xml_with_pre, sps_pkg_name, components
    ):
        xml = ArticleAndSubArticles(xml_with_pre.xmltree)
        xml_langs = []
        for item in xml.data:
            if item.get("lang"):
                xml_langs.append(item.get("lang"))

        pdf_langs = []

        for rendition in self.renditions:
            try:
                if rendition.lang:
                    sps_filename = f"{sps_pkg_name}-{rendition.lang}.pdf"
                else:
                    sps_filename = f"{sps_pkg_name}.pdf"
                pdf_langs.append(rendition.lang or xml.main_lang)

                zf.write(rendition.file.path, arcname=sps_filename)

                components[sps_filename] = {
                    "lang": rendition.lang,
                    "legacy_uri": rendition.original_href,
                    "component_type": "rendition",
                }
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                components[rendition.original_name] = {
                    "failures": format_traceback(exc_traceback),
                }
        html_langs = list(self.translations.keys())
        try:
            if self.migrated_data.n_paragraphs:
                html_langs.append(self.main_lang)
        except Exception as e:
            pass

        return {
            "xml_langs": xml_langs,
            "pdf_langs": pdf_langs,
            "html_langs": html_langs,
        }

    def _build_sps_package_add_assets(
        self, zf, user, xml_with_pre, sps_pkg_name, components
    ):
        replacements = {}
        subdir = os.path.join(
            self.issue_proc.journal_proc.acron,
            self.issue_proc.issue_folder,
        )
        xml_assets = ArticleAssets(xml_with_pre.xmltree)
        for xml_graphic in xml_assets.items:
            try:
                if replacements.get(xml_graphic.xlink_href):
                    continue

                basename = os.path.basename(xml_graphic.xlink_href)
                name, ext = os.path.splitext(basename)

                found = False

                # procura a "imagem" no contexto do "issue"
                for asset in self.issue_proc.find_asset(basename, name):
                    found = True
                    self._build_sps_package_add_asset(
                        zf,
                        asset,
                        xml_graphic,
                        replacements,
                        components,
                        user,
                        sps_pkg_name,
                    )
                if not found:
                    # procura a "imagem" no contexto da coleção
                    for asset in MigratedFile.find(
                        collection=self.collection,
                        xlink_href=xml_graphic.xlink_href,
                        subidr=subdir,
                    ):
                        found = True
                        self._build_sps_package_add_asset(
                            zf,
                            asset,
                            xml_graphic,
                            replacements,
                            components,
                            user,
                            sps_pkg_name,
                        )

                if not found:
                    components[xml_graphic.xlink_href] = {
                        "failures": "Not found",
                    }

            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                components[xml_graphic.xlink_href] = {
                    "failures": format_traceback(exc_traceback),
                }
        xml_assets.replace_names(replacements)

    def _build_sps_package_add_asset(
        self, zf, asset, xml_graphic, replacements, components, user, sps_pkg_name
    ):
        try:
            # obtém o nome do arquivo no padrão sps
            sps_filename = xml_graphic.name_canonical(sps_pkg_name)

            # indica a troca de href original para o padrão SPS
            replacements[xml_graphic.xlink_href] = sps_filename

            # adiciona arquivo ao zip
            zf.write(asset.file.path, arcname=sps_filename)

            component_type = (
                "supplementary-material"
                if xml_graphic.is_supplementary_material
                else "asset"
            )
            components[sps_filename] = {
                "xml_elem_id": xml_graphic.id,
                "legacy_uri": asset.original_href,
                "component_type": component_type,
            }
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            components[xml_graphic.xlink_href] = {
                "failures": format_traceback(exc_traceback),
            }

    def _build_sps_package_add_xml(
        self, zf, user, xml_with_pre, sps_pkg_name, components
    ):
        try:
            sps_xml_name = sps_pkg_name + ".xml"
            zf.writestr(sps_xml_name, xml_with_pre.tostring())
            components[sps_xml_name] = {"component_type": "xml"}
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            components[sps_xml_name] = {
                "component_type": "xml",
                "failures": format_traceback(exc_traceback),
            }

    def generate_sps_package(
        self,
        user,
        body_and_back_xml=False,
        html_to_xml=False,
    ):
        try:
            operation = self.start(user, "generate_sps_package")

            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            components = {}
            texts = {}
            with TemporaryDirectory() as output_folder:
                sps_pkg_zip_path = self.build_sps_package(
                    user,
                    output_folder,
                    components,
                    texts,
                )

                # FIXME assumindo que isso será executado somente na migração
                # verificar se este código pode ser aproveitado pelo fluxo
                # de ingresso, se sim, ajustar os valores dos parâmetros
                # origin e is_published
                self.sps_pkg = SPSPkg.create_or_update(
                    user,
                    sps_pkg_zip_path,
                    origin=package_choices.PKG_ORIGIN_MIGRATION,
                    is_public=True,
                    components=components,
                    texts=texts,
                    article_proc=self,
                )

            detail = dict(
                texts=texts,
                components=components,
                is_pid_provider_synchronized=self.sps_pkg.is_pid_provider_synchronized,
            )
            if (
                self.sps_pkg.is_pid_provider_synchronized
                and self.sps_pkg.valid_texts
                and self.sps_pkg.valid_components
            ):
                self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DONE
                self.save()
                operation.finish(user, completed=True, detail=detail)
            else:
                self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_PENDING
                self.save()
                operation.finish(
                    user, completed=False, detail=detail
                )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_PENDING
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )

    @property
    def journal_proc(self):
        return self.issue_proc.journal_proc

    @property
    def article(self):
        if self.sps_pkg is not None:
            return Article.objects.get(sps_pkg=self.sps_pkg)
