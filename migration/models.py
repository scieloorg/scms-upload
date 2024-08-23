import logging
import os
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import IntegrityError, models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from scielo_classic_website import classic_ws
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from collection.models import Collection
from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from tracker import choices as tracker_choices

from . import exceptions


def now():
    return datetime.utcnow().isoformat().replace(":", "-").replace(".", "-")


class MigratedFileCreateOrUpdateError(Exception):
    ...


class MigratedDocumentHTMLForbiddenError(Exception):
    ...


class MigrationError(Exception):
    ...


def modified_date(file_path):
    try:
        s = os.stat(file_path)
        return datetime.fromtimestamp(s.st_mtime)
    except Exception as e:
        return datetime.utcnow()


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
    cisis_path = models.CharField(
        _("Cisis path"),
        max_length=255,
        null=True,
        blank=True,
        help_text=_("Cisis path where there are CISIS utilities such as mx and i2id"),
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
        cisis_path=None,
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
            obj.cisis_path = cisis_path
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
        classic_ws_obj = cls.get_data_from_classic_website(data)

        status = tracker_choices.PROGRESS_STATUS_TODO

        try:
            if classic_ws_obj.is_press_release:
                status = tracker_choices.PROGRESS_STATUS_IGNORED
        except AttributeError:
            pass

        return cls.create_or_update_migrated_data(
            collection=collection,
            pid=pid,
            user=user,
            isis_created_date=classic_ws_obj.isis_created_date,
            isis_updated_date=classic_ws_obj.isis_updated_date,
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


def migrated_files_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>

    try:
        path = instance.original_path
    except (AttributeError, TypeError) as e:
        path = instance.source_path

    try:
        return f"classic_website/{instance.collection.acron}/{path}"
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
    original_path = models.TextField(_("Original Path"), null=True, blank=True)

    # pt_a01.pdf
    original_name = models.TextField(_("Original name"), null=True, blank=True)

    file_date = models.DateField(null=True, blank=True)

    # /pdf/acron/volnum/pt_a01.pdf
    original_href = models.TextField(_("Original href"), null=True, blank=True)

    component_type = models.CharField(
        _("Component type"), max_length=16, null=True, blank=True
    )
    lang = models.CharField(_("Language"), max_length=2, null=True, blank=True)
    pkg_name = models.CharField(_("Pkg name"), max_length=32, null=True, blank=True)
    part = models.CharField(_("Part"), max_length=1, null=True, blank=True)

    autocomplete_search_field = "original_path"

    def __str__(self):
        return f"{self.collection} {self.original_path}"

    def autocomplete_label(self):
        return f"{self.collection} {self.original_path}"

    panels = [
        FieldPanel("file"),
        FieldPanel("file_date", read_only=True),
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
    def get(
        cls,
        collection=None,
        original_path=None,
    ):
        if collection and original_path:
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
    ):
        if not source_path and not collection and not original_path:
            raise ValueError(
                "MigratedFile.create_or_update requires source_path, collection, original_path"
            )

        basename = os.path.basename(source_path)
        file_date = modified_date(source_path)

        try:
            obj = cls.get(collection, original_path)

            if not force_update and obj.is_up_to_date(file_date):
                # is already done
                logging.info("it is already up-to-date")
                return obj

            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.collection = collection
            obj.original_path = original_path
            obj.original_name = basename
            obj.original_href = obj.get_original_href(original_path)
            obj.creator = user

        obj.pkg_name = pkg_name or obj.pkg_name
        obj.lang = lang or obj.lang
        obj.part = part or obj.part
        obj.component_type = component_type or obj.component_type
        obj.file_date = file_date

        with open(source_path, "rb") as fp:
            content = fp.read()
        obj.save_file(basename, content, bool(original_path))
        obj.save()

        return obj

    @classmethod
    def find(cls, collection, xlink_href, subdir):
        original = xlink_href
        path = xlink_href

        if "/img/revistas/" in path and not path.startswith("/img/revistas/"):
            path = path[path.find("/img/revistas") :]

        if "/img/revistas/" not in path:
            path = os.path.join("/img/revistas", subdir, path)

        if ".." in path:
            path = os.path.normpath(path)

        name, ext = os.path.splitext(path)

        return cls.objects.filter(
            Q(original_href=path) | Q(original_href__startswith=name + "."),
            collection=collection,
        )

    def get_original_href(self, original_path):
        try:
            return original_path[original_path.find("/") :]
        except:
            pass

    def save_file(self, name, content, delete=False):
        try:
            self.file.delete(save=True)
        except Exception as e:
            pass
        self.file.save(name, ContentFile(content))

    def is_up_to_date(self, file_date):
        return bool(self.file_date and self.file_date == file_date)

    @property
    def text(self):
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
    # bases/pdf/acron/volnum/pt_a01.pdf
    source_path = models.TextField(_("Source"), null=True, blank=True)

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
                obj.save_file(basename, fp.read(), True)
                obj.save()

            return obj
        except IntegrityError:
            return cls.get(collection, source_path)

    def save_file(self, name, content, delete=False):
        try:
            self.file.delete(save=True)
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
                logging.info(f"skip update {source_path}")
                return obj

            obj.updated_by = user
            obj.updated = datetime.utcnow()
            obj.file_size = file_size
            obj.save()

            with open(source_path, "rb") as fp:
                basename = os.path.basename(source_path)
                obj.save_file(basename, fp.read(), True)
                obj.save()

            obj.id_file_records.all().update(deleted=True)
            return obj
        except cls.DoesNotExist:
            return cls.create(user, collection, journal_acron, source_path)

    @staticmethod
    def get_file_size(source_path):
        return os.stat(source_path).st_size

    def is_up_to_date(self, file_size):
        logging.info(f"{self.file.path} {file_size} {self.file_size}")
        return bool(self.file_size and self.file_size == file_size)

    @classmethod
    def modified_articles(cls, collection=None, journal_acron=None, issue_folder=None):
        params = {}
        if collection:
            params["collection"] = collection
        if journal_acron:
            params["journal_acron"] = journal_acron

        for journal_acron_id_file in cls.objects.filter(**params):
            from_datetime = (
                journal_acron_id_file.updated or journal_acron_id_file.created
            )
            items = IdFileRecord.modified_records(
                collection=journal_acron_id_file.collection,
                journal_acron=journal_acron_id_file.journal_acron,
                issue_folder=issue_folder,
                from_datetime=from_datetime,
            )
            if items.exists():
                yield from items

    @classmethod
    def issues_with_modified_articles(cls, collection=None, journal_acron=None):
        params = {}
        if collection:
            params["collection"] = collection
        if journal_acron:
            params["journal_acron"] = journal_acron

        for journal_acron_id_file in cls.objects.filter(**params):
            from_datetime = (
                journal_acron_id_file.updated or journal_acron_id_file.created
            )
            items = IdFileRecord.modified_records(
                collection=journal_acron_id_file.collection,
                journal_acron=journal_acron_id_file.journal_acron,
                from_datetime=from_datetime,
            )
            if items.exists():
                yield from items.values(
                    "parent__journal_acron", "parent__collection__id", "issue_folder"
                ).distinct()

    @classmethod
    def journals_with_modified_articles(cls, collection=None, journal_acron=None):
        params = {}
        if collection:
            params["collection"] = collection
        if journal_acron:
            params["journal_acron"] = journal_acron

        for journal_acron_id_file in cls.objects.filter(**params):
            from_datetime = (
                journal_acron_id_file.updated or journal_acron_id_file.created
            )
            items = IdFileRecord.modified_records(
                collection=journal_acron_id_file.collection,
                journal_acron=journal_acron_id_file.journal_acron,
                from_datetime=from_datetime,
            )
            if items.exists():
                yield journal_acron_id_file


class IdFileRecord(CommonControlField, Orderable):
    parent = ParentalKey(
        JournalAcronIdFile, on_delete=models.CASCADE, related_name="id_file_records"
    )
    data = models.JSONField()
    item_pid = models.CharField(_("PID"), max_length=23)
    item_type = models.CharField(_("Type"), max_length=10)
    issue_folder = models.CharField(_("Issue folder"), max_length=30)
    article_filename = models.CharField(
        _("Filename"), max_length=30, null=True, blank=True
    )
    article_filetype = models.CharField(
        _("File type"), max_length=4, null=True, blank=True
    )
    processing_date = models.CharField(max_length=8, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    panels = [
        FieldPanel("item_pid", read_only=True),
        FieldPanel("item_type", read_only=True),
        FieldPanel("issue_folder", read_only=True),
        FieldPanel("article_filename", read_only=True),
        FieldPanel("article_filetype", read_only=True),
        FieldPanel("data", read_only=True),
    ]

    class Meta:
        unique_together = [("parent", "item_type", "item_pid")]
        indexes = [
            models.Index(fields=["parent"]),
            models.Index(fields=["item_pid"]),
            models.Index(fields=["item_type"]),
            models.Index(fields=["issue_folder"]),
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
        issue_folder,
        article_filename=None,
        article_filetype=None,
        processing_date=None,
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
                issue_folder=issue_folder,
                article_filename=article_filename,
                article_filetype=article_filetype,
                processing_date=processing_date,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(parent, item_type, item_pid)

    @classmethod
    def create_or_update(
        cls,
        user,
        parent,
        item_type,
        item_pid,
        data,
        issue_folder,
        article_filename=None,
        article_filetype=None,
        processing_date=None,
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
            if processing_date and obj.processing_date == processing_date:
                obj.deleted = False
                obj.save()
                return obj
            obj.updated_by = user
            obj.updated = datetime.utcnow()
            obj.data = data
            obj.issue_folder = issue_folder
            obj.article_filename = article_filename
            obj.article_filetype = article_filetype
            obj.processing_date = processing_date
            obj.deleted = False
            obj.save()
            return obj
        except cls.DoesNotExist:
            return cls.create(
                user,
                parent,
                item_type,
                item_pid,
                data,
                issue_folder,
                article_filename,
                article_filetype,
                processing_date,
            )

    def get_record_data(self, journal_data=None, issue_data=None):
        data = {}
        data["title"] = journal_data
        if not issue_data:
            issue_data = (
                IdFileRecord.objects.filter(
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
            "issue_folder": self.issue_folder,
            "deleted": self.deleted,
        }

    @classmethod
    def modified_records(
        cls, collection=None, journal_acron=None, issue_folder=None, from_datetime=None
    ):
        params = {}
        if collection:
            params["parent__collection"] = collection
        if journal_acron:
            params["parent__journal_acron"] = journal_acron
        if issue_folder:
            params["issue_folder"] = issue_folder
        if from_datetime:
            return cls.objects.filter(
                Q(created__gte=from_datetime) | Q(updated__gte=from_datetime),
                item_type="article",
                **params,
            )
        else:
            return cls.objects.filter(item_type="article", **params)
