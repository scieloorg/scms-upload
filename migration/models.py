import logging
import os
import sys
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import IntegrityError, models, DataError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from scielo_classic_website import classic_ws
from wagtail.admin.panels import FieldPanel
from wagtail.models import Orderable
from pathlib import Path

from collection.models import Collection
from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent
from . import exceptions


def now():
    return datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")


class MigratedFileCreateOrUpdateError(Exception): ...


class MigratedDocumentHTMLForbiddenError(Exception): ...


class MigrationError(Exception): ...


def modified_date(file_path):
    try:
        s = os.stat(file_path)
        return datetime.fromtimestamp(s.st_mtime).isoformat()
    except Exception as e:
        return datetime.utcnow().isoformat()


class ClassicWebsiteConfiguration(CommonControlField):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    title_path = models.CharField(
        _("Title path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Title path: title.id path or title.mst path without extension"),
    )
    issue_path = models.CharField(
        _("Issue path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Issue path: issue.id path or issue.mst path without extension"),
    )
    serial_path = models.CharField(
        _("Serial path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Serial path"),
    )
    bases_work_path = models.CharField(
        _("Bases work path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases work path"),
    )
    bases_pdf_path = models.CharField(
        _("Bases pdf path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases translation path"),
    )
    bases_translation_path = models.CharField(
        _("Bases translation path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases translation path"),
    )
    bases_xml_path = models.CharField(
        _("Bases XML path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Bases XML path"),
    )
    htdocs_img_revistas_path = models.CharField(
        _("Htdocs img revistas path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Htdocs img revistas path"),
    )
    pid_list_path = models.CharField(
        _("PID list path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_(
            "Path of a text file which contains all the article PIDs from artigo.mst"
        ),
    )
    alternative_htdocs_img_revistas_path = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"{self.collection}"

    class Meta:
        indexes = [
            models.Index(fields=["collection"]),
        ]

    @classmethod
    def get_or_create(
        cls,
        collection,
        user=None,
        title_path=None,
        issue_path=None,
        serial_path=None,
        pid_list_path=None,
        bases_work_path=None,
        bases_pdf_path=None,
        bases_translation_path=None,
        bases_xml_path=None,
        htdocs_img_revistas_path=None,
    ):
        try:
            return cls.objects.get(collection=collection)
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.title_path = title_path
            obj.issue_path = issue_path
            obj.serial_path = serial_path
            obj.pid_list_path = pid_list_path
            obj.bases_work_path = bases_work_path
            obj.bases_pdf_path = bases_pdf_path
            obj.bases_translation_path = bases_translation_path
            obj.bases_xml_path = bases_xml_path
            obj.htdocs_img_revistas_path = htdocs_img_revistas_path
            obj.creator = user
            obj.save()
            return obj

    base_form_class = CoreAdminModelForm


class MigratedData(CommonControlField):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )

    pid = models.CharField(_("PID"), max_length=23, null=True, blank=True)
    content_type = models.CharField(_("Origin"), max_length=23, null=True, blank=True)

    # datas no registro da base isis para identificar
    # se houve mudança nos dados durante a migração
    isis_updated_date = models.CharField(
        _("ISIS updated date"), max_length=8, null=True, blank=True
    )
    isis_created_date = models.CharField(
        _("ISIS created date"), max_length=8, null=True, blank=True
    )
    migration_status = models.CharField(
        _("Migration Status"),
        max_length=8,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )

    # dados migrados
    data = models.JSONField(blank=True, null=True)

    panels = [
        FieldPanel("content_type"),
        FieldPanel("pid"),
        FieldPanel("collection"),
        FieldPanel("migration_status"),
        FieldPanel("isis_updated_date"),
        FieldPanel("isis_created_date"),
        FieldPanel("data"),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["content_type"]),
            models.Index(fields=["pid"]),
            models.Index(fields=["migration_status"]),
        ]

    def __str__(self):
        return f"{self.collection} {self.pid}"

    def is_up_to_date(self, isis_updated_date, data):
        return (
            bool(self.isis_updated_date and self.isis_updated_date == isis_updated_date)
            and self.data == data
        )

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
            if data:
                classic_ws_obj = cls.get_data_from_classic_website(data)
        except Exception as e:
            classic_ws_obj = None

        if classic_ws_obj:
            status = tracker_choices.PROGRESS_STATUS_TODO
            isis_created_date = classic_ws_obj.isis_created_date
            isis_updated_date = classic_ws_obj.isis_updated_date
            try:
                if classic_ws_obj.is_press_release:
                    status = tracker_choices.PROGRESS_STATUS_IGNORED
            except AttributeError:
                pass
        else:
            status = tracker_choices.PROGRESS_STATUS_PENDING
            isis_created_date = None
            isis_updated_date = None
        return cls.create_or_update_migrated_data(
            collection=collection,
            pid=pid,
            user=user,
            isis_created_date=isis_created_date,
            isis_updated_date=isis_updated_date,
            data=data,
            migration_status=status,
            content_type=content_type,
            force_update=force_update,
        )

    @classmethod
    def create_or_update_migrated_data(
        cls,
        user=None,
        collection=None,
        pid=None,
        data=None,
        migration_status=None,
        isis_created_date=None,
        isis_updated_date=None,
        content_type=None,
        force_update=None,
    ):
        try:
            obj = cls.objects.get(collection=collection, pid=pid)
            if obj.is_up_to_date(isis_updated_date, data) and not force_update:
                return obj
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.pid = pid
            obj.creator = user

        try:
            obj.content_type = content_type or obj.content_type
            obj.collection = collection or obj.collection
            obj.pid = pid or obj.pid
            obj.migration_status = migration_status or obj.migration_status
            obj.data = data or obj.data

            obj.isis_created_date = isis_created_date or obj.isis_created_date
            obj.isis_updated_date = isis_updated_date or obj.isis_updated_date

            _date = now()[:10].replace("-", "")

            if obj.isis_created_date:
                if not obj.isis_updated_date:
                    obj.isis_updated_date = _date
            else:
                obj.isis_created_date = _date
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateMigratedError(
                _("Unable to create_or_update_migrated_data {} {} {} {}").format(
                    collection, pid, type(e), e
                )
            )


def extract_relative_path(full_path):
    for part in ["htdocs", "bases-work", "bases"]:
        if part in full_path:
            return full_path[full_path.find(part):]
    return full_path


def migrated_files_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>

    try:
        path_relative = instance.original_path
    except (AttributeError, TypeError) as e:
        path_relative = extract_relative_path(instance.source_path)

    try:
        return f"classic_website/{instance.collection.acron}/{path_relative or filename}"
    except (AttributeError, TypeError) as e:
        return f"classic_website/{filename}"


class MigratedFile(CommonControlField):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )
    file = models.FileField(
        upload_to=migrated_files_directory_path, null=True, blank=True
    )
    # bases/pdf/acron/volnum/pt_a01.pdf
    original_path = models.CharField(
        _("Original Path"), max_length=200, null=True, blank=True
    )

    # pt_a01.pdf
    original_name = models.CharField(
        _("Original name"), max_length=100, null=True, blank=True
    )

    # 2025-09-02T19:35:35.829144 - dat
    file_datetime_iso = models.CharField(max_length=26, null=True, blank=True)

    # /pdf/acron/volnum/pt_a01.pdf
    original_href = models.CharField(
        _("Original href"), max_length=150, null=True, blank=True
    )
    component_type = models.CharField(
        _("Component type"), max_length=16, null=True, blank=True
    )
    lang = models.CharField(_("Language"), max_length=2, null=True, blank=True)
    pkg_name = models.CharField(_("Pkg name"), max_length=100, null=True, blank=True)
    part = models.CharField(_("Part"), max_length=1, null=True, blank=True)

    autocomplete_search_field = "original_path"

    def __str__(self):
        return f"{self.collection} {self.original_path}"

    def autocomplete_label(self):
        return f"{self.collection} {self.original_path}"

    panels = [
        FieldPanel("file"),
        FieldPanel("file_datetime_iso", read_only=True),
        FieldPanel("original_path", read_only=True),
        FieldPanel("original_href", read_only=True),
        FieldPanel("original_name", read_only=True),
        FieldPanel("component_type", read_only=True),
        FieldPanel("pkg_name", read_only=True),
        FieldPanel("lang", read_only=True),
        FieldPanel("part", read_only=True),
    ]

    class Meta:
        indexes = [
            models.Index(fields=["original_name"]),
            models.Index(fields=["original_path"]),
            models.Index(fields=["original_href"]),
        ]

    @classmethod
    def has_changes(cls, user, collection, file_path, force_update):
        if not force_update:
            try:
                file_datetime_iso = modified_date(file_path)
                if cls.objects.filter(
                    collection=collection, original_path=file_path, file_datetime_iso=file_datetime_iso
                ).exists():
                    return False
            except cls.DoesNotExist:
                pass

        cls.create_or_update(
            user=user,
            collection=collection,
            original_path=file_path,
            source_path=file_path,
            component_type="id_file",
            force_update=force_update,
        )
        return True

    @classmethod
    def get(
        cls,
        collection=None,
        original_path=None,
        file_datetime_iso=None,
    ):
        if collection and original_path:
            if file_datetime_iso:
                return cls.objects.get(collection=collection, original_path=original_path, file_datetime_iso=file_datetime_iso)
            return cls.objects.get(collection=collection, original_path=original_path)
        raise ValueError("MigratedFile.get requires collection and original_path")

    @classmethod
    def create_or_update(
        cls,
        user=None,
        collection=None,
        original_path=None,
        source_path=None,
        component_type=None,
        lang=None,
        part=None,
        pkg_name=None,
        force_update=None,
        content=None,
        file_datetime_iso=None,
        basename=None,
    ):
        if not source_path and not collection and not original_path:
            raise ValueError(
                "MigratedFile.create_or_update requires source_path, collection, original_path"
            )

        if not file_datetime_iso:
            file_datetime_iso = modified_date(source_path)

        try:
            obj = cls.get(collection, original_path)
            if not force_update and obj.is_up_to_date(file_datetime_iso):
                return obj

            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.original_path = original_path
            obj.original_href = obj.get_original_href(original_path)
            obj.creator = user

            if not basename:
                basename = os.path.basename(source_path)
            obj.original_name = basename

        obj.pkg_name = pkg_name
        obj.lang = lang
        obj.part = part
        obj.component_type = component_type
        obj.file_datetime_iso = file_datetime_iso

        if not content:
            try:
                with open(source_path, "rb") as fp:
                    content = fp.read()
            except Exception as e:
                logging.info(f"MigratedFile.create_or_update - {source_path} - readfile")
                logging.exception(e)
                exc_type, exc_value, exc_traceback = sys.exc_info()
                UnexpectedEvent.create(
                    e=e,
                    exc_traceback=exc_traceback,
                    detail={
                        "function": "MigratedFile.create_or_update - readfile",
                        "collection": str(collection),
                    },
                )
                raise e

        try:
            obj.save_file(obj.original_name, content or "")
        except Exception as e:
            logging.info(f"MigratedFile.create_or_update - {source_path} - save_file")
            logging.exception(e)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "function": "MigratedFile.create_or_update - save_file",
                    "collection": str(collection),
                },
            )
            raise e

        try:
            obj.save()
        except Exception as e:
            logging.info(f"MigratedFile.create_or_update - {source_path} - save")
            logging.exception(e)
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "function": "MigratedFile.create_or_update - save",
                    "collection": str(collection),
                },
            )
            raise e
        return obj

    @classmethod
    def find(cls, collection, xlink_href, journal_acron):
        try:
            # dirname = os.path.dirname(xlink_href)
            basename = os.path.basename(xlink_href)
            name, ext = os.path.splitext(basename)

            # issue_folder = dirname.split("/")[-1]
            # issue_folder__name = os.path.join(issue_folder, name)

            return cls.objects.filter(
                # Q(original_href__contains=issue_folder__name + "."),
                collection=collection,
                original_href__contains=f"/{journal_acron}/",
                original_name__contains=name+".",
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "migrations.models.MigratedFile.find",
                    "xlink_href": xlink_href,
                    "journal_acron": journal_acron,
                    "collection": str(collection),
                },
            )
            return []

    def get_original_href(self, original_path):
        try:
            return original_path[original_path.find("/") :]
        except:
            pass

    def save_file(self, name, content, save=False):
        try:
            self.file.delete(save=save)
        except Exception as e:
            pass
        self.file.save(name, ContentFile(content))

    def is_up_to_date(self, file_datetime_iso):
        return bool(self.file_datetime_iso and self.file_datetime_iso == file_datetime_iso)

    @property
    def text(self):
        try:
            if self.component_type == "html":
                try:
                    with open(self.file.path, mode="r", encoding="iso-8859-1") as fp:
                        return fp.read()
                except:
                    with open(self.file.path, mode="r", encoding="utf-8") as fp:
                        return fp.read()
            if self.component_type == "xml":
                with open(self.file.path, mode="r", encoding="utf-8") as fp:
                    return fp.read()
        except Exception as e:
            return None


class MigratedJournal(MigratedData):
    panels = [
        FieldPanel("isis_updated_date"),
        FieldPanel("isis_created_date"),
        FieldPanel("data"),
    ]

    @classmethod
    def get_data_from_classic_website(cls, data):
        return classic_ws.Journal(data)

    @property
    def journal_acron(self):
        j = classic_ws.Journal(self.data)
        return j.acronym


class MigratedIssue(MigratedData):
    panels = [
        FieldPanel("isis_updated_date"),
        FieldPanel("isis_created_date"),
        FieldPanel("data"),
    ]

    @classmethod
    def get_data_from_classic_website(cls, data):
        return classic_ws.Issue(data)

    @property
    def issue_folder(self):
        issue = classic_ws.Issue(self.data)
        return issue.issue_label


class MigratedArticle(MigratedData):
    file_type = models.CharField(
        _("File type"),
        max_length=4,
        default=None,
        null=True,
        blank=True,
    )

    panels = [
        FieldPanel("file_type"),
        FieldPanel("isis_updated_date"),
        FieldPanel("isis_created_date"),
        FieldPanel("data"),
    ]

    def __str__(self):
        document = self.document
        return f"{document.journal.acronym} {document.issue.issue_label} {document.filename_without_extension}"

    @classmethod
    def get_data_from_classic_website(cls, data):
        return classic_ws.Document(data)

    @property
    def document(self):
        return classic_ws.Document(self.data)

    @property
    def n_paragraphs(self):
        return len(self.document.p_records or [])

    @property
    def pkg_name(self):
        return self.document.filename_without_extension

    @property
    def path(self):
        document = self.document
        return f"{document.journal.acronym}/{document.issue.issue_label}/{document.filename_without_extension}"


class JournalAcronIdFile(CommonControlField, ClusterableModel):
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )
    journal = models.ForeignKey(
        "journal.Journal", on_delete=models.SET_NULL, null=True, blank=True
    )
    journal_acron = models.CharField(max_length=16, null=True, blank=True)
    file = models.FileField(
        upload_to=migrated_files_directory_path, null=True, blank=True
    )
    # classic_website/spa/scielo_www/hercules-spa/new_platform/bases_for_upload/bases-work/acron/file_asdg.id
    source_path = models.CharField(_("Source"), max_length=200, null=True, blank=True)

    file_size = models.IntegerField(null=True, blank=True)

    autocomplete_search_field = "source_path"

    def __str__(self):
        return f"{self.source_path}"

    def autocomplete_label(self):
        return f"{self.source_path}"

    class Meta:
        unique_together = [
            ("collection", "journal", "source_path"),
            ("collection", "journal_acron", "source_path"),
        ]
        indexes = [
            models.Index(fields=["source_path"]),
        ]

    @classmethod
    def has_changes(cls, user, collection, journal_acron, file_path, force_update):
        if not force_update:
            try:
                file_size = JournalAcronIdFile.get_file_size(file_path)
                if cls.objects.filter(
                    collection=collection, source_path=file_path, file_size=file_size
                ).exists():
                    return False
            except cls.DoesNotExist:
                pass
            except cls.MultipleObjectsReturned:
                pass

        cls.create_or_update(
            user=user,
            collection=collection,
            journal_acron=journal_acron,
            source_path=file_path,
            force_update=force_update,
        )
        return True

    @classmethod
    def get(
        cls,
        collection,
        source_path,
    ):
        if collection and source_path:
            return cls.objects.get(collection=collection, source_path=source_path)

        d = dict(
            collection=collection,
            source_path=source_path,
        )
        raise ValueError(f"JournalAcronIdFile.create requires all parameters. Got {d}")

    @classmethod
    def create(
        cls,
        user,
        collection,
        journal_acron,
        source_path,
    ):
        if not user and not journal_acron and not collection and not source_path:
            d = dict(
                user=user,
                collection=collection,
                journal_acron=journal_acron,
                source_path=source_path,
            )
            raise ValueError(
                f"JournalAcronIdFile.create requires all parameters. Got {d}"
            )

        try:
            obj = cls()
            obj.collection = collection
            obj.journal_acron = journal_acron
            obj.source_path = source_path
            obj.creator = user
            obj.file_size = JournalAcronIdFile.get_file_size(source_path)
            obj.save()

            with open(source_path, "rb") as fp:
                basename = os.path.basename(source_path)
                obj.save_file(basename, fp.read())
                obj.save()

            return obj
        except IntegrityError:
            return cls.get(collection, source_path)

    def save_file(self, name, content, save=False):
        try:
            self.file.delete(save=save)
        except Exception as e:
            pass
        self.file.save(name, ContentFile(content))

    @classmethod
    def create_or_update(
        cls,
        user,
        collection,
        journal_acron,
        source_path,
        force_update=None,
    ):
        try:
            obj = cls.get(collection, source_path)
            if journal_acron and obj.journal_acron is None:
                obj.journal_acron = journal_acron
                obj.save()
            file_size = JournalAcronIdFile.get_file_size(source_path)

            doit = any((force_update, not obj.is_up_to_date(file_size)))
            if not doit:
                return obj

            obj.updated_by = user
            obj.updated = datetime.utcnow()
            obj.file_size = file_size

            with open(source_path, "rb") as fp:
                basename = os.path.basename(source_path)
                obj.save_file(basename, fp.read())
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(user, collection, journal_acron, source_path)

    @staticmethod
    def get_file_size(source_path):
        return os.stat(source_path).st_size

    def is_up_to_date(self, file_size):
        try:
            logging.info(f"{self.file.path} {file_size} {self.file_size}")
            return bool(self.file_size and self.file_size == file_size)
        except Exception as e:
            return False


class IdFileRecord(CommonControlField, Orderable):
    parent = ParentalKey(
        JournalAcronIdFile, on_delete=models.CASCADE, related_name="id_file_records"
    )
    data = models.JSONField()
    item_pid = models.CharField(_("PID"), max_length=23)
    item_type = models.CharField(_("Type"), max_length=10)
    # issue_folder = models.CharField(_("Issue folder"), max_length=30)
    # article_filename = models.CharField(
    #     _("Filename"), max_length=40, null=True, blank=True
    # )
    # article_filetype = models.CharField(
    #     _("File type"), max_length=4, null=True, blank=True
    # )
    # processing_date = models.CharField(max_length=8, null=True, blank=True)
    # deleted = models.BooleanField(default=False)
    todo = models.BooleanField(default=True)

    panels = [
        FieldPanel("item_pid", read_only=True),
        FieldPanel("item_type", read_only=True),
        FieldPanel("data", read_only=True),
    ]

    class Meta:
        unique_together = [("parent", "item_type", "item_pid")]
        indexes = [
            models.Index(fields=["parent"]),
            models.Index(fields=["item_pid"]),
            models.Index(fields=["item_type"]),
        ]

    def __str__(self):
        return f"{self.item_pid}"

    @classmethod
    def get(
        cls,
        parent,
        item_type,
        item_pid,
    ):
        if parent and item_type and item_pid:
            return cls.objects.get(
                parent=parent, item_type=item_type, item_pid=item_pid
            )
        d = dict(
            parent=parent,
            item_type=item_type,
            item_pid=item_pid,
        )
        raise ValueError(f"IdFileRecord.get requires all parameters. Got {d}")

    @classmethod
    def create(
        cls,
        user,
        parent,
        item_type,
        item_pid,
        data,
        todo,
    ):
        if not user and not item_type and not parent and not item_pid:
            d = dict(
                user=user,
                parent=parent,
                item_type=item_type,
                item_pid=item_pid,
            )
            raise ValueError(f"IdFileRecord.create requires all parameters. Got {d}")

        try:
            obj = cls(
                creator=user,
                parent=parent,
                item_type=item_type,
                item_pid=item_pid,
                data=data,
                todo=todo,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(parent, item_type, item_pid)
        except DataError as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            UnexpectedEvent.create(
                e=e,
                exc_traceback=exc_traceback,
                detail={
                    "task": "migrations.models.IdFileRecord.create",
                    "user_id": user.id,
                    "username": user.username,
                    "item_type": item_type,
                    "item_pid": item_pid,
                    "data": data,
                },
            )

    @classmethod
    def create_or_update(
        cls,
        user,
        parent,
        item_type,
        item_pid,
        data,
        force_update=None,
        todo=None,
    ):
        if not user and not item_type and not parent and not item_pid:
            d = dict(
                user=user,
                parent=parent,
                item_type=item_type,
                item_pid=item_pid,
            )
            raise ValueError(f"IdFileRecord.create requires all parameters. Got {d}")

        try:
            obj = cls.get(parent, item_type, item_pid)
            if not force_update:
                if data == obj.data:
                    return obj
            obj.updated_by = user
            obj.updated = datetime.utcnow()
            obj.data = data
            obj.todo = todo
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(
                user,
                parent,
                item_type,
                item_pid,
                data,
                todo,
            )

    def get_record_data(self, journal_data=None, issue_data=None):
        data = {}
        data["title"] = journal_data
        if not issue_data:
            issue_data = (
                IdFileRecord.objects.filter(
                    parent=self.parent,
                    item_pid=self.item_pid[1:-5],
                    item_type="issue",
                )
                .first()
                .data
            )
        data["issue"] = issue_data
        try:
            p_records = (
                IdFileRecord.objects.filter(
                    parent=self.parent,
                    item_pid=self.item_pid,
                    item_type="paragraph",
                )
                .first()
                .data
            )
        except AttributeError:
            p_records = []
        data["article"] = self.data + list(p_records)
        return {
            "data": data,
            "pid": self.item_pid,
            "todo": self.todo,
        }

    @classmethod
    def document_records_to_migrate(cls, collection, issue_pid, force_update):
        params = {}
        if collection:
            params["parent__collection"] = collection
        if issue_pid:
            params["item_pid__startswith"] = f"S{issue_pid}"
        if not force_update:
            params["todo"] = True

        logging.info(f"IdFileRecord.document_records_to_migrate {params}")
        return cls.objects.filter(item_type="article", **params)
