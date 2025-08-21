import json
import logging
import traceback
import uuid
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import models
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from tracker import choices


class ProcEventCreateError(Exception):
    ...


class UnexpectedEventCreateError(Exception):
    ...


class EventCreateError(Exception):
    ...


class EventReportCreateError(Exception):
    ...


class EventReportSaveFileError(Exception):
    ...


class EventReportCreateError(Exception):
    ...


class EventReportDeleteEventsError(Exception):
    ...


def format_traceback(exc_traceback):
    return traceback.format_tb(exc_traceback)


class BaseEvent(models.Model):
    name = models.CharField(_("name"), max_length=200)
    detail = models.JSONField(null=True, blank=True)
    created = models.DateTimeField(verbose_name=_("Creation date"), auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def data(self):
        return {
            "name": self.name,
            "detail": self.detail,
            "created": self.created.isoformat(),
        }

    @classmethod
    def create(
        cls,
        name=None,
        detail=None,
    ):
        obj = cls()
        obj.detail = detail
        obj.name = name
        obj.save()
        return obj


class UnexpectedEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(verbose_name=_("Creation date"), auto_now_add=True)
    exception_type = models.TextField(_("Exception Type"), null=True, blank=True)
    exception_msg = models.TextField(_("Exception Msg"), null=True, blank=True)
    traceback = models.JSONField(null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)
    item = models.CharField(
        _("Item"),
        max_length=256,
        null=True,
        blank=True,
    )
    action = models.CharField(
        _("Action"),
        max_length=256,
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["exception_type"]),
            models.Index(fields=["item"]),
            models.Index(fields=["action"]),
        ]
        ordering = ["-created"]

    def __str__(self):
        if self.item or self.action:
            return f"{self.action} {self.item} {self.exception_msg}"
        return f"{self.exception_msg}"

    @property
    def data(self):
        return dict(
            created=self.created.isoformat(),
            item=self.item,
            action=self.action,
            exception_type=self.exception_type,
            exception_msg=self.exception_msg,
            traceback=json.dumps(self.traceback),
            detail=json.dumps(self.detail),
        )

    @classmethod
    def create(
        cls,
        e=None,
        exception=None,
        exc_traceback=None,
        item=None,
        action=None,
        detail=None,
    ):
        try:
            exception = exception or e
            if exception:
                logging.exception(exception)

            obj = cls()
            obj.item = item
            obj.action = action
            obj.exception_msg = str(exception)
            obj.exception_type = str(type(exception))
            try:
                json.dumps(detail)
                obj.detail = detail
            except Exception as e:
                obj.detail = str(detail)

            if exc_traceback:
                obj.traceback = traceback.format_tb(exc_traceback)
            obj.save()
            return obj
        except Exception as exc:
            raise UnexpectedEventCreateError(
                f"Unable to create unexpected event ({exception} {exc_traceback}). EXCEPTION {exc}"
            )


class TaskTracker(BaseEvent):
    updated = models.DateTimeField(verbose_name=_("Last update date"), auto_now=True)
    status = models.CharField(
        _("status"),
        choices=choices.TASK_TRACK_STATUS,
        max_length=11,
        null=True,
        blank=True,
        default=choices.TASK_TRACK_STATUS_STARTED,
    )

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-updated"]

    def finish(
        self,
        completed=False,
        exception=None,
        message_type=None,
        message=None,
        exc_traceback=None,
        detail=None,
    ):
        detail = detail or {}
        if exception:
            logging.exception(exception)
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

        if detail:
            self.detail = detail
        if completed:
            status = choices.TASK_TRACK_STATUS_FINISHED
        else:
            status = choices.TASK_TRACK_STATUS_INTERRUPTED
        self.status = status
        self.save()
