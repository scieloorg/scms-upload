import json
import logging
import os
import sys
import traceback
from datetime import datetime
from tempfile import TemporaryDirectory

from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from packtools.sps.utils.xml_fixer import fix_inline_graphic_in_caption
from wagtail.admin.panels import (
    FieldPanel,
    InlinePanel,
    ObjectList,
    TabbedInterface,
)
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article.models import Article
from collection import choices as collection_choices
from collection.models import Collection
from core.models import CommonControlField
from core.utils.file_utils import delete_files
from htmlxml.models import HTMLXML
from issue.models import Issue
from journal.choices import JOURNAL_AVAILABILTY_STATUS
from journal.models import Journal
from migration.controller import (
    PkgZipBuilder,
    XMLVersionXmlWithPreError,
    create_or_update_article,
)
from migration.models import (
    IdFileRecord,
    JournalAcronIdFile,
    MigratedArticle,
    MigratedFile,
    MigratedIssue,
    MigratedJournal,
)
from package import choices as package_choices
from package.models import SPSPkg
from proc import exceptions
from proc.forms import IssueProcAdminModelForm, ProcAdminModelForm
from publication.api.publication import get_api_data
from scielo_classic_website.htmlbody.html_body import HTMLContent
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback


class NoDocumentRecordsToMigrateError(Exception):
    ...

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
        ordering = ["-updated"]
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
    file = models.FileField(upload_to=proc_report_directory_path, null=True, blank=True, max_length=300)
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
        collection_acron = self.collection.acron if self.collection else "Unknown"
        return f"{collection_acron} {self.pid} {self.task_name} {self.report_date}"

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
        if not self.pid:
            return ""
        pid = self.pid
        if len(self.pid) == 23:
            pid = self.pid[1:]
        collection_acron = self.collection.acron if self.collection else ""
        paths = [collection_acron, pid[:9], pid[9:13], pid[13:17], pid[17:]]
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
            except cls.MultipleObjectsReturned:
                items = cls.objects.filter(collection=collection, pid=pid).order_by("-created")
                for item in items[1:]:
                    item.delete()
                return items[0]
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
            q |= (
                Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_DONE)
                | Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_PENDING)
                | Q(qa_ws_status=tracker_choices.PROGRESS_STATUS_BLOCKED)
            )

        cls.objects.filter(q, **params).update(
            qa_ws_status=tracker_choices.PROGRESS_STATUS_TODO
        )
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

            completed = bool(resp.get("result") == "OK")
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
                    detail=resp,
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
            params["sps_pkg_status__isnull"] = False
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
        collection_name = self.collection.name if self.collection else "Unknown"
        if self.acron:
            return f"{self.acron} ({collection_name})"
        return f"{self.pid} ({collection_name})"

    def __str__(self):
        collection_name = self.collection.name if self.collection else "Unknown"
        if self.acron:
            return f"{self.acron} ({collection_name})"
        return f"{self.pid} ({collection_name})"

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
        if self.journal_proc:
            return f"{self.journal_proc.acron} {self.issue_folder} ({self.collection})"
        return f"{self.pid} ({self.collection})"
    
    def __str__(self):
        if self.journal_proc:
            return f"{self.journal_proc.acron} {self.issue_folder} ({self.collection})"
        return f"{self.pid} ({self.collection})"
    
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
        self, user, force_update, migrate_issue_files_function
    ):
        try:
            operation = self.start(user, "get_files_from_classic_website")
            if self.files_status == tracker_choices.PROGRESS_STATUS_DONE and not force_update:
                operation.finish(
                    user,
                    completed=True,
                    message="Files already migrated",
                    detail={"migrated": self.issue_files.count()},
                )
                return

            self.files_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()

            failures = []
            migration_result = migrate_issue_files_function(
                user,
                collection=self.collection,
                journal_acron=self.journal_proc.acron,
                issue_folder=self.issue_folder,
                force_update=force_update,
            )
            failures = migration_result.get("exceptions", [])
            migrated = migration_result.get("migrated") or []
            self.issue_files.clear()
            self.issue_files.set(migration_result.get("migrated", []))

            if migrated and failures:
                self.files_status = tracker_choices.PROGRESS_STATUS_PENDING
            elif migrated:
                self.files_status = tracker_choices.PROGRESS_STATUS_DONE
            else:
                self.files_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()

            operation.finish(
                user,
                completed=(self.files_status == tracker_choices.PROGRESS_STATUS_DONE),
                message="Files",
                detail={"migrated": self.issue_files.count(), "failures": failures},
            )
            return self.issue_files.count()

        except Exception as e:
            logging.exception(f"Exception: get_files_from_classic_website: {e}")
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.files_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail={"failures": failures, "migrated": self.issue_files.count()},
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
        items = self.issue_files.filter(
            Q(original_name=basename) | Q(original_name__startswith=name + ".")
        )
        if items.exists():
            return items
        # procura a "imagem" no contexto do "journal"
        return MigratedFile.find(
            collection=self.collection,
            journal_acron=self.journal_proc.acron,
            name=name,  
        )

    @classmethod
    def get_id_and_pid_list_to_process(cls, journal_proc, issue_folder, publication_year, issue_pids, status, events):
        events.append("Identify filter: status")
        q = Q(docs_status__in=status) | Q(files_status__in=status)

        events.append("Identify filter: issue_folder / publication_year")
        issue_filter = {}
        if issue_folder:
            issue_filter["issue_folder"] = issue_folder
        if publication_year:
            issue_filter["issue__publication_year"] = publication_year
        
        events.append("Select journal issues to process")
        if issue_filter:
            if issue_pids:
                issue_filter["pid__in"] = issue_pids
            return cls.objects.filter(
                journal_proc=journal_proc,
                **issue_filter
            ).values_list("id", "pid")

        if issue_pids:
            q |= Q(pid__in=issue_pids)

        return cls.objects.filter(
            q,
            journal_proc=journal_proc,
        ).values_list("id", "pid")

    def migrate_document_records(self, user, force_update=None):
        try:
            total = 0
            total_document_records = 0
            exception = None
            exc_traceback = None
            detail = {}
            operation = None
            operation = self.start(user, "migrate_document_records")
            if not self.journal_proc:
                raise ValueError(f"IssueProc ({self}) has no journal_proc")

            total_document_records = IdFileRecord.document_records_to_migrate(
                collection=self.collection,
                issue_pid=self.pid,
                force_update=True,  # todos os registros encontrados em acron.id no momento
            ).count()
            detail["total_document_records"] = total_document_records

            force_update = ArticleProc.objects.filter(issue_proc=self).count() < total_document_records

            id_file_records = IdFileRecord.document_records_to_migrate(
                collection=self.collection,
                issue_pid=self.pid,
                force_update=force_update,
            )
            detail["total_document_records_to_migrate"] = id_file_records.count()
            if detail["total_document_records_to_migrate"] == 0:
                raise NoDocumentRecordsToMigrateError("No document records to migrate")

            detail["total_migrated_articles - initial"] = ArticleProc.objects.filter(
                issue_proc=self
            ).count()
            journal_data = self.journal_proc.migrated_data.data
            issue_data = self.migrated_data.data
            exceptions = {}
            for record in id_file_records:
                try:
                    data = None
                    data = record.get_record_data(
                        journal_data,
                        issue_data,
                    )
                    article_proc = self.create_or_update_article_proc(
                        user, record.item_pid, data["data"], force_update
                    )
                    total += 1
                    if not article_proc:
                        raise ValueError(f"Unable to create ArticleProc for PID {record.item_pid}")
                except Exception as e:
                    exceptions[record.item_pid] = traceback.format_exc()

            detail["exceptions"] = exceptions
            detail["total failed"] = len(exceptions)
            detail["total done"] = detail["total_document_records_to_migrate"] - detail["total failed"]
            id_file_records.exclude(item_pid__in=list(exceptions.keys())).update(todo=False)

            new_status = self.get_new_docs_status(total_document_records)
            
        except NoDocumentRecordsToMigrateError as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            new_status = self.get_new_docs_status(total_document_records)

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            exception = e
            new_status = tracker_choices.PROGRESS_STATUS_BLOCKED
        if new_status != self.docs_status:
            self.docs_status = new_status
            self.save()
        if operation:
            operation.finish(
                user,
                completed=self.docs_status == tracker_choices.PROGRESS_STATUS_DONE,
                exc_traceback=exc_traceback,
                exception=exception,
                detail=detail
            )
        return total

    def get_new_docs_status(self, total_document_records=None, total_migrated_articles=None):
        if total_document_records is None:
            total_document_records = IdFileRecord.document_records_to_migrate(
                collection=self.collection,
                issue_pid=self.pid,
                force_update=True,  # todos os registros encontrados em acron.id no momento
            ).count()
        if total_migrated_articles is None:
            total_migrated_articles = ArticleProc.objects.filter(issue_proc=self).count()
        if total_document_records == 0:
            return tracker_choices.PROGRESS_STATUS_BLOCKED
        if total_migrated_articles == 0:
            return tracker_choices.PROGRESS_STATUS_TODO
        if total_migrated_articles == total_document_records:
            return tracker_choices.PROGRESS_STATUS_DONE
        return tracker_choices.PROGRESS_STATUS_PENDING

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
        issue_proc = IssueProc.objects.filter(issue=issue).first()
        return issue_proc.pid if issue_proc else None

    @property
    def bundle_id(self):
        if not self.journal_proc or not self.journal_proc.pid:
            return ""
        if not self.issue or not self.issue.bundle_id_suffix:
            return ""
        return "-".join([self.journal_proc.pid, self.issue.bundle_id_suffix])



class ArticleEventCreateError(Exception): ...


class ArticleEventReportCreateError(Exception): ...


def proc_directory_path(instance, filename):
    name, ext = os.path.splitext(filename)
    return os.path.join("proc", *name.split("-"), filename)


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
    processed_xml = models.FileField(
        _("Processed XML"),
        upload_to=proc_directory_path,
        null=True,
        blank=True,
        help_text=_("Native XML + modifications or converted XML from HTML"),
        max_length=300,
    )

    base_form_class = ProcAdminModelForm
    ProcResult = ArticleProcResult

    panel_files = [
        FieldPanel("pkg_name", read_only=True),
        FieldPanel("processed_xml"),
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

    @classmethod
    def mark_for_reprocessing(cls, issue_proc, article_pids=None):
        params = {"issue_proc": issue_proc}
        if article_pids:
            params["pid__in"] = article_pids
        if issue_proc.docs_status not in (
            tracker_choices.PROGRESS_STATUS_DONE,
            tracker_choices.PROGRESS_STATUS_PENDING,
        ):
            return
        if issue_proc.files_status not in (
            tracker_choices.PROGRESS_STATUS_DONE,
            tracker_choices.PROGRESS_STATUS_PENDING,
        ):
            return
        cls.objects.filter(**params).update(
            xml_status=tracker_choices.PROGRESS_STATUS_REPROC,
            sps_pkg_status=tracker_choices.PROGRESS_STATUS_REPROC,
            migration_status=tracker_choices.PROGRESS_STATUS_REPROC,
            qa_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,
            public_ws_status=tracker_choices.PROGRESS_STATUS_REPROC,
        )

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

    def get_xml(self, user):
        try:
            detail = {}
            operation = self.start(user, "get xml")

            self.xml_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()
            try:
                delete_files(self.processed_xml.file.path)
            except Exception:
                pass

            migrated_data = self.migrated_data
            document = migrated_data.document
            migrated_document_publication_day = document.get_complete_article_publication_date()

            if not migrated_data.file_type:
                migrated_data.file_type = document.file_type
                migrated_data.save()

            detail["file_type"] = migrated_data.file_type
            if detail["file_type"] == "html":
                xml_file_path = self.get_xml_from_html(user, detail)
                xml_with_pre = None
            else:
                xml_with_pre = self.get_xml_from_native(detail)
                xml_file_path = None

            self.save_processed_xml(
                xml_with_pre,
                xml_file_path,
                detail,
                migrated_document_publication_day,
            )
            self.xml_status = tracker_choices.PROGRESS_STATUS_DONE
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

    def get_xml_from_native(self, detail):
        try:
            xml_with_pre = list(XMLWithPre.create(path=self.migrated_xml.file.path))[0]
        except IndexError as e:
            raise XMLVersionXmlWithPreError(
                _("Unable to get xml_with_pre from native for {}: {}").format(self, e)
            )
        try:
            # correção de fig/inline-graphic para fig/graphic
            detail["fix_inline_graphic_in_caption"] = fix_inline_graphic_in_caption(xml_with_pre.xmltree)
        except Exception as e:
            logging.exception(e)
            raise
        try:
            article_publication_date = xml_with_pre.article_publication_date
            if not article_publication_date or len(article_publication_date) != 10:
                processing_date = self.migrated_data.document.processing_date
                if processing_date:
                    # adota a data de processamento do documento como data de publicação
                    article_publication_date = datetime.strptime(processing_date, "%Y%m%d").strftime("%Y-%m-%d")
                else:
                    # completa a data de publicação com média de dia e/ou mes ausentes
                    article_publication_date =  xml_with_pre.get_complete_publication_date()
                xml_with_pre.article_publication_date = article_publication_date
        except Exception as e:
            logging.exception(e)
            raise
        return xml_with_pre
    
    def get_xml_from_html(self, user, detail):
        migrated_data = self.migrated_data
        classic_ws_doc = migrated_data.document
        htmlxml = HTMLXML.create_or_update(
            user=user,
            migrated_article=migrated_data,
            n_references=len(classic_ws_doc.citations or []),
            record_types="|".join(classic_ws_doc.record_types or []),
        )
        detail["html_to_xml"] = htmlxml.html_to_xml(user, self)
        self.xml_status = htmlxml.html2xml_status
        if os.path.isfile(htmlxml.file.path):
            return htmlxml.file.path
    
    @property
    def xml_with_pre(self):
        try:
            return list(XMLWithPre.create(path=self.processed_xml.path))[0]
        except Exception as e:
            raise XMLVersionXmlWithPreError(
                _("Unable to get xml_with_pre for {}: {}").format(self, e)
            )
            
    def save_processed_xml(self, xml_with_pre, xml_file_path, detail, migrated_document_publication_day):
        try:
            if not xml_with_pre and xml_file_path:
                xml_with_pre = list(XMLWithPre.create(path=xml_file_path))[0]
            
            if not xml_with_pre:
                raise ValueError("No XML with pre to process")

            if self.pid and xml_with_pre.v2 != self.pid:
                # corrige ou adiciona pid v2 no XML nativo ou obtido do html
                # usando o valor do pid v2 do site clássico
                xml_with_pre.v2 = self.pid

            order = str(int(self.pid[-5:]))
            if not xml_with_pre.order or str(int(xml_with_pre.order)) != order:
                # corrige ou adiciona other pid no XML nativo ou obtido do html
                # usando o valor do "order" do site clássico
                xml_with_pre.order = order

            try:
                article_date = xml_with_pre.article_publication_date
            except Exception as e:
                # data incompleta
                article_date = None
            if not article_date:
                xml_with_pre.article_publication_date = (
                    migrated_document_publication_day or xml_with_pre.get_complete_publication_date()
                )

            detail.update(xml_with_pre.data)
            try:
                os.unlink(self.processed_xml.path)
            except Exception as e:
                pass
            self.processed_xml.save(
                xml_with_pre.sps_pkg_name + ".xml",
                ContentFile(xml_with_pre.tostring()),
                save=False,
            )
        except Exception as e:
            logging.exception(f"Exception: save_processed_xml: {e}")
            raise XMLVersionXmlWithPreError(
                _("Unable to get xml with pre from migrated article {}: {} {}").format(
                    xml_file_path or xml_with_pre.sps_pkg_name + ".xml", type(e), e
                )
            )

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
            if not item.file:
                continue
            if not item.file.path:
                continue
            if not os.path.isfile(item.file.path):
                continue
            return item
        raise MigratedFile.DoesNotExist(
            _("No migrated XML file found for {} ({})").format(self.pkg_name, self.issue_proc)
        )

    @property
    def translation_files(self):
        return self.issue_proc.issue_files.filter(
            component_type="html",
            pkg_name=self.pkg_name,
        ).order_by("-updated")

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
            if not item.text:
                continue
            lang = item.lang
            if lang in xhtmls.keys():
                continue
            hc = HTMLContent(item.text)
            xhtmls.setdefault(lang, {})
            xhtmls[lang][part[item.part]] = hc.content
        return xhtmls

    def generate_sps_package(
        self,
        user,
    ):
        try:
            operation = self.start(user, "generate_sps_package")
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_DOING
            self.save()
            completed = False
            pid_v3 = None
            detail = {}
            with TemporaryDirectory() as output_folder:

                xml_with_pre = self.xml_with_pre

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
                detail["replacements"] = builder.replacements
                if self.sps_pkg:
                    detail.update(self.sps_pkg.data)
                    completed = self.sps_pkg.is_complete
                    pid_v3 = self.sps_pkg.pid_v3
            self.update_sps_pkg_status()
            operation.finish(
                user,
                completed=completed,
                detail=detail,
            )
            return bool(pid_v3)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.sps_pkg_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            operation.finish(
                user,
                exc_traceback=exc_traceback,
                exception=e,
                detail=detail,
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
        if force_update:
            self.xml_status = tracker_choices.PROGRESS_STATUS_REPROC
            self.set_status()
        if not self.get_xml(user):
            return None
        if not self.generate_sps_package(user):
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
