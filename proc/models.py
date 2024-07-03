import json
import logging
import os
import sys
from datetime import datetime
from tempfile import TemporaryDirectory

from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
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
from migration.controller import (
    PkgZipBuilder,
    XMLVersionXmlWithPreError,
    get_migrated_xml_with_pre,
)
from migration.models import (
    MigratedArticle,
    MigratedData,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)
from package import choices as package_choices
from package.models import SPSPkg
from proc import exceptions
from proc.forms import ProcAdminModelForm
from tracker import choices as tracker_choices
from tracker.models import Event, UnexpectedEvent, format_traceback


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
        FieldPanel("name", read_only=True),
        FieldPanel("created", read_only=True),
        FieldPanel("updated", read_only=True),
        FieldPanel("completed", read_only=True),
        FieldPanel("detail", read_only=True),
    ]

    class Meta:
        # isso faz com que em InlinePanel mostre do mais recente para o mais antigo
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} {self.started} {self.finished} {self.completed}"

    @property
    def data(self):
        return dict(
            name=self.name,
            completed=self.completed,
            event=self.event and self.event.data,
            detail=self.detail,
            created=self.created.isoformat(),
        )

    @property
    def started(self):
        return self.created and self.created.isoformat() or ""

    @property
    def finished(self):
        return self.updated and self.updated.isoformat() or ""

    @classmethod
    def create(cls, user, proc, name):
        for item in cls.objects.filter(proc=proc, name=name).order_by("created"):
            # obtém o primeiro ocorrência de proc e name

            # obtém todos os ítens criados após este evento
            rows = []
            for row in (
                cls.objects.filter(proc=proc, created__gte=item.created)
                .order_by("created")
                .iterator()
            ):
                rows.append(row.data)

            try:
                # converte para json
                file_content = json.dumps(rows)
                file_extension = ".json"
            except Exception as e:
                # caso não seja serializável, converte para str
                file_content = str(rows)
                file_extension = ".txt"
                logging.info(proc.pid)
                logging.exception(e)

            try:
                report_date = item.created.isoformat()
                # cria um arquivo com o conteúdo
                ProcReport.create_or_update(
                    user,
                    proc,
                    name,
                    report_date,
                    file_content,
                    file_extension,
                )
                # apaga todas as ocorrências que foram armazenadas no arquivo
                cls.objects.filter(proc=proc, created__gte=item.created).delete()
            except Exception as e:
                logging.info(proc.pid)
                logging.exception(e)
            break

        obj = cls()
        obj.proc = proc
        obj.name = name
        obj.creator = user
        obj.save()
        return obj

    @classmethod
    def start(
        cls,
        user,
        proc,
        name=None,
    ):
        try:
            return cls.create(user, proc, name)
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
            if exception:
                logging.exception(exception)
            if not message_type:
                if not completed:
                    message_type = "ERROR"

            detail = detail or {}
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
            try:
                json.dumps(detail)
                self.detail = detail
            except TypeError:
                self.detail = str(detail)
            self.completed = completed
            self.updated_by = user
            self.save()
            return self
        except Exception as exc:
            logging.exception(exc)
            data = dict(
                completed=completed,
                exception=exception,
                message_type=message_type,
                message=message,
                exc_traceback=exc_traceback,
                detail=detail,
            )
            error = []
            for k, v in data.items():
                try:
                    json.dumps(v)
                    error.append(k)
                except TypeError:
                    pass

            raise OperationFinishError(
                f"Unable to finish ({self.name}). Input: {error}. EXCEPTION: {type(exc)} {exc}"
            )


def proc_report_directory_path(instance, filename):
    try:
        subdir = instance.directory_path
        YYYY = instance.report_date[:4]
        return f"archive/{subdir}/proc/{YYYY}/{filename}"
    except AttributeError:
        return f"archive/{filename}"


class ProcReport(CommonControlField):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)
    task_name = models.CharField(
        _("Procedure name"), max_length=32, null=True, blank=True
    )
    file = models.FileField(upload_to=proc_report_directory_path, null=True, blank=True)
    report_date = models.CharField(
        _("Identification"), max_length=34, null=True, blank=True
    )
    item_type = models.CharField(_("Item type"), max_length=16, null=True, blank=True)

    panel_files = [
        FieldPanel("task_name", read_only=True),
        FieldPanel("report_date", read_only=True),
        FieldPanel("file", read_only=True),
    ]

    def __str__(self):
        return f"{self.collection.acron} {self.pid} {self.task_name} {self.report_date}"

    class Meta:
        ordering = ["-created"]

        verbose_name = _("Processing report")
        verbose_name_plural = _("Processing reports")
        indexes = [
            models.Index(fields=["item_type"]),
            models.Index(fields=["pid"]),
            models.Index(fields=["task_name"]),
            models.Index(fields=["report_date"]),
        ]

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return ProcReport.objects.filter(
            Q(pid__icontains=search_term)
            | Q(collection__acron__icontains=search_term)
            | Q(collection__name__icontains=search_term)
            | Q(task_name__icontains=search_term)
            | Q(report_date__icontains=search_term)
        )

    def autocomplete_label(self):
        return str(self)

    def save_file(self, name, content):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        try:
            self.file.save(name, ContentFile(content))
        except Exception as e:
            raise Exception(f"Unable to save {name}. Exception: {e}")

    @classmethod
    def get(cls, proc=None, task_name=None, report_date=None):
        if proc and task_name and report_date:
            try:
                return cls.objects.get(
                    collection=proc.collection,
                    pid=proc.pid,
                    task_name=task_name,
                    report_date=report_date,
                )
            except cls.MultipleObjectsReturned:
                return cls.objects.filter(
                    collection=proc.collection,
                    pid=proc.pid,
                    task_name=task_name,
                    report_date=report_date,
                ).first()
        raise ValueError("ProcReport.get requires proc and task_name and report_date")

    @staticmethod
    def get_item_type(pid):
        if len(pid) == 23:
            return "article"
        if len(pid) == 9:
            return "journal"
        return "issue"

    @classmethod
    def create(cls, user, proc, task_name, report_date, file_content, file_extension):
        if proc and task_name and report_date and file_content and file_extension:
            try:
                obj = cls()
                obj.collection = proc.collection
                obj.pid = proc.pid
                obj.task_name = task_name
                obj.item_type = ProcReport.get_item_type(proc.pid)
                obj.report_date = report_date
                obj.creator = user
                obj.save()
                obj.save_file(f"{task_name}{file_extension}", file_content)
                return obj
            except IntegrityError:
                return cls.get(proc, task_name, report_date)
        raise ValueError(
            "ProcReport.create requires proc and task_name and report_date and file_content and file_extension"
        )

    @classmethod
    def create_or_update(
        cls, user, proc, task_name, report_date, file_content, file_extension
    ):
        try:
            obj = cls.get(proc=proc, task_name=task_name, report_date=report_date)
            obj.updated_by = user
            obj.task_name = task_name or obj.task_name
            obj.report_date = report_date or obj.report_date
            obj.save()
            obj.save_file(f"{task_name}{file_extension}", file_content)
        except cls.DoesNotExist:
            obj = cls.create(
                user, proc, task_name, report_date, file_content, file_extension
            )
        return obj

    @property
    def directory_path(self):
        pid = self.pid
        if len(self.pid) == 23:
            pid = self.pid[1:]
        paths = [self.collection.acron, pid[:9], pid[9:13], pid[13:17], pid[17:]]
        paths = [path for path in paths if path]
        return os.path.join(*paths)


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
        ordering = ["-updated"]

        indexes = [
            models.Index(fields=["pid"]),
        ]

    # MigratedDataClass = MigratedData
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
            ObjectList(panel_proc_result, heading=_("Events newest to oldest")),
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
                detail=obj.migrated_data,
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
        params = dict(
            collection=collection,
            migrated_data__content_type=content_type,
        )
        if content_type == "article":
            params["sps_pkg__pid_v3__isnull"] = False
        q = Q(migration_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= (
                Q(migration_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(migration_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(migration_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
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

            registered = callable_register_data(user, self, force_update)
            operation.finish(
                user,
                completed=(
                    self.migration_status == tracker_choices.PROGRESS_STATUS_DONE
                ),
                detail=registered and registered.data,
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
        if content_type == "article":
            params["sps_pkg__pid_v3__isnull"] = False

        q = Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q = (
                Q(qa_ws_status__isnull=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(qa_ws_status__isnull=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(qa_ws_status__isnull=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(q, **params).update(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
        )

        count = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        ).count()
        logging.info(f"It will publish: {count}")
        items = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        # seleciona itens para publicar em produção
        return items.iterator()

    def publish(self, user, callable_publish, website_kind, api_data):
        operation = self.start(user, f"publication on {website_kind}")
        response = callable_publish(user, self, api_data)
        logging.info(f"Publish response: {response}")
        completed = bool(response.get("result") == "OK")
        if completed:
            self.update_publication_stage()
        operation.finish(user, completed=completed, detail=response)

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
        if content_type == "article":
            params["sps_pkg_status"] = False
            params["sps_pkg__pid_v3__isnull"] = False
            params["sps_pkg__registered_in_core"] = True

        q = Q(public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC)

        if force_update:
            q |= (
                Q(public_ws_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(public_ws_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(public_ws_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
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

    migrated_data = models.ForeignKey(
        MigratedJournal, on_delete=models.SET_NULL, null=True, blank=True
    )

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
        InlinePanel("journal_proc_result", label=_("Event")),
    ]
    MigratedDataClass = MigratedJournal

    edit_handler = TabbedInterface(
        [
            ObjectList(BaseProc.panel_status, heading=_("Status")),
            ObjectList(panel_proc_result, heading=_("Events newest to oldest")),
        ]
    )

    class Meta:
        ordering = ["-updated"]
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

    migrated_data = models.ForeignKey(
        MigratedIssue, on_delete=models.SET_NULL, null=True, blank=True
    )

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
        InlinePanel("issue_proc_result", label=_("Event")),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_proc_result, heading=_("Events newest to oldest")),
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
        ordering = ["-updated"]
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
    def files_to_migrate(
        cls, collection, journal_acron, publication_year, force_update
    ):
        """
        Muda o status de PROGRESS_STATUS_REPROC para PROGRESS_STATUS_TODO
        E se force_update = True, muda o status de PROGRESS_STATUS_DONE para PROGRESS_STATUS_TODO
        """
        q = Q(files_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= (
                Q(files_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(files_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(files_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(
            q,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).update(files_status=tracker_choices.PROGRESS_STATUS_TODO)

        params = {}
        if publication_year:
            params["issue__publication_year"] = publication_year
        if journal_acron:
            params["journal_proc__acron"] = journal_acron

        return cls.objects.filter(
            files_status=tracker_choices.PROGRESS_STATUS_TODO,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            **params,
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

            result = None
            result = f_get_files_from_classic_website(user, self, force_update)

            migrated = result.pop("migrated") or []

            result["migrated"] = []
            for item in migrated:
                self.issue_files.add(item)
                result["migrated"].append({"file": item.original_path})

            self.files_status = (
                tracker_choices.PROGRESS_STATUS_PENDING
                if result["failures"]
                else tracker_choices.PROGRESS_STATUS_DONE
            )
            self.save()
            operation.finish(
                user,
                completed=(self.files_status == tracker_choices.PROGRESS_STATUS_DONE),
                message="Files",
                detail=result,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.files_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail=result,
            )

    @classmethod
    def docs_to_migrate(cls, collection, journal_acron, publication_year, force_update):
        """
        Muda o status de PROGRESS_STATUS_REPROC para PROGRESS_STATUS_TODO
        E se force_update = True, muda o status de PROGRESS_STATUS_DONE para PROGRESS_STATUS_TODO
        """
        q = Q(docs_status=tracker_choices.PROGRESS_STATUS_REPROC)
        if force_update:
            q |= (
                Q(docs_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(docs_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(docs_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(
            q,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
        ).update(docs_status=tracker_choices.PROGRESS_STATUS_TODO)

        params = {}
        if publication_year:
            params["issue__publication_year"] = publication_year
        if journal_acron:
            params["journal_proc__acron"] = journal_acron

        return cls.objects.filter(
            docs_status=tracker_choices.PROGRESS_STATUS_TODO,
            collection=collection,
            migration_status=tracker_choices.PROGRESS_STATUS_DONE,
            **params,
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
            result = None
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
                detail=result,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.docs_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail=result,
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


class ArticleProc(BaseProc, ClusterableModel):
    # Armazena os IDs dos artigos no contexto de cada coleção
    # serve para conseguir recuperar artigos pelo ID do site clássico
    migrated_data = models.ForeignKey(
        MigratedArticle, on_delete=models.SET_NULL, null=True, blank=True
    )
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
        FieldPanel("pkg_name", read_only=True),
        AutocompletePanel("sps_pkg", read_only=True),
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
        InlinePanel("article_proc_result", label=_("Event")),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_files, heading=_("Files")),
            ObjectList(panel_proc_result, heading=_("Events newest to oldest")),
        ]
    )

    MigratedDataClass = MigratedArticle

    class Meta:
        ordering = ["-updated"]
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
                htmlxml.html_to_xml(user, self, body_and_back_xml)

            xml = get_migrated_xml_with_pre(self)

            if xml:
                self.xml_status = tracker_choices.PROGRESS_STATUS_DONE
            else:
                self.xml_status = tracker_choices.PROGRESS_STATUS_REPROC
            self.save()

            operation.finish(
                user,
                completed=self.xml_status == tracker_choices.PROGRESS_STATUS_DONE,
                detail=xml and xml.data,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.xml_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
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
            q |= (
                Q(xml_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(xml_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(xml_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(q, **params).update(
            xml_status=tracker_choices.PROGRESS_STATUS_TODO,
        )

        count = cls.objects.filter(
            xml_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        ).count()
        logging.info(f"items_to_get_xml: {count} {params}")
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
        params["xml_status"] = tracker_choices.PROGRESS_STATUS_DONE
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
            q |= (
                Q(sps_pkg_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(sps_pkg_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(sps_pkg_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )
        cls.objects.filter(q, **params,).update(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
        )
        return cls.objects.filter(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        ).iterator()

    @property
    def renditions(self):
        return self.issue_proc.issue_files.filter(
            pkg_name=self.pkg_name, component_type="rendition"
        ).iterator()

    @property
    def migrated_xml(self):
        for item in self.issue_proc.issue_files.filter(
            pkg_name=self.pkg_name, component_type="xml"
        ).iterator():
            return item

    @property
    def translation_files(self):
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
        return xhtmls

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

            with TemporaryDirectory() as output_folder:

                xml_with_pre = get_migrated_xml_with_pre(self)

                builder = PkgZipBuilder(xml_with_pre)
                sps_pkg_zip_path = builder.build_sps_package(
                    output_folder,
                    renditions=list(self.renditions),
                    translations=self.translations,
                    main_paragraphs_lang=self.migrated_data.n_paragraphs
                    and self.main_lang,
                    issue_proc=self.issue_proc,
                )

                # FIXME assumindo que isso será executado somente na migração
                # verificar se este código pode ser aproveitado pelo fluxo
                # de ingresso, se sim, ajustar os valores dos parâmetros
                # origin e is_published

                self.fix_pid_v2(user)

                self.sps_pkg = SPSPkg.create_or_update(
                    user,
                    sps_pkg_zip_path,
                    origin=package_choices.PKG_ORIGIN_MIGRATION,
                    is_public=True,
                    original_pkg_components=builder.components,
                    texts=builder.texts,
                    article_proc=self,
                )
            self.update_sps_pkg_status()
            operation.finish(
                user,
                completed=bool(self.sps_pkg and self.sps_pkg.is_complete),
                detail=self.sps_pkg and self.sps_pkg.data,
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail=self.sps_pkg and self.sps_pkg.data,
            )

    def fix_pid_v2(self, user):
        if self.sps_pkg:
            self.sps_pkg.fix_pid_v2(user, correct_pid_v2=self.migrated_data.pid)

    def update_sps_pkg_status(self):
        if not self.sps_pkg:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_REPROC
        elif self.sps_pkg.is_complete:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DONE
        elif not self.sps_pkg.registered_in_core:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_REPROC
        elif not self.sps_pkg.valid_components:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_REPROC
        else:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_PENDING
        self.save()

    @property
    def journal_proc(self):
        return self.issue_proc.journal_proc

    @property
    def article(self):
        if self.sps_pkg is not None:
            return Article.objects.get(sps_pkg=self.sps_pkg)

    def synchronize(self, user):
        try:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            operation = self.start(user, "synchronize to core")
            self.sps_pkg.synchronize(user, self)
            operation.finish(user, completed=self.sps_pkg.registered_in_core)

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )
