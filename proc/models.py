import json
import logging
import os
import sys
from datetime import datetime
from tempfile import TemporaryDirectory

from django import forms
from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Q, Count
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
from htmlxml.models import HTMLXML
from issue.models import Issue
from journal.choices import JOURNAL_AVAILABILTY_STATUS
from journal.models import Journal
from migration.controller import (
    PkgZipBuilder,
    XMLVersionXmlWithPreError,
    create_or_update_article,
    get_migrated_xml_with_pre,
)
from migration.models import (
    JournalAcronIdFile,
    IdFileRecord,
    MigratedArticle,
    MigratedData,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)
from package import choices as package_choices
from package.models import SPSPkg
from proc import exceptions
from proc.forms import ProcAdminModelForm, IssueProcAdminModelForm
from pid_provider.models import PidProviderXML
from publication.api.publication import get_api_data
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback


class Operation(CommonControlField):

    name = models.CharField(
        _("Name"),
        max_length=64,
        null=True,
        blank=True,
    )
    completed = models.BooleanField(null=True, blank=True, default=False)
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
        name = name[:64]
        cls.exclude_events(user, proc, name)
        obj = cls()
        obj.proc = proc
        obj.name = name
        obj.creator = user
        obj.save()
        return obj
        # try:
        #     return cls.objects.get(proc=proc, name=name)
        # except cls.MultipleObjectsReturned:
        #     return cls.objects.filter(proc=proc, name=name).order_by("-created").first()
        # except cls.DoesNotExist:
        #     obj = cls()
        #     obj.proc = proc
        #     obj.name = name
        #     obj.creator = user
        #     obj.save()
        #     return obj

    @classmethod
    def exclude_events(cls, user, proc, name):
        # apaga todas as ocorrências que foram armazenadas no arquivo
        try:
            cls.objects.filter(proc=proc, name=name).delete()
        except Exception as e:
            pass

    @classmethod
    def start(
        cls,
        user,
        proc,
        name=None,
    ):
        return cls.create(user, proc, name)

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
        detail = detail or {}
        if exception:
            detail["exception_message"] = str(exception)
            detail["exception_type"] = str(type(exception))
        if exc_traceback:
            detail["traceback"] = str(format_traceback(exc_traceback))
        if message_type:
            detail["message_type"] = message_type
        if message:
            detail["message"] = message

        try:
            json.dumps(detail)
        except Exception as exc_detail:
            detail = str(detail)

        self.detail = detail
        self.completed = completed
        self.updated_by = user
        self.save()


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
        _("Procedure name"), max_length=64, null=True, blank=True
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
        self.file.save(name, ContentFile(content))

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
        _("Migration Status"),
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

    panel_data = [
        FieldPanel("collection"),
        FieldPanel("pid"),
    ]

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
            ObjectList(panel_proc_result, heading=_("Events")),
        ]
    )

    def __unicode__(self):
        return f"{self.collection} {self.pid}"

    def __str__(self):
        return f"{self.collection} {self.pid}"

    def set_status(self):
        if self.migration_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.qa_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        if self.qa_ws_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.public_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        self.save()

    @classmethod
    def get(cls, collection, pid):
        if collection and pid:
            return cls.objects.get(collection=collection, pid=pid)
        raise ValueError("BaseProc.get requires collection and pid")

    @classmethod
    def get_or_create(cls, user, collection, pid, **kwargs):
        if collection and pid:
            try:
                return cls.get(collection, pid)
            except cls.DoesNotExist:
                return cls.create(user, collection, pid)
        raise ValueError(
            f"{cls}.get_or_create requires collection ({collection}) and pid ({pid})"
        )

    @classmethod
    def create(cls, user, collection, pid):
        try:
            obj = cls()
            obj.creator = user
            obj.collection = collection
            obj.pid = pid
            obj.public_ws_status = tracker_choices.PROGRESS_STATUS_TODO
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(collection, pid)

    def start(self, user, name):
        # self.save()
        # operation = Operation.start(user, name)
        # self.operations.add(operation)
        # return operation
        return self.ProcResult.start(user, self, name)

    @property
    def data(self):
        return {
            "migration_status": self.migration_status,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
        }

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

            operation = obj.start(user, f"get data from classic website {pid}")
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
    def register_pid(
        cls,
        user,
        collection,
        pid,
        force_update=False,
    ):
        try:
            operation = None
            obj = cls.get_or_create(user, collection, pid)
            operation = obj.start(user, f"register {pid}")
            if obj.migrated_data and obj.migrated_data.data:
                operation.finish(user, completed=False, message="migrated")
            else:
                obj.migration_status = tracker_choices.PROGRESS_STATUS_PENDING
                obj.save()
                operation.finish(user, completed=True, message="to be migrated")
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
                        "task": "proc.BaseProc.register_pid",
                        "username": user.username,
                        "collection": collection.acron,
                        "pid": pid,
                    },
                )

    @classmethod
    def get_queryset_to_process(cls, STATUS):
        return (
            Q(migration_status__in=STATUS)
            | Q(qa_ws_status__in=STATUS)
            | Q(public_ws_status__in=STATUS)
        )

    @classmethod
    def items_to_process_info(cls, items):
        return items.values(
            "migration_status", "qa_ws_status", "public_ws_status"
        ).annotate(total=Count("id"))

    @classmethod
    def items_to_process(cls, collection, content_type, params, force_update):
        """
        BaseProc.items_to_process
        """
        STATUS = tracker_choices.PROGRESS_STATUS_REGULAR_TODO
        if force_update:
            STATUS = tracker_choices.PROGRESS_STATUS_FORCE_UPDATE

        if params is None:
            params = {}

        q = cls.get_queryset_to_process(STATUS)

        return cls.objects.filter(
            q,
            collection=collection,
            **params,
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
        return cls.objects.filter(
            migration_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        )

    def create_or_update_item(
        self,
        user,
        force_update,
        callable_register_data,
        **kwargs,
    ):
        try:
            operation = None
            try:
                item_name = self.migrated_data.content_type
            except AttributeError:
                item_name = ""
            operation = self.start(user, f"create or update {item_name}")
            registered = callable_register_data(user, self, force_update, **kwargs)
            operation.finish(
                user,
                completed=(
                    self.migration_status == tracker_choices.PROGRESS_STATUS_DONE
                ),
                detail=registered and registered.data,
            )
            return registered
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.migration_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            if operation:
                operation.finish(user, exc_traceback=exc_traceback, exception=e)
            else:
                params = dict(
                    user=user,
                    force_update=force_update,
                    callable_register_data=callable_register_data,
                )
                UnexpectedEvent.create(
                    e=e,
                    exc_traceback=exc_traceback,
                    detail=str(params),
                )

    @classmethod
    def items_to_publish_on_qa(cls, content_type, force_update=None, params=None):
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
                Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(q, **params).update(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
        )

        count = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        ).count()
        logging.info(f"It will publish: {count} {params}")
        items = cls.objects.filter(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO, **params
        )
        # seleciona itens para publicar em produção
        return items

    def publish(
        self,
        user,
        callable_publish,
        website_kind=None,
        api_data=None,
        force_update=None,
        content_type=None,
    ):
        try:
            website_kind = website_kind or collection_choices.QA
            detail = {
                "website_kind": website_kind,
                "force_update": force_update,
            }
            resp = {}
            operation = None
            operation = self.start(
                user, f"publish {content_type} {self} on {website_kind}"
            )

            if not content_type:
                try:
                    content_type = self.migrated_data.content_type
                except AttributeError:
                    raise Exception("*Proc.publish requires content_type parameter")

            doit = force_update
            if not force_update:
                if website_kind == collection_choices.QA:
                    detail["qa_ws_status"] = self.qa_ws_status
                    doit = True
                else:
                    detail["public_ws_status"] = self.public_ws_status
                    if content_type == "article" and (
                        not self.sps_pkg or not self.sps_pkg.registered_in_core
                    ):
                        detail["registered_in_core"] = self.sps_pkg.registered_in_core
                        doit = False
                    else:
                        doit = True

            detail["doit"] = doit

            if not doit:
                # logging.info(f"Skip publish on {website_kind} {self.pid}")
                operation.finish(user, completed=True, detail=detail)
                resp.update(detail)
                resp["completed"] = True
                return resp

            if website_kind == collection_choices.QA:
                self.qa_ws_status = tracker_choices.PROGRESS_STATUS_DOING
                self.public_ws_status = tracker_choices.PROGRESS_STATUS_TODO
            else:
                self.public_ws_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            api_data = api_data or get_api_data(
                self.collection, content_type, website_kind
            )
            if api_data.get("error"):
                resp.update(api_data)
            else:
                response = callable_publish(self, api_data)
                resp.update(response)

            completed = bool(response.get("result") == "OK")
            self.update_publication_stage(website_kind, completed)
            resp.update(detail)
            operation.finish(user, completed=completed, detail=resp)
            resp["completed"] = completed
            return resp
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            if website_kind == collection_choices.QA:
                self.qa_ws_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            else:
                self.public_ws_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            if operation:
                operation.finish(
                    user,
                    exc_traceback=exc_traceback,
                    exception=e,
                    detail=result,
                )
            resp.update(detail)
            resp["error_type"] = str(type(e))
            resp["error_message"] = str(e)
            return resp

    def update_publication_stage(self, website_kind, completed):
        """
        Estabele o próxim estágio, após ser publicado no QA ou no Público
        """
        if completed:
            status = tracker_choices.PROGRESS_STATUS_DONE
        else:
            status = tracker_choices.PROGRESS_STATUS_REPROC

        if website_kind == collection_choices.QA:
            self.qa_ws_status = status
            self.save()
        else:
            self.public_ws_status = status
            self.save()

    @classmethod
    def items_to_publish(
        cls,
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
            return cls.items_to_publish_on_qa(content_type, force_update, params)
        return cls.items_to_publish_on_public(content_type, force_update, params)

    @classmethod
    def items_to_publish_on_public(cls, content_type, force_update=None, params=None):
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
        return items


class JournalProc(BaseProc, ClusterableModel):
    """ """

    migrated_data = models.ForeignKey(
        MigratedJournal, on_delete=models.SET_NULL, null=True, blank=True
    )

    acron = models.CharField(_("Acronym"), max_length=25, null=True, blank=True)
    title = models.CharField(_("Title"), max_length=128, null=True, blank=True)
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

    panel_data = BaseProc.panel_data + [
        AutocompletePanel("journal"),
        FieldPanel("acron"),
    ]
    panel_proc_result = [
        InlinePanel("journal_proc_result", label=_("Event newest to oldest")),
    ]
    MigratedDataClass = MigratedJournal

    edit_handler = TabbedInterface(
        [
            ObjectList(BaseProc.panel_status, heading=_("Status")),
            ObjectList(panel_data, heading=_("Data")),
            ObjectList(panel_proc_result, heading=_("Events")),
        ]
    )

    class Meta:
        ordering = ["-updated"]
        indexes = [
            models.Index(fields=["acron"]),
        ]

    def __unicode__(self):
        if self.acron:
            return f"{self.acron} ({self.collection.name})"
        return f"{self.pid} ({self.collection.name})"

    def __str__(self):
        if self.acron:
            return f"{self.acron} ({self.collection.name})"
        return f"{self.pid} ({self.collection.name})"

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return JournalProc.objects.filter(acron__icontains=search_term)

    def autocomplete_label(self):
        return f"{self.acron} ({self.collection})"

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

    def issues_with_modified_articles(self):
        for item in JournalAcronIdFile.issues_with_modified_articles(
            collection=self.collection, journal_acron=self.acron
        ):
            yield from IssueProc.objects.filter(
                collection=self.collection,
                journal_proc=self,
                issue_folder=item["issue_folder"],
            )

    @classmethod
    def journals_with_modified_articles(cls, collection=None, journal_acron=None):
        for item in JournalAcronIdFile.journals_with_modified_articles(
            collection=collection, journal_acron=journal_acron
        ):
            yield from JournalProc.objects.filter(
                collection=item.collection,
                acron=item.journal_acron,
            )

    @property
    def completeness(self):
        return {
            "core_synchronized": self.journal.core_synchronized,
            "missing_fields": self.journal.missing_fields,
        }

    @property
    def issn_print(self):
        return self.journal and self.journal.issn_print

    @property
    def issn_electronic(self):
        return self.journal and self.journal.issn_electronic


################################################
class IssueGetOrCreateError(Exception): ...


class IssueProcGetOrCreateError(Exception): ...


class IssueEventCreateError(Exception): ...


class IssueEventReportCreateError(Exception): ...


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
        return f"{self.journal_proc and self.journal_proc.acron} {self.issue_folder} ({self.collection})"

    def __str__(self):
        return f"{self.journal_proc and self.journal_proc.acron} {self.issue_folder} ({self.collection})"

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
    base_form_class = IssueProcAdminModelForm
    ProcResult = IssueProcResult

    panel_status = [
        FieldPanel("migration_status"),
        FieldPanel("files_status"),
        FieldPanel("docs_status"),
        FieldPanel("qa_ws_status"),
        FieldPanel("public_ws_status"),
    ]
    # panel_files = [
    #     AutocompletePanel("issue_files"),
    # ]
    panel_proc_result = [
        InlinePanel("issue_proc_result", label=_("Event newest to oldest")),
    ]
    panel_data = BaseProc.panel_data + [
        AutocompletePanel("journal_proc"),
        AutocompletePanel("issue"),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_data, heading=_("Data")),
            ObjectList(panel_proc_result, heading=_("Events")),
        ]
    )

    @staticmethod
    def create_from_journal_proc_and_issue(user, journal_proc, issue):
        issue_pid_suffix = issue.issue_pid_suffix
        issue_proc = IssueProc.get_or_create(
            user,
            journal_proc.collection,
            pid=f"{journal_proc.pid}{issue.publication_year}{issue_pid_suffix}",
        )
        issue_proc.issue = issue
        issue_proc.journal_proc = journal_proc
        issue_proc.save()
        return issue_proc

    def set_status(self):
        # Propaga status para QA e Public WS
        if self.migration_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.qa_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        if self.qa_ws_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.public_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        # Otimiza a atualização de ArticleProc para docs_status
        if self.docs_status == tracker_choices.PROGRESS_STATUS_REPROC:
            # Atualiza diretamente os artigos relacionados em massa
            ArticleProc.objects.filter(issue_proc=self).update(
                migration_status=tracker_choices.PROGRESS_STATUS_REPROC,
                qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de doc para migration e qa
                public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de doc para public
            )

        # Otimiza a atualização de ArticleProc para files_status
        if self.files_status == tracker_choices.PROGRESS_STATUS_REPROC:
            # Atualiza diretamente os artigos relacionados em massa
            ArticleProc.objects.filter(issue_proc=self).update(
                xml_status=tracker_choices.PROGRESS_STATUS_REPROC,
                sps_pkg_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de xml para sps_pkg
                migration_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de sps_pkg para migration
                qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de migration para qa
                public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,  # Propaga status de qa para public
            )

        self.save()

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
    def get_queryset_to_process(cls, STATUS):
        return (
            Q(migration_status__in=STATUS)
            | Q(qa_ws_status__in=STATUS)
            | Q(public_ws_status__in=STATUS)
            | Q(docs_status__in=STATUS)
            | Q(files_status__in=STATUS)
        )

    @classmethod
    def items_to_process_info(cls, items):
        return items.values(
            "migration_status",
            "docs_status",
            "files_status",
            "qa_ws_status",
            "public_ws_status",
        ).annotate(total=Count("id"))

    @classmethod
    def files_to_migrate(
        cls, collection, journal_acron, publication_year=None, force_update=None
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
        )

    def get_files_from_classic_website(
        self, user, force_update, f_get_files_from_classic_website
    ):
        failures = []
        migrated = []
        try:
            operation = self.start(user, "get_files_from_classic_website")

            self.files_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            for item in f_get_files_from_classic_website(user, self, force_update):
                try:
                    migrated.append(item.original_name)
                    self.issue_files.add(item)
                except AttributeError:
                    try:
                        if item.get("error"):
                            failures.append(item)
                            continue
                    except AttributeError:
                        continue

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
                detail={"failures": len(failures), "migrated": migrated},
            )

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.files_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail={"migrated": len(migrated), "failures": len(failures)},
            )

        if failures:
            try:
                operation = self.start(user, "get_files_from_classic_website - failures")
                operation.finish(
                    user,
                    completed=False,
                    message="Files",
                    detail=failures,
                )
            except Exception as e:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                operation.finish(
                    user,
                    completed=False,
                    message="Files",
                    detail={"failures": len(failures)},
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
        )

    def find_asset(self, basename, name=None):
        if not name:
            name, ext = os.path.splitext(basename)
        # procura a "imagem" no contexto do "issue"
        return self.issue_files.filter(
            Q(original_name=basename) | Q(original_name__startswith=name + ".")
        )

    @staticmethod
    def migrate_pending_document_records(
        user,
        collection_acron,
        journal_acron=None,
        issue_folder=None,
        publication_year=None,
    ):

        id_file_record_params = {}
        if journal_acron:
            id_file_record_params["parent__journal_acron"] = journal_acron
        if publication_year:
            id_file_record_params["item_pid__contains"] = publication_year

        issue_pids = set()
        for item in IdFileRecord.objects.filter(
            parent__collection__acron=collection_acron,
            item_type="article",
            todo=True,
            **id_file_record_params,
        ):
            issue_pids.add(item.item_pid[1:-5])

        if not issue_pids:
            return

        logging.info(
            f"IssueProc.migrate_pending_document_records - issue_pids: {len(issue_pids)}"
        )
        params = {}
        if issue_folder:
            params["issue_folder"] = issue_folder

        issue_procs = IssueProc.objects.select_related(
            "collection",
            "journal_proc",
            "issue",
            "migrated_data",
            "journal_proc__migrated_data",
        ).filter(
            collection__acron=collection_acron,
            pid__in=issue_pids,
            **params,
        )
        if not issue_procs.exists():
            return

        logging.info(
            f"IssueProc.migrate_pending_document_records - issue_procs: {issue_procs.count()}"
        )
        for item in issue_procs:
            item.migrate_document_records(user, force_update=True)
        issue_procs.update(files_status=tracker_choices.PROGRESS_STATUS_TODO)

    def migrate_document_records(self, user, force_update=None):
        try:
            detail = None
            operation = None
            operation = self.start(user, "migrate_document_records")
            if not self.journal_proc:
                raise ValueError(f"IssueProc ({self}) has no journal_proc")

            journal_data = self.journal_proc.migrated_data.data
            issue_data = self.migrated_data.data

            failed_pids = set()
            id_file_records = IdFileRecord.document_records_to_migrate(
                collection=self.journal_proc.collection,
                issue_pid=self.pid,
                force_update=force_update,
            )
            for record in id_file_records:
                try:
                    logging.info(f"migrate_document_records: {record.item_pid}")
                    data = None
                    data = record.get_record_data(
                        journal_data,
                        issue_data,
                    )
                    article_proc = self.create_or_update_article_proc(
                        user, record.item_pid, data["data"], force_update
                    )
                    if not article_proc:
                        failed_pids.add(record.item_pid)
                except Exception as e:
                    failed_pids.add(record.item_pid)
                    detail = {
                        "pid": record.item_pid,
                        "data": data,
                    }
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    subevent = self.start(user, "migrate document records / item")
                    subevent.finish(
                        user,
                        completed=False,
                        detail=detail,
                        exception=e,
                        exc_traceback=exc_traceback,
                    )

            detail = {
                "total issue documents": self.issue.total_documents,
                "total records": id_file_records.count(),
                "total errors": len(failed_pids),
            }

            if failed_pids:
                self.docs_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            else:
                self.docs_status = tracker_choices.PROGRESS_STATUS_DONE
            self.save()
            operation.finish(user, completed=not failed_pids, detail=detail)
            if id_file_records.count():
                id_file_records.exclude(item_pid__in=failed_pids).update(todo=False)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.docs_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            if operation:
                operation.finish(
                    user, exc_traceback=exc_traceback, exception=e, detail=detail
                )

    def create_or_update_article_proc(self, user, pid, data, force_update):
        article_proc = ArticleProc.register_classic_website_data(
            user=user,
            collection=self.collection,
            pid=pid,
            data=data,
            content_type="article",
            force_update=force_update,
        )
        if not article_proc:
            raise ArticleProc.DoesNotExist(f"Unable to create ArticleProc for {pid}")

        migrated_article = article_proc.migrated_data
        document = migrated_article.document

        if not migrated_article.file_type:
            migrated_article.file_type = document.file_type
            migrated_article.save()

        article_proc.update(
            issue_proc=self,
            pkg_name=document.filename_without_extension,
            migration_status=tracker_choices.PROGRESS_STATUS_TODO,
            user=user,
            main_lang=document.original_language,
            force_update=force_update,
        )
        return article_proc

    @staticmethod
    def get_issue_pid(issue):
        return IssueProc.objects.filter(issue=issue).first().pid

    @property
    def bundle_id(self):
        return "-".join([self.journal_proc.pid, self.issue.bundle_id_suffix])

    def delete_unlink_articles(self, user=None):
        return Article.delete_unlink_articles(
            user or self.updated_by or self.creator,
            self.journal_proc.journal,
            self.issue,
        )


class ArticleEventCreateError(Exception): ...


class ArticleEventReportCreateError(Exception): ...


class ArticleProc(BaseProc, ClusterableModel):
    # Armazena os IDs dos artigos no contexto de cada coleção
    # serve para conseguir recuperar artigos pelo ID do site clássico
    migrated_data = models.ForeignKey(
        MigratedArticle, on_delete=models.SET_NULL, null=True, blank=True
    )
    issue_proc = models.ForeignKey(
        IssueProc, on_delete=models.SET_NULL, null=True, blank=True
    )
    pkg_name = models.CharField(
        _("Package name"), max_length=100, null=True, blank=True
    )
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

    base_form_class = ProcAdminModelForm
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
        InlinePanel("article_proc_result", label=_("Event newest to oldest")),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_files, heading=_("Files")),
            ObjectList(panel_proc_result, heading=_("Events")),
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

    def set_status(self):
        if self.xml_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_REPROC

        if self.sps_pkg_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.migration_status = tracker_choices.PROGRESS_STATUS_REPROC

        if self.migration_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.qa_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        if self.qa_ws_status == tracker_choices.PROGRESS_STATUS_REPROC:
            self.public_ws_status = tracker_choices.PROGRESS_STATUS_REPROC

        self.save()

    @property
    def identification(self):
        if self.sps_pkg:
            return self.sps_pkg.sps_pkg_name
        if self.issue_proc:
            return f"{self.issue_proc} {self.pkg_name}"
        return f"{self.pid} {self.collection}"

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

    def get_xml(self, user, body_and_back_xml):
        try:

            operation = self.start(user, "get xml")

            self.xml_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            if not self.migrated_data.file_type:
                self.migrated_data.file_type = self.migrated_data.document.file_type
                self.migrated_data.save()

            detail = {}
            detail["file_type"] = self.migrated_data.file_type

            if self.migrated_data.file_type == "html":
                migrated_data = self.migrated_data
                classic_ws_doc = migrated_data.document
                htmlxml = HTMLXML.create_or_update(
                    user=user,
                    migrated_article=migrated_data,
                    n_references=len(classic_ws_doc.citations or []),
                    record_types="|".join(classic_ws_doc.record_types or []),
                )
                htmlxml.html_to_xml(user, self, body_and_back_xml)
                htmlxml.generate_report(user, self)
                detail.update(htmlxml.data)

            xml = get_migrated_xml_with_pre(self)
            if xml:
                self.xml_status = tracker_choices.PROGRESS_STATUS_DONE
                detail.update(xml.data)
            else:
                self.xml_status = tracker_choices.PROGRESS_STATUS_REPROC
            self.save()

            completed = self.xml_status == tracker_choices.PROGRESS_STATUS_DONE
            operation.finish(user, completed=completed, detail=detail)
            return completed
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.xml_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
            )
            return self.xml_status == tracker_choices.PROGRESS_STATUS_TODO

    @classmethod
    def get_queryset_to_process(cls, STATUS):
        return (
            Q(migration_status__in=STATUS)
            | Q(qa_ws_status__in=STATUS)
            | Q(public_ws_status__in=STATUS)
            | Q(xml_status__in=STATUS)
            | Q(sps_pkg_status__in=STATUS)
        )

    @classmethod
    def items_to_process_info(cls, items):
        return items.values(
            "xml_status",
            "sps_pkg_status",
            "migration_status",
            "qa_ws_status",
            "public_ws_status",
        ).annotate(total=Count("id"))

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
        )

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
        cls.objects.filter(
            q,
            **params,
        ).update(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
        )
        return cls.objects.filter(
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_TODO,
            **params,
        )

    @property
    def renditions(self):
        return self.issue_proc.issue_files.filter(
            pkg_name=self.pkg_name, component_type="rendition"
        )

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
        force_update=False,
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
            completed = bool(self.sps_pkg and self.sps_pkg.is_complete)
            operation.finish(
                user,
                completed=completed,
                detail=self.sps_pkg and self.sps_pkg.data,
            )
            return bool(self.sps_pkg and self.sps_pkg.pid_v3)
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
        if self.sps_pkg:
            if self.sps_pkg.registered_in_core:
                self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DONE
            else:
                self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_REPROC
        else:
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_BLOCKED
        self.save()

    @property
    def journal_proc(self):
        return self.issue_proc.journal_proc

    @property
    def article(self):
        try:
            sps_pkg = self.sps_pkg
            if sps_pkg:
                return Article.objects.get(sps_pkg=sps_pkg)
        except (AttributeError, Article.DoesNotExist) as e:
            logging.info(f"Not found ArticleProc.article: {sps_pkg} {e}")

    def migrate_article(self, user, force_update):
        body_and_back_xml = force_update
        html_to_xml = force_update
        if not self.get_xml(user, body_and_back_xml):
            return None

        if not self.generate_sps_package(
            user,
            body_and_back_xml,
            html_to_xml,
        ):
            return None

        return self.create_or_update_item(user, force_update, create_or_update_article)

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
