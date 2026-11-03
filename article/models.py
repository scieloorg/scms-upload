import logging
import os
import traceback
from datetime import datetime, timezone
from functools import cached_property

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models, transaction
from django.core.files.base import ContentFile
from django.db.models import Count, Max, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.models.article_titles import ArticleTitles
from packtools.sps.models.article_toc_sections import ArticleTocSections
from packtools.sps.pid_provider.xml_sps_lib import XMLWithPre
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, TabbedInterface, ObjectList
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.forms import CoreAdminModelForm
from core.utils.requester import NonRetryableError
from core.widgets import ReadOnlyPrettyJSONWidget
from migration import choices as migration_choices
from migration.models import ClassicWebsiteConfiguration
from article.page_checker import check_url, check_content, format_url, format_classic_url
from article.forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from collection.choices import PUBLIC
from collection.models import Language, Collection, WebSiteConfiguration
from core.models import CommonControlField, HTMLTextModel
from doi.models import DOIWithLang
from issue.models import TOC, Issue, TocSection
from journal.models import Journal, JournalSection, OfficialJournal
from package.models import SPSPkg
from pid_provider.models import CollectionPidV2, PidProviderXML
from pid_provider.choices import PPXML_STATUS_INVALID
from . import choices
from package import collection_pid_v2_completion as completion

from .exceptions import (
    ArticleSourcePidV3MismatchError,
    RequestXMLException,
    UnableToRegisterPIDError,
    XMLException,
)
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()


DATA_AVAILABILITY_XPATH = (
    './body//sec[@sec-type="data-availability"]'
    ' | ./body//fn[@fn-type="data-availability"]'
    ' | ./back//sec[@sec-type="data-availability"]'
    ' | ./back//fn[@fn-type="data-availability"]'
)


def get_data_availability_status(xmltree):
    """
    Obtém o status de disponibilidade de dados do artigo principal
    (sub-articles são desconsiderados, pois traduções repetem a declaração).

    Retorna o primeiro specific-use reconhecido; DAS_INVALID se há declaração
    sem specific-use reconhecido; DAS_ABSENT se não há declaração.
    """
    if xmltree is None:
        return None
    root = xmltree.find(".") if hasattr(xmltree, "getroot") else xmltree
    nodes = root.xpath(DATA_AVAILABILITY_XPATH)
    if not nodes:
        return choices.DAS_ABSENT
    valid = dict(choices.DATA_AVAILABILITY_STATUS)
    for node in nodes:
        specific_use = (node.get("specific-use") or "").strip()
        if specific_use in valid and specific_use not in (
            choices.DAS_ABSENT,
            choices.DAS_INVALID,
        ):
            return specific_use
    return choices.DAS_INVALID


def get_compiled_status(status_list):
    """Recalcula status a partir das ArticleWebPage filhas."""
    
    if not status_list:
        return choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED
    if len(status_list) == 1:
        return status_list[0]
    order = (
        choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
        choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH,
        choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE,
        choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE,
    )
    for item in order:
        if item in status_list:
            return item


def get_pid_status_from_webpage_status(website, article_status: str) -> str:
    """
    Realiza a correspondência entre o status da página e o status do PID.
    """
    mapping = {
        "CLASSIC": {
            choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE: migration_choices.PID_STATUS_CLASSIC_FOUND,
            choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT: migration_choices.PID_STATUS_CLASSIC_MATCHED,
            choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH: migration_choices.PID_STATUS_CLASSIC_MISMATCHED,
            choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE: migration_choices.PID_STATUS_CLASSIC_NOT_FOUND,
            choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED: migration_choices.PID_STATUS_UNKNOWN,
        },
        "PUBLIC": {
            choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE: migration_choices.PID_STATUS_PUBLISHED,
            choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT: migration_choices.PID_STATUS_PUBLIC_VALID,
            choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH: migration_choices.PID_STATUS_PUBLIC_MISMATCHED,
            choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE: migration_choices.PID_STATUS_PUBLIC_NOT_FOUND,
            choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED: migration_choices.PID_STATUS_UNKNOWN,
        },
    }


    # Retorna o valor mapeado ou o status de 'not found' por padrão
    return mapping.get(website).get(article_status) or migration_choices.PID_STATUS_UNKNOWN


# ============================================================
# Article
# ============================================================


class ArticleQuerySet(models.QuerySet):
    """QuerySet customizado para Article com select_related otimizado."""
    
    def with_sps_pkg(self):
        """Inclui select_related de sps_pkg por padrão."""
        return self.select_related("sps_pkg")


class ArticleManager(models.Manager):
    """Manager customizado para Article com select_related otimizado."""
    
    def get_queryset(self):
        """
        Por padrão, inclui select_related do pacote e do documento na
        coleção (collection_pid_v2) em todas as queries.
        """
        return ArticleQuerySet(self.model, using=self._db).select_related(
            "sps_pkg",
            "collection_pid_v2__collection",
            "journal",
            "issue",
        )


class Article(ClusterableModel, CommonControlField):
    """
    Modelo que representa um artigo no contexto de Upload.

    No contexto de Upload, Article deve conter o mínimo de campos,
    suficiente para o processo de ingresso/validações, pois os dados
    devem ser obtidos do XML.

    Artigo presente em mais de uma coleção tem um Article por coleção,
    com o mesmo pid_v3, pois o XML (sps_pkg), o pid v2 e o acrônimo do
    periódico podem diferir por coleção.

    pid_v3 e pid_v2 não são únicos: o mesmo documento tem um Article por
    coleção e o pid v2 pode se repetir entre coleções. Buscas devem
    combiná-los com a coleção.

    collection_pid_v2 (documento na coleção) é o vínculo com a coleção.
    Artigos anteriores à separação por coleção não o têm; são vinculados
    pela migração article 0014_complete_collection_pid_v2 e, o que ficar
    pendente, pela tarefa article.tasks.task_complete_collection_pid_v2
    (ver complete_collection_pid_v2). Quando vinculado,
    pp_xml, pid_v2 e sps_pkg são mantidos iguais aos de collection_pid_v2.
    """

    # Manager customizado com select_related otimizado
    objects = ArticleManager()

    pp_xml = models.ForeignKey(
        PidProviderXML,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    sps_pkg = models.ForeignKey(
        SPSPkg, blank=True, null=True, on_delete=models.SET_NULL
    )
    pid_v3 = models.CharField(
        _("PID v3"), max_length=23, blank=True, null=True
    )
    pid_v2 = models.CharField(
        _("PID v2"), max_length=23, blank=True, null=True
    )
    # documento na coleção; vazio para artigos ainda não vinculados
    # (anteriores à separação por coleção) ou sem coleção (ex.: ingresso)
    collection_pid_v2 = models.OneToOneField(
        CollectionPidV2,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="article",
    )
    article_type = models.CharField(
        _("Article type"),
        max_length=32,
        choices=choices.ARTICLE_TYPE,
        blank=True,
        null=True,
    )
    status = models.CharField(
        _("Article status"),
        max_length=32,
        choices=choices.ARTICLE_STATUS,
        blank=True,
        null=True,
    )
    position = models.PositiveIntegerField(_("Position"), blank=True, null=True)
    first_publication_date = models.DateField(null=True, blank=True)
    data_availability_status = models.CharField(
        _("Data availability status"),
        max_length=32,
        choices=choices.DATA_AVAILABILITY_STATUS,
        blank=True,
        null=True,
    )
    first_pubdate_iso = models.CharField(
        _("First publication date ISO"), max_length=10, blank=True, null=True
    )
    elocation_id = models.CharField(
        _("Elocation ID"), max_length=64, blank=True, null=True
    )
    fpage = models.CharField(_("First page"), max_length=16, blank=True, null=True)
    fpage_seq = models.CharField(
        _("First page seq"), max_length=16, blank=True, null=True
    )
    lpage = models.CharField(_("Last page"), max_length=16, blank=True, null=True)

    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.SET_NULL)
    journal = models.ForeignKey(
        Journal, blank=True, null=True, on_delete=models.SET_NULL
    )
    related_items = models.ManyToManyField(
        "self",
        symmetrical=False,
        through="RelatedItem",
        related_name="related_to",
    )
    sections = models.ManyToManyField(JournalSection, verbose_name=_("sections"))
    panel_article_ids = MultiFieldPanel(
        heading="Article identifiers", classname="collapsible"
    )
    panel_article_ids.children = [
        FieldPanel("collection_pid_v2", read_only=True),
        FieldPanel("pid_v2", read_only=True),
        FieldPanel("pid_v3", read_only=True),
    ]

    panel_article_details = MultiFieldPanel(
        heading="Article details", classname="collapsible"
    )
    panel_article_details.children = [
        FieldPanel("first_pubdate_iso", read_only=True),
        FieldPanel("data_availability_status", read_only=True),
        FieldPanel("article_type", read_only=True),
        FieldPanel("status", read_only=True),
        InlinePanel(relation_name="title_with_lang", label="Title with Language"),
        FieldPanel("elocation_id", read_only=True),
        FieldPanel("fpage", read_only=True),
        FieldPanel("lpage", read_only=True),
    ]

    panel_collections = MultiFieldPanel(
        heading=_("Collections"), classname="collapsible"
    )
    panel_collections.children = [
        InlinePanel(relation_name="article_collections", label="Collections"),
    ]
    panel_webpages = MultiFieldPanel(
        heading=_("Webpages"), classname="collapsible"
    )
    panel_webpages.children = [
        InlinePanel(relation_name="pages", label=_("Web pages")),
    ]

    edit_handler = TabbedInterface(
        [
            ObjectList(
                [panel_article_ids, panel_article_details],
                heading="Article",
            ),
            ObjectList(
                [FieldPanel("issue", read_only=True)],
                heading="Issue",
            ),
            ObjectList(
                [panel_collections],
                heading="Collections",
            ),
            ObjectList(
                [panel_webpages],
                heading=_("Webpages"),
            ),
        ]
    )

    base_form_class = ArticleForm

    class Meta:
        constraints = [
            # artigos anteriores à separação por coleção; os demais são
            # únicos por collection_pid_v2 (documento na coleção)
            models.UniqueConstraint(
                fields=["pid_v3"],
                condition=Q(collection_pid_v2__isnull=True),
                name="article_unique_pid_v3_without_collection",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["pid_v3"]),
            models.Index(fields=["pid_v2"]),
        ]
        ordering = ["position", "fpage", "-first_pubdate_iso"]
        permissions = (
            (MAKE_ARTICLE_CHANGE, _("Can make article change")),
            (REQUEST_ARTICLE_CHANGE, _("Can request article change")),
        )

    # ── str / autocomplete ──

    @classmethod
    def autocomplete_custom_queryset_filter(cls, term):
        return cls.objects.filter(
            Q(sps_pkg__sps_pkg_name__endswith=term)
            | Q(title_with_lang__text__icontains=term)
        )

    def autocomplete_label(self):
        return str(self)

    def __str__(self):
        try:
            return self.sps_pkg.sps_pkg_name
        except AttributeError:
            return self.pid_v3 or self.pid_v2 or f"Article {self.pk}"

    # ── documento na coleção (collection_pid_v2) ──

    LINK_FIELDS = ["collection_pid_v2", "pp_xml", "pid_v2", "sps_pkg"]

    @property
    def collection(self):
        return self.collection_pid_v2 and self.collection_pid_v2.collection

    def set_collection_pid_v2(self, collection_pid_v2):
        """
        Vincula o artigo ao documento na coleção e mantém pp_xml, pid_v2 e
        sps_pkg iguais aos do documento na coleção
        """
        self.collection_pid_v2 = collection_pid_v2
        if not collection_pid_v2:
            return
        self.pp_xml_id = collection_pid_v2.pid_provider_xml_id
        self.pid_v2 = collection_pid_v2.pid_v2 or self.pid_v2
        try:
            self.sps_pkg = collection_pid_v2.sps_pkg
        except ObjectDoesNotExist:
            pass

    def get_pp_xml_id(self):
        """
        PidProviderXML do artigo: o do documento na coleção ou, na falta
        dele, pp_xml ou o único do pid_v3 (legado)
        """
        if self.collection_pid_v2_id:
            return self.collection_pid_v2.pid_provider_xml_id
        return completion.get_unique_ppx_id(django_apps, self.pp_xml_id, self.pid_v3)

    def get_pid_v2(self):
        """
        PID v2 do artigo: o do documento na coleção ou, na falta dele,
        pid_v2 (legado)
        """
        if self.collection_pid_v2_id and self.collection_pid_v2.pid_v2:
            return self.collection_pid_v2.pid_v2
        return self.pid_v2

    def get_collection_pid_v2_without_sps_pkg(self, user):
        """
        Documento na coleção do artigo sem pacote, se não houver
        ambiguidade
        (ver package.collection_pid_v2_completion.get_article_collection_pid_v2_without_sps_pkg)

        Retorna (collection_pid_v2, None) ou (None, motivo)
        """
        return completion.get_article_collection_pid_v2_without_sps_pkg(
            django_apps, self, user and user.id
        )

    def complete_collection_pid_v2(self, user=None, sync_fields=False):
        """
        Vincula ao documento na coleção (collection_pid_v2) o artigo
        anterior à separação por coleção, somente se não houver ambiguidade
        (ver package.collection_pid_v2_completion.link_article)

        sync_fields: se False, pp_xml, pid_v2 e sps_pkg (legado) são
        mantidos e somente os vazios são completados

        Retorna o resultado: "linked", "already_linked", "no_ppx",
        "no_collection" ou "taken" (documento na coleção já tem outro
        artigo)
        """
        return completion.link_article(
            django_apps, self, user and user.id, sync_fields
        )

    def complete_journal_acron(self, collection_pid_v2):
        """
        Completa o acrônimo do periódico no documento na coleção com o do
        periódico do artigo na coleção (JournalProc)
        """
        completion.complete_journal_acron(django_apps, self, collection_pid_v2)

    @classmethod
    def complete_collection_pid_v2_batch(cls, user, last_id=0, batch_size=100):
        """
        Vincula ao documento na coleção um lote de artigos ainda não
        vinculados, com id > last_id, em ordem de id
        (ver package.collection_pid_v2_completion.complete_batch)

        Retorna (stats, last_id, done)
        """
        return completion.complete_batch(
            django_apps, "Article", user and user.id, last_id, batch_size
        )

    @classmethod
    def _filter_in_collection(cls, queryset, collection):
        """
        Artigos de queryset que pertencem à coleção: os vinculados ao
        documento na coleção e os ainda não vinculados (legados, pendentes
        da migração article 0014_complete_collection_pid_v2 / da tarefa
        article.tasks.task_complete_collection_pid_v2)
        """
        return queryset.filter(
            Q(collection_pid_v2__collection=collection)
            | Q(collection_pid_v2__isnull=True)
        )

    @classmethod
    def _get_in_collection(cls, queryset, collection):
        """
        Obtém o artigo de queryset que pertence à coleção, priorizando o
        vinculado ao documento na coleção
        """
        qs = cls._filter_in_collection(queryset, collection)
        try:
            return qs.get(collection_pid_v2__collection=collection)
        except cls.DoesNotExist:
            return qs.get(collection_pid_v2__isnull=True)

    # ── properties delegadas ao sps_pkg ──

    @property
    def pdfs(self):
        return self.sps_pkg.pdfs

    @property
    def htmls(self):
        return self.sps_pkg.htmls

    @property
    def xml(self):
        return self.sps_pkg.xml_uri

    @property
    def is_public(self):
        pubdate = self.get_first_pubdate()
        return bool(
            pubdate and pubdate <= datetime.now(timezone.utc).isoformat()[:10]
        )

    def get_first_pubdate(self):
        if self.first_pubdate_iso:
            return self.first_pubdate_iso
        try:
            value = self.first_publication_date.isoformat()[:10]
            self.first_pubdate_iso = value
            self.save()
            return value
        except (TypeError, AttributeError):
            return None

    @property
    def data(self):
        return dict(
            xml=self.sps_pkg and self.sps_pkg.xml_uri,
            collection=self.collection and self.collection.acron,
            issue=self.issue.data,
            journal=self.journal.data,
            pid_v3=self.pid_v3,
            created=self.created.isoformat(),
            updated=self.updated.isoformat(),
        )

    @property
    def article_langs(self):
        langs = set()
        for item in self.sps_pkg.htmls:
            if item.get("lang"):
                langs.add(item.get("lang"))
        for item in self.sps_pkg.pdfs:
            if item.get("lang"):
                langs.add(item.get("lang"))
        return list(langs)

    # ── get / dedup ──

    @classmethod
    def get(
        cls, pid_v2=None, sps_pkg_name=None, pid_v3=None, sps_pkg=None, collection=None
    ):
        """
        Obtém o Article do documento na coleção.

        Há um Article por documento na coleção (mesmo pid_v3 em coleções
        diferentes; pid_v2 e sps_pkg_name dependem da coleção), então
        pid_v3, pid_v2 e sps_pkg_name devem ser combinados com collection.
        sps_pkg dispensa collection, pois é único por documento na coleção.

        Prioriza as chaves determinísticas (pid_v3, pid_v2); sps_pkg_name
        (identificação humana, depende de vários dados do XML) é usado
        somente na falta delas.

        Artigos ainda não vinculados ao documento na coleção são retornados
        sem completar o vínculo (ver _get_in_collection).
        """
        if sps_pkg:
            qs = cls.objects.filter(sps_pkg=sps_pkg)
            if collection:
                return cls._get_in_collection(qs, collection)
            return qs.get()

        if not collection:
            raise ValueError(
                "Article.get requires collection with pid_v3 or pid_v2 or sps_pkg_name, or sps_pkg"
            )
        if not (pid_v3 or pid_v2 or sps_pkg_name):
            raise ValueError(
                "Article.get requires pid_v3 or pid_v2 or sps_pkg_name with collection, or sps_pkg"
            )

        qs = cls.objects.all()
        if pid_v3 or pid_v2:
            if pid_v2:
                qs = qs.filter(pid_v2=pid_v2)
            if pid_v3:
                qs = qs.filter(pid_v3=pid_v3)
        else:
            qs = cls.filter_by_sps_pkg_name(qs, sps_pkg_name)
        return cls._get_in_collection(qs, collection)

    @classmethod
    def filter_by_sps_pkg_name(cls, qs, sps_pkg_name):
        """
        Filtra pelo nome do pacote SPS (identificação humana).

        O nome do pacote é o de SPSPkg; CollectionPidV2.sps_pkg_name é
        usado somente para os documentos sem pacote.
        """
        return qs.filter(
            Q(sps_pkg__sps_pkg_name=sps_pkg_name)
            | Q(
                sps_pkg__isnull=True,
                collection_pid_v2__sps_pkg_name=sps_pkg_name,
            )
        )

    @classmethod
    def get_by_sps_pkg_name(cls, sps_pkg_name, collection=None):
        """
        Obtém o Article pelo nome do pacote SPS (identificação humana)
        """
        if not sps_pkg_name:
            raise ValueError("Article.get_by_sps_pkg_name requires sps_pkg_name")
        qs = cls.filter_by_sps_pkg_name(cls.objects.all(), sps_pkg_name)
        if collection:
            return cls._get_in_collection(qs, collection)
        return qs.get()

    @classmethod
    def filter_by_journal_acron(cls, qs, journal_acron):
        """
        Filtra os artigos pelo acrônimo do periódico na coleção do artigo.

        Journal.journal_acron fica vazio quando o periódico tem acrônimos
        diferentes nas coleções; o acrônimo na coleção está em
        JournalProc (journal, collection, acron).
        """
        from proc.models import JournalProc

        return qs.filter(
            Q(journal__journal_acron=journal_acron)
            | Q(
                models.Exists(
                    JournalProc.objects.filter(
                        journal=models.OuterRef("journal"),
                        collection=models.OuterRef("collection_pid_v2__collection"),
                        acron=journal_acron,
                    )
                )
            )
        )

    @classmethod
    def get_by_pid_v3(cls, pid_v3):
        """
        Retorna o Article do pid_v3, priorizando o da coleção principal
        (artigo em mais de uma coleção tem um Article por coleção)
        """
        items = list(cls.objects.filter(pid_v3=pid_v3).order_by("-updated"))
        if not items:
            raise cls.DoesNotExist(f"Article pid_v3={pid_v3} does not exist")
        for item in items:
            if item.collection and item.collection.is_national_journal_collection:
                return item
        return items[0]

    @classmethod
    def delete_related_items(cls, qs):
        ArticleDOIWithLang.objects.filter(article__in=qs).delete()
        ArticleTitle.objects.filter(parent__in=qs).delete()
        ArticleCollection.objects.filter(article__in=qs).delete()
        ArticleWebPage.objects.filter(article__in=qs).delete()
        return qs.delete()

    # ── create_or_update ──

    @classmethod
    def _get_to_update(cls, user, sps_pkg, collection_pid_v2=None):
        """
        Obtém o Article a atualizar

        Com documento na coleção (collection_pid_v2): o Article vinculado a
        ele ou, na falta, o Article ainda não vinculado do mesmo pacote ou
        pid_v3 (anterior à separação por coleção), cujo vínculo é
        completado; é reaproveitado se for desta coleção ou se a coleção
        continuar ambígua, mas não se for de outra coleção.

        Sem documento na coleção (ex.: ingresso): o Article do pacote ou o
        do pid_v3 (priorizando o não vinculado e, depois, o da coleção
        principal)
        """
        pid_v3 = sps_pkg.pid_v3
        q = Q(sps_pkg=sps_pkg)
        if pid_v3:
            q |= Q(pid_v3=pid_v3)

        if collection_pid_v2:
            try:
                return cls.objects.get(collection_pid_v2=collection_pid_v2)
            except cls.DoesNotExist:
                pass
            for item in cls.objects.filter(q, collection_pid_v2__isnull=True).order_by(
                "-updated"
            ):
                item.complete_collection_pid_v2(user)
                if item.collection_pid_v2_id in (None, collection_pid_v2.id):
                    return item
            raise cls.DoesNotExist

        obj = (
            cls.objects.filter(sps_pkg=sps_pkg).order_by("-updated").first()
            or (
                pid_v3
                and cls.objects.filter(
                    pid_v3=pid_v3, collection_pid_v2__isnull=True
                ).first()
            )
        )
        if obj:
            return obj
        if pid_v3:
            return cls.get_by_pid_v3(pid_v3)
        raise cls.DoesNotExist

    @classmethod
    def create_or_update(
        cls, user, sps_pkg, issue=None, journal=None, position=None, collection=None
    ):
        """
        Cria / atualiza o Article do documento na coleção do pacote
        (sps_pkg.collection_pid_v2)

        Pacote ainda não vinculado ao documento na coleção é vinculado,
        se possível; pacote sem coleção (ex.: ingresso) gera Article sem
        collection_pid_v2

        collection: se informada, deve ser a coleção do pacote
        """
        if not sps_pkg:
            raise ValueError("create_article requires sps_pkg with pid_v2")

        if not sps_pkg.collection_pid_v2_id:
            sps_pkg.complete_collection_pid_v2(user)
        collection_pid_v2 = sps_pkg.collection_pid_v2
        if collection and not collection_pid_v2:
            raise ValueError(
                f"SPSPkg {sps_pkg} is missing collection_pid_v2 (document in the collection {collection})"
            )
        if collection and collection_pid_v2.collection_id != collection.id:
            raise ValueError(
                f"SPSPkg {sps_pkg} collection ({collection_pid_v2.collection}) is not {collection}"
            )

        xml_with_pre = sps_pkg.xml_with_pre
        if not xml_with_pre:
            raise ValueError(f"SPSPkg {sps_pkg} is missing xml_with_pre")

        try:
            obj = cls._get_to_update(user, sps_pkg, collection_pid_v2)
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user

        obj.sps_pkg = sps_pkg
        obj.pid_v3 = sps_pkg.pid_v3
        obj.pid_v2 = sps_pkg.pid_v2 or obj.pid_v2
        obj.pp_xml_id = sps_pkg.ppx_id or obj.pp_xml_id
        if collection_pid_v2:
            obj.set_collection_pid_v2(collection_pid_v2)
        obj.updated_by = user
        obj.article_type = xml_with_pre.xmltree.find(".").get("article-type")

        if journal:
            obj.journal = journal
        else:
            obj.add_journal(xml_with_pre)
        if issue:
            obj.issue = issue
        else:
            obj.add_issue(xml_with_pre)

        obj.status = obj.status or choices.AS_READY_TO_PUBLISH
        obj.add_pages(xml_with_pre)
        obj.add_article_publication_date()
        obj.add_data_availability_status(xml_with_pre)
        obj.add_position(position, xml_with_pre.fpage)
        obj.save()

        obj.add_sections(user, xml_with_pre)
        obj.add_article_titles(user, xml_with_pre)
        obj.add_doi_with_lang(user, xml_with_pre.article_doi_with_lang)
        obj.add_position_in_table_of_contents()
        return obj

    # ── add_* helpers ──

    def add_doi_with_lang(self, user, article_doi_with_lang):
        for item in article_doi_with_lang:
            try:
                ArticleDOIWithLang.get_or_create(
                    user, self, item["value"], item["lang"]
                )
            except Exception as e:
                logging.exception(e)

    def add_related_item(self, target_doi, target_article_type):
        self.save()

    def add_pages(self, xml_with_pre):
        self.fpage = xml_with_pre.fpage
        self.fpage_seq = xml_with_pre.fpage_seq
        self.lpage = xml_with_pre.lpage
        self.elocation_id = xml_with_pre.elocation_id

    def add_issue(self, xml_with_pre):
        self.issue = Issue.get(
            journal=self.journal,
            volume=xml_with_pre.volume,
            supplement=xml_with_pre.suppl,
            number=xml_with_pre.number,
        )

    def add_journal(self, xml_with_pre):
        self.journal = Journal.get(
            official_journal=OfficialJournal.get(
                issn_electronic=xml_with_pre.journal_issn_electronic,
                issn_print=xml_with_pre.journal_issn_print,
            ),
        )

    def add_article_titles(self, user, xml_with_pre):
        titles = ArticleTitles(
            xmltree=xml_with_pre.xmltree,
        ).article_title_list
        self.title_with_lang.clear()
        for title in titles:
            try:
                language_code2 = title.get("language") or title.get("lang")
                if not language_code2:
                    raise ValueError(
                        f"Missing language for article title: {title}"
                    )
                if not title.get("html_text"):
                    raise ValueError(f"Missing text for article title: {title}")

                obj_lang = Language.get_or_create(
                    code2=language_code2,
                    creator=user,
                    text_to_detect_language=title.get("html_text"),
                )
                obj = ArticleTitle.create_or_update(
                    user,
                    parent=self,
                    text=title.get("html_text"),
                    language=obj_lang,
                )
                self.title_with_lang.add(obj)
            except Exception as e:
                logging.exception(e)

    def add_sections(self, user, xml_with_pre):
        self.sections.clear()

        xml_sections = ArticleTocSections(
            xmltree=xml_with_pre.xmltree,
        )

        items = xml_sections.article_section
        items.extend(xml_sections.sub_article_section)

        toc = TOC.create_or_update(user, self.issue, ordered=False)

        group = None
        for item in items:
            if not item.get("text") or not item.get("lang"):
                continue
            obj_lang = Language.get_or_create(
                code2=item.get("lang"),
                creator=user,
                text_to_detect_language=item.get("text"),
            )
            section = self.journal.get_section(
                user,
                obj_lang=obj_lang,
                code=item.get("code"),
                text=item.get("text"),
            )
            self.sections.add(section)
            group = group or section.code or TocSection.create_group(self.issue)
            TocSection.create_or_update(user, toc, group, section)

    def add_article_publication_date(self):
        if self.sps_pkg.is_public:
            value = self.sps_pkg.pub_date
            self.first_pubdate_iso = value
            self.first_publication_date = datetime.fromisoformat(value).date()
            self.save()

    @classmethod
    def update_data_availability_status(cls, queryset=None, force_update=False):
        """
        Preenche data_availability_status de artigos já existentes
        a partir do XML do sps_pkg.
        """
        qs = queryset if queryset is not None else cls.objects.all()
        qs = qs.filter(sps_pkg__isnull=False)
        if not force_update:
            qs = qs.filter(data_availability_status__isnull=True)
        updated = 0
        for article in qs.iterator():
            try:
                xml_with_pre = article.sps_pkg.xml_with_pre
                if not xml_with_pre:
                    continue
                article.add_data_availability_status(xml_with_pre)
                article.save(update_fields=["data_availability_status"])
                updated += 1
            except Exception as e:
                logging.exception(e)
        return updated

    def add_data_availability_status(self, xml_with_pre):
        try:
            self.data_availability_status = get_data_availability_status(
                xml_with_pre.xmltree
            )
        except Exception as e:
            logging.exception(e)

    def add_position(self, position=None, fpage=None):
        try:
            self.position = int(position or fpage)
        except (ValueError, TypeError):
            self.position = None

    def add_position_in_table_of_contents(self):
        if self.position:
            return
        position = TocSection.get_section_position(self.issue, self.sections) or 0
        sections = [item.text for item in self.sections.all()]
        self.position = (
            position * 10000
            + Article.objects.filter(sections__text__in=sections).count()
        )
        self.save()

    # ── display properties ──

    @property
    def multilingual_sections(self):
        return TocSection.multilingual_sections(self.issue, self.sections)

    @property
    def display_sections(self):
        return str(self.multilingual_sections)

    @property
    def collections_acron(self):
        """Acrônimos das coleções via ArticleCollection (sem depender de proc)."""
        return list(
            self.article_collections.values_list(
                "collection__acron", flat=True
            )
            .distinct()
            .order_by("collection__acron")
        )

    @property
    def display_collections(self):
        return ", ".join(self.collections_acron)

    # ── status ──

    def update_status(self, new_status=None, rollback=False):
        if rollback:
            if self.status == choices.AS_ERRATUM_SUBMITTED:
                self.status = choices.AS_REQUIRE_ERRATUM
                self.save()
                return
            elif self.status not in (
                choices.AS_REQUIRE_UPDATE,
                choices.AS_REQUIRE_ERRATUM,
            ):
                self.status = choices.AS_REQUIRE_UPDATE
                self.save()
                return
        else:
            if self.status == choices.AS_REQUIRE_UPDATE:
                self.status = choices.AS_UPDATE_SUBMITTED
                self.save()
                return
            if self.status == choices.AS_REQUIRE_ERRATUM:
                self.status = choices.AS_ERRATUM_SUBMITTED
                self.save()
                return
            self.status = new_status or choices.AS_PUBLISHED
            self.save()

    def get_zip_filename_and_content(self):
        return self.sps_pkg.get_zip_filename_and_content()

    # ── URL generators ──

    def get_html_urls(self, website_url, purpose, journal_acron=None):
        """
        Gera dicts de URL para HTML do artigo.

        Parameters
        ----------
        website_url : str
        purpose : str
            ARTICLE_WEBPAGE_PURPOSE_CLASSIC, ARTICLE_WEBPAGE_PURPOSE_PUBLIC
            ou ARTICLE_WEBPAGE_PURPOSE_QA.
        journal_acron : str, optional
            Acrônimo do periódico na coleção (JournalProc.acron).

        Yields
        ------
        dict  {"url", "format", "lang", "purpose"}
        """
        pid_v2 = self.get_pid_v2()
        pid_v3 = self.pid_v3
        is_classic = purpose == choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC

        if is_classic:
            journal_acron = None
        else:
            journal_acron = journal_acron or self.journal.get_acron()

        for item in self.htmls:
            lang = item.get("lang")
            if not lang:
                continue
            if is_classic:
                url = format_classic_url(
                    website_url, pid_v2=pid_v2, format="html", lang_code=lang
                )
            else:
                url = format_url(
                    website_url, pid_v3, journal_acron, format="html", lang_code=lang
                )
            yield {
                "url": url,
                "format": "html",
                "lang": lang,
                "purpose": purpose,
            }

    def get_pdf_urls(self, website_url, purpose, journal_acron=None):
        """
        Gera dicts de URL para PDF do artigo.

        Parameters
        ----------
        website_url : str
        purpose : str
        journal_acron : str, optional
            Acrônimo do periódico na coleção (JournalProc.acron).

        Yields
        ------
        dict  {"url", "format", "lang", "purpose"}
        """
        pid_v2 = self.get_pid_v2()
        pid_v3 = self.pid_v3
        is_classic = purpose == choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC
        if not is_classic:
            journal_acron = journal_acron or self.journal.get_acron()

        for item in self.pdfs:
            lang = item.get("lang")
            if not lang:
                continue
            if is_classic:
                url = format_classic_url(
                    website_url, pid_v2=pid_v2, format="pdf", lang_code=lang
                )
            else:
                url = format_url(
                    website_url, pid_v3, journal_acron, format="pdf", lang_code=lang
                )
            yield {
                "url": url,
                "format": "pdf",
                "lang": lang,
                "purpose": purpose,
            }

    def get_webpage_items(self, website_url, purpose, journal_acron=None):
        """Gera todos os itens de página (HTML + PDF) para um purpose."""
        yield from self.get_html_urls(website_url, purpose, journal_acron)
        yield from self.get_pdf_urls(website_url, purpose, journal_acron)

    def get_main_article_url(self, website_url, journal_acron=None):
        return format_url(
            website_url, self.pid_v3, journal_acron or self.journal.get_acron()
        )

    # ── repetitions / dedup ──

    @classmethod
    def select_items(
        cls,
        journal_id_list=None,
        issue_id_list=None,
        sps_pkg_list=None
    ):
        kwargs = {}
        if journal_id_list:
            kwargs["journal__id__in"] = journal_id_list
        if issue_id_list:
            kwargs["issue__id__in"] = issue_id_list
        if sps_pkg_list:
            kwargs["sps_pkg__id__in"] = sps_pkg_list
        return cls.objects.filter(**kwargs)

    # ── ArticleCollection: ponto de entrada ──

    def create_or_update_article_collections(self, user, force_update=None):
        """
        Obtém ou cria ArticleCollection para cada coleção do journal
        e delega a criação das ArticleWebPages.

        As páginas de uma coleção são reconstruídas automaticamente
        quando a WebSiteConfiguration vigente foi alterada após a
        última reconstrução (``ArticleCollection.is_stale``), sem que
        o chamador precise decidir isso via ``force_update``.
        """
        items = []
        if not force_update:
            force_update = self.pages.filter(url__startswith="None").exists()
        try:
            if self.collection:
                # um Article por coleção; remove o que era de outras coleções
                # (artigo anterior à separação por coleção)
                self.article_collections.exclude(collection=self.collection).delete()
                self.pages.exclude(collection=self.collection).delete()
                collections = [self.collection]
            else:
                # artigo anterior à separação por coleção
                collections = [
                    journal_proc.collection
                    for journal_proc in self.journal.journalproc_set.all()
                ]
            for collection in collections:
                art_col = ArticleCollection.get_or_create(user, self, collection)
                if force_update or art_col.is_stale():
                    art_col.create_or_update_pages(user)
                items.append(art_col)
        except Exception as e:
            logging.exception(e)
        return items

    # ── Convenience: acesso a ArticleCollection ──

    def get_article_collection(self, collection):
        """Retorna ArticleCollection ou None."""
        return self.article_collections.filter(
            collection=collection
        ).first()

    # ── Metadata ──

    def get_metadata_by_lang(self):
        langs = self.article_langs
        metadata = {}
        for lang in langs:
            metadata[lang] = self.get_metadata_items(lang)
        return metadata

    def get_metadata_items(self, lang=None):
        items = []
        lang_filter = {"language__code2": lang} if lang else {}

        for i, title in enumerate(
            self.title_with_lang.filter(**lang_filter), 1
        ):
            if title.text:
                items.append((f"title.{i}", title.text))

        doi_lang_filter = {"lang__code2": lang} if lang else {}
        for i, doi in enumerate(
            self.doi_with_lang.filter(**doi_lang_filter), 1
        ):
            if doi.doi:
                items.append((f"doi.{i}", doi.doi))

        for i, section in enumerate(
            self.sections.filter(**lang_filter), 1
        ):
            if section.text:
                items.append((f"section.{i}", section.text))

        pid_v2 = self.get_pid_v2()
        if pid_v2:
            items.append(("pid_v2", pid_v2))

        try:
            xmltree = self.sps_pkg.xml_with_pre.xmltree
            contribs = xmltree.xpath(
                ".//front/article-meta/contrib-group/"
                "contrib[@contrib-type='author']"
            )
            for i, contrib in enumerate(contribs, 1):
                surname = contrib.findtext("name/surname") or ""
                if surname:
                    items.append((f"author.{i}", surname))
        except (AttributeError, TypeError):
            pass

        return items

    @property
    def webpages(self):
        for art_col in self.article_collections.all():
            for page in art_col.pages.all():
                yield page.data

    def check_availability(self, user, collection=None, collection_id=None, purpose=None, force_update=None, timeout=None):
        """
        Verifica disponibilidade das páginas do artigo.

        Parameters
        ----------
        collection_id : int, optional
            Filtra por coleção.
        purpose : str, optional
            Filtra por purpose (PUBLIC, QA, CLASSIC).
        """
        qs = self.article_collections.all()
        if collection_id:
            qs = qs.filter(collection_id=collection_id)
        if collection:
            qs = qs.filter(collection=collection)
        logging.info("article_collections: {}".format(qs.count()))
        response = []
        for art_col in qs:
            if not art_col.pages.exists() and not force_update:
                force_update = True
            for resp in art_col.check_pages(
                user=user, purpose=purpose, force_update=force_update, timeout=timeout
            ):
                response.append(resp)
        return response

    @property
    def availability(self):
        data = []
        for item in ArticleWebPage.objects.filter(article=self):
            data.append(item.data)
        return data

    def is_available_on_website(self, collection=None, purpose=None):
        pages = []
        kwargs = {}
        if purpose:
            kwargs["purpose"] = purpose
        if collection:
            kwargs["collection"] = collection
        items = self.pages.filter(**kwargs)
        
        status_list = list(items.values_list("status", flat=True).distinct())
        status = get_compiled_status(status_list)
        valid = status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
        
        for item in items:
            pages.append(item.data)
        return {
            "collection": collection and collection.acron,
            "purpose": purpose,
            "valid": valid,
            "status_list": status_list,
            "status": status,
            "pages": pages,
        }
        
    def available_on_classic_website(self, collection):
        response = self.is_available_on_website(collection, choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC)
        response["new_pid_status"] = get_pid_status_from_webpage_status(
            choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC, response["status"]
        )
        return response

    def available_on_public_website(self, collection):
        response = self.is_available_on_website(collection, choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC)
        response["new_pid_status"] = get_pid_status_from_webpage_status(
            choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC, response["status"]
        )
        return response
 
    @classmethod
    def get_repeated_values(cls, field_name, queryset, issue=None, other_field_names=None):
        """
        Retorna os valores de field_name repetidos ou, se other_field_names
        é informado, as tuplas de valores (field_name, *other_field_names)
        repetidas
        """
        if not queryset:
            raise ValueError("Article.get_repeated_values requires queryset")
        params = {}
        if issue:
            params["issue"] = issue
        queryset = queryset.filter(**params)
        field_names = (field_name,) + tuple(other_field_names or ())
        return (
            queryset.values(*field_names)
            .filter(sps_pkg__isnull=False)
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .values_list(*field_names, flat=not other_field_names)
        )

    @classmethod
    def exclude_invalid_records(
        cls,
        user,
        issue,
        delete_article_which_sps_pkg_is_missing=True,
        delete_article_which_is_duplicated=True,
         timeout=None,
    ):
        try:
            return cls._exclude_invalid_records(
                user,
                issue,
                delete_article_which_sps_pkg_is_missing,
                delete_article_which_is_duplicated,
                timeout,
            )
        except Exception as e:
            return {"error": str(e), "error_type": str(type(e)), "traceback": traceback.format_exc()}

    @classmethod
    def _exclude_invalid_records(
        cls,
        user,
        issue,
        delete_article_which_sps_pkg_is_missing=True,
        delete_article_which_is_duplicated=True,
        timeout=None,
    ):
        total_deletado = 0
        response = {}
        exceptions = []
        articles = cls.objects.filter(issue=issue)
        response["total_articles"]= articles.count()
        response["params"] = {
            "delete_article_which_sps_pkg_is_missing": delete_article_which_sps_pkg_is_missing,
            "delete_article_which_is_duplicated": delete_article_which_is_duplicated,            
        }

        if delete_article_which_sps_pkg_is_missing:
            # 1. Remoção por falta de sps_pkg
            to_delete = articles.filter(sps_pkg__isnull=True)
            if to_delete:
                try:
                    qtd_deleted, _ignored = cls.delete_related_items(to_delete)
                    response["total_delete_article_which_sps_pkg_is_missing"] = qtd_deleted
                    total_deletado += qtd_deleted
                    # consulta novamente
                    articles = cls.objects.filter(
                        issue=issue, sps_pkg__isnull=False
                    )
                except Exception as e:
                    exceptions.append({
                        "action": "deleting due to missing sps_pkg",
                        "exception": traceback.format_exc()
                    })

        # vincula ao documento na coleção os artigos ainda não vinculados,
        # para que os duplicados sejam avaliados por coleção
        link_stats = {}
        for article in articles.filter(collection_pid_v2__isnull=True):
            result = article.complete_collection_pid_v2(user)
            link_stats[result] = link_stats.get(result, 0) + 1
        response["complete_collection_pid_v2"] = link_stats

        if delete_article_which_is_duplicated:
            # 2. Remoção por duplicidade
            duplicated_items = []
            # pid_v3 repetido na mesma coleção
            multiple_values = cls.get_repeated_values(
                "pid_v3",
                articles,
                other_field_names=["collection_pid_v2__collection_id"],
            )
            total_delete_article_which_is_duplicated = 0
            for value in list(multiple_values or []):
                try:
                    # Filtra os registros que possuem este valor específico duplicado
                    pid_v3, collection_id = value
                    articles_which_same_sps_pkg = articles.filter(
                        pid_v3=pid_v3, collection_pid_v2__collection_id=collection_id
                    ).order_by("-updated")

                    articles_which_same_sps_pkg_list = list(articles_which_same_sps_pkg)
                    data = {"value": value, "total": len(articles_which_same_sps_pkg_list)}
                    
                    result = Article.duplicated_item_to_keep(user, timeout, articles_which_same_sps_pkg_list)
                    data.update(result)

                    # Executa a deleção e soma ao totalizador
                    qtd_deletada, _ignored = cls.delete_related_items(
                        articles_which_same_sps_pkg.exclude(id=result["keep"])
                    )
                    total_delete_article_which_is_duplicated += qtd_deletada
                    data["total_deleted"] = qtd_deletada
                    duplicated_items.append(data)
                except Exception as e:
                    exceptions.append({
                        "action": "removing duplicity",
                        "item": value,
                        "exception": traceback.format_exc()
                    })
            response["duplicated_items"] = duplicated_items
            total_deletado += total_delete_article_which_is_duplicated
            response["total_delete_article_which_is_duplicated"] = total_delete_article_which_is_duplicated
        response["total_deleted_items"] = total_deletado
        response["exceptions"] = exceptions
        return response

    @staticmethod
    def duplicated_item_to_keep(user, timeout, duplicated_items):
        # Define o fallback (mais recente) caso nenhum seja válido na API
        keep = duplicated_items[0]
        exceptions = []
        # Verifica a disponibilidade do artigo
        for item in duplicated_items:
            try:
                item.create_or_update_article_collections(user, force_update=True)
                item.check_availability(user, force_update=True, timeout=timeout)
                for coll in item.article_collections.all():
                    page_status = item.available_on_public_website(coll.collection)
                    if page_status.get("valid"):
                        keep = item
                        break
            except Exception as e:
                exceptions.append({
                    "item": str(item),
                    "exception": traceback.format_exc()
                })
        return {"keep": keep.id, "exceptions": exceptions}


# ============================================================
# Article DOI / Title / RelatedItem / RequestChange
# ============================================================


class ArticleDOIWithLang(Orderable, DOIWithLang):
    article = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="doi_with_lang"
    )

    class Meta:
        verbose_name = _("Article DOI with Language")
        verbose_name_plural = _("Article DOIs with Language")

    def __str__(self):
        return f"{self.lang}: {self.doi}"

    @classmethod
    def get(cls, article=None, doi=None, lang=None):
        if lang and isinstance(lang, str):
            lang = Language.get(code2=lang)
        if article and doi and lang:
            try:
                return cls.objects.get(
                    article=article, doi__iexact=doi, lang=lang
                )
            except cls.MultipleObjectsReturned:
                return cls.objects.filter(
                    article=article, doi__iexact=doi, lang=lang
                ).first()
        params = {}
        if lang:
            params["lang"] = lang
        if article:
            params["article"] = article
        if doi:
            params["doi"] = doi
        if params:
            return cls.objects.filter(**params)
        raise ValueError(
            f"ArticleDOIWithLang.get missing params "
            f"{dict(article=article, doi=doi, lang=lang)}"
        )

    @classmethod
    def create(cls, user, article=None, doi=None, lang=None):
        if lang and isinstance(lang, str):
            lang = Language.get(code2=lang)
        if article and doi and lang:
            try:
                obj = cls()
                obj.article = article
                obj.doi = doi
                obj.lang = lang
                obj.creator = user
                obj.save()
                return obj
            except IntegrityError:
                return cls.get(article, doi, lang)
        raise ValueError(
            f"ArticleDOIWithLang.create missing params "
            f"{dict(article=article, doi=doi, lang=lang)}"
        )

    @classmethod
    def get_or_create(cls, user, article=None, doi=None, lang=None):
        if article and doi and lang:
            try:
                return cls.get(article, doi, lang)
            except cls.DoesNotExist:
                return cls.create(user, article, doi, lang)
        return cls.get(article, doi, lang)


class ArticleTitle(HTMLTextModel, CommonControlField):
    parent = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="title_with_lang"
    )
    panels = [
        FieldPanel("text", read_only=True),
        FieldPanel("language", read_only=True),
    ]


class RelatedItem(CommonControlField):
    item_type = models.CharField(
        _("Related item type"),
        max_length=32,
        choices=choices.RELATED_ITEM_TYPE,
        blank=False,
        null=False,
    )
    source_article = models.ForeignKey(
        "Article",
        related_name="source_article",
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )
    target_article = models.ForeignKey(
        "Article",
        related_name="target_article",
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )

    panel = [
        FieldPanel("item_type"),
        FieldPanel("source_article"),
        FieldPanel("target_article"),
    ]

    def __str__(self):
        return (
            f"{self.source_article} - {self.target_article} ({self.item_type})"
        )

    base_form_class = RelatedItemForm


class RequestArticleChange(CommonControlField):
    change_type = models.CharField(
        _("Change type"),
        max_length=32,
        choices=choices.REQUEST_CHANGE_TYPE,
        blank=False,
        null=False,
    )
    comment = models.TextField(_("Comment"), blank=True, null=True)
    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, blank=True, null=True
    )

    panels = [
        AutocompletePanel("article"),
        FieldPanel("change_type", classname="collapsible"),
        FieldPanel("comment", classname="collapsible"),
    ]

    def __str__(self) -> str:
        return f"{self.article}"

    base_form_class = RequestArticleChangeForm


# ============================================================
# ArticleCollection  (Article × Collection)
# ============================================================


class ArticleCollection(CommonControlField):
    """
    Vínculo explícito entre um artigo e uma coleção SciELO.

    Cada registro representa "este artigo pertence a esta coleção".
    O campo status é agregado das ArticleWebPage filhas.

    Modelo simplificado: ArticleWebPage é o único filho, com um campo
    `purpose` (PUBLIC / QA / CLASSIC) que substitui os antigos
    ArticleWebsite e ClassicArticleWebPage.
    """

    article = ParentalKey(
        Article,
        on_delete=models.CASCADE,
        related_name="article_collections",
    )
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        # related_name="article_collections",
    )

    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=choices.ARTICLE_WEBPAGE_STATUS,
        default=choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
    )

    panels = [
        FieldPanel("article", read_only=True),
        FieldPanel("collection", read_only=True),
        FieldPanel("status", read_only=True),
    ]

    class Meta:
        verbose_name = _("Article collection")
        verbose_name_plural = _("Article collections")
        unique_together = ("article", "collection")
        indexes = [
            models.Index(fields=["collection", "status"]),
            models.Index(fields=["article", "status"]),
        ]

    def __str__(self):
        return f"{self.article} @ {self.collection} [{self.status}]"

    # ── Status agregado ──

    def update_aggregate_status(self, user):
        """Recalcula status a partir das ArticleWebPage filhas."""
        status_list = self.pages.values_list("status", flat=True)

        self.status = get_compiled_status(list(status_list))
        self.updated_by = user
        self.save(update_fields=["status", "updated_by"])

    # ── get_or_create ──

    @classmethod
    def get_or_create(cls, user, article, collection):
        try:
            return cls.objects.get(article=article, collection=collection)
        except cls.DoesNotExist:
            try:
                obj = cls(
                    article=article,
                    collection=collection,
                    creator=user,
                )
                obj.save()
                return obj
            except IntegrityError:
                return cls.objects.get(
                    article=article, collection=collection
                )

    # ── Helpers de configuração ──

    def is_stale(self):
        """
        Indica se a WebSiteConfiguration vigente da coleção foi
        alterada após a última reconstrução das páginas deste
        ArticleCollection, ou se ele ainda não possui páginas.
        """
        if not self.pages.exists():
            return True
        latest_config_update = WebSiteConfiguration.objects.filter(
            collection=self.collection, enabled=True
        ).aggregate(Max("updated"))["updated__max"]
        return bool(latest_config_update) and latest_config_update > self.updated

    @property
    def classic_website(self):
        """ClassicWebsiteConfiguration da coleção, se existir."""
        try:
            return ClassicWebsiteConfiguration.objects.get(
                collection=self.collection
            )
        except ClassicWebsiteConfiguration.DoesNotExist:
            return None

    # ── Criar / atualizar páginas ──

    def create_or_update_pages(self, user):
        """
        Cria ArticleWebPages para todos os websites (QA, PUBLIC)
        e para o site clássico desta coleção.

        Substitui os antigos create_or_update_websites() +
        create_or_update_classic_website_pages().
        """
        article = self.article
        existing_ids = set()
        journal_acron = article.journal.get_acron(self.collection)

        # ── Websites novos (QA / PUBLIC) ──
        for ws_config in WebSiteConfiguration.objects.filter(
            collection=self.collection,
            enabled=True,
        ):
            purpose = ws_config.purpose  # "PUBLIC" ou "QA"
            self.pages.filter(purpose=purpose).exclude(
                url__startswith=ws_config.url
            ).delete()

            for item in article.get_webpage_items(
                ws_config.url, purpose, journal_acron
            ):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self.article, self.collection, item
                )
                existing_ids.add(page.id)

        # ── Site clássico ──
        classic_ws = self.classic_website
        if classic_ws and classic_ws.url:
            purpose = choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC
            self.pages.filter(purpose=purpose).exclude(
                url__startswith=classic_ws.url
            ).delete()
            for item in article.get_html_urls(
                classic_ws.url, purpose
            ):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self.article, self.collection, item
                )
                existing_ids.add(page.id)
                # obter apenas 1
                break
            for item in article.get_pdf_urls(
                classic_ws.url, purpose
            ):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self.article, self.collection, item
                )
                # obter apenas 1
                existing_ids.add(page.id)

        # Remove páginas órfãs
        self.pages.exclude(id__in=existing_ids).delete()

        # Marca o momento da reconstrução, usado por is_stale() para
        # detectar automaticamente futuras mudanças de WebSiteConfiguration
        self.save(update_fields=["updated"])

    @property
    def pages(self):
        return ArticleWebPage.objects.filter(
            collection=self.collection,
            article=self.article,
        )

    # ── Disponibilidade: queries ──

    @property
    def is_available(self):
        """Todas as páginas estão válidas?"""
        return self.status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT

    @property
    def any_classic_website_page_available(self):
        return self.any_page_available(choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC)

    @property
    def any_public_website_page_available(self):
        return self.any_page_available(choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC)

    def get_pages_by_purpose(self, purpose):
        """Retorna queryset de páginas filtradas por purpose."""
        return self.pages.filter(purpose=purpose)

    def any_page_available(self, purpose=None):
        """Ao menos uma ArticleWebPage está VALID_CONTENT?"""
        qs = self.pages.filter(
            status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
        )
        if purpose:
            qs = qs.filter(purpose=purpose)
        return qs.exists()

    def get_availability_stats(self, purpose=None):
        """Estatísticas de disponibilidade das páginas."""
        qs = self.pages.all()
        if purpose:
            qs = qs.filter(purpose=purpose)
        total = qs.count()
        if not total:
            return {}
        stats = qs.values("status").annotate(count=Count("id"))
        return {
            item["status"]: round(item["count"] * 100 / total, 1)
            for item in stats
        }

    # ── Disponibilidade: verificação ──

    def check_pages(
        self, user, timeout=None, force_update=None, purpose=None,
    ):
        """
        Verifica disponibilidade de todas as pages desta coleção.

        Calcula metadata uma vez e delega para cada ArticleWebPage.
        Propaga status automaticamente: Page → Collection.

        Parameters
        ----------
        purpose : str, optional
            Se informado, verifica apenas páginas desse purpose.
        """
        response = []
        article_metadata = self.article.get_metadata_by_lang()

        pages = self.pages.all()
        if purpose:
            pages = pages.filter(purpose=purpose)

        # Verifica se a coleção possui site clássico antes de checar
        # páginas clássicas — algumas coleções não têm site clássico
        if not self.classic_website:
            if purpose == choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC:
                return response
            pages = pages.exclude(purpose=choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC)

        if not force_update:
            pages = pages.exclude(
                status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
            )
        for page in pages.select_related("lang"):
            lang_code = page.lang.code2 if page.lang else None
            response.append(
                page.check_page(
                    user,
                    timeout,
                    article_metadata=article_metadata.get(lang_code),
                    force_update=force_update,
                )
            )
        return response


# ============================================================
# ArticleWebPage  (única tabela de páginas)
# ============================================================


class ArticleWebPage(CommonControlField):
    """
    Página web de um artigo vinculada a um ArticleCollection.

    O campo `purpose` distingue entre PUBLIC, QA e CLASSIC,
    unificando os antigos ArticleWebPage, ClassicArticleWebPage
    e o nível intermediário ArticleWebsite.

    Propagação de status: Page → ArticleCollection.
    """

    # article_collection = models.ForeignKey(
    #     ArticleCollection,
    #     on_delete=models.CASCADE,
    #     related_name="pages",
    #     null=True, blank=True,
    # )
    article = ParentalKey(
        Article,
        on_delete=models.CASCADE,
        related_name="pages",
        null=True, blank=True,
    )
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        # related_name="pages",
        null=True, blank=True,
    )
    purpose = models.CharField(
        _("Purpose"),
        max_length=8,
        choices=choices.ARTICLE_WEBPAGE_PURPOSE,
        help_text=_("Distinguishes between public, QA, and classic website pages."),
        null=True, blank=True,
    )
    fmt = models.CharField(_("Format"), max_length=4, null=True, blank=True)
    lang = models.ForeignKey(
        Language,
        verbose_name=_("Language"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    url = models.CharField(_("URL"), max_length=265, null=True, blank=True,)
    status = models.CharField(
        _("Status"),
        max_length=16,
        null=True,
        blank=True,
        choices=choices.ARTICLE_WEBPAGE_STATUS,
        default=choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
    )
    detail = models.JSONField(_("Detail"), null=True, blank=True)

    panels = [
        FieldPanel("article", read_only=True),
        FieldPanel("collection", read_only=True),
        FieldPanel("purpose", read_only=True),
        FieldPanel("url", read_only=True),
        FieldPanel("fmt", read_only=True),
        FieldPanel("lang", read_only=True),
        FieldPanel("status", read_only=True),
        FieldPanel("detail", widget=ReadOnlyPrettyJSONWidget()),
    ]

    class Meta:
        verbose_name = _("Article web page")
        verbose_name_plural = _("Article web pages")
        unique_together = [
            ("article", "collection", "purpose", "fmt", "lang")
        ]
        indexes = [
            models.Index(fields=["article", "collection", "status"]),
            models.Index(fields=["article", "collection", "purpose"]),
            models.Index(fields=["purpose", "status"]),
        ]

    def __str__(self):
        return f"{self.url} [{self.purpose}/{self.fmt}/{self.lang}] {self.status}"

    # ── URL update ──

    def update_url_if_changed(self, new_url, user):
        """Atualiza URL se mudou. Retorna True se houve alteração."""
        if self.url != new_url:
            self.url = new_url
            self.updated_by = user
            self.save(update_fields=["url", "updated"])
            return True
        return False

    # ── Verificação de disponibilidade ──

    @property
    def data(self):
        return {
            "url": self.url,
            "format": self.fmt,
            "lang": self.lang.code2 if self.lang else None,
            "purpose": self.purpose,
            "status": self.status,
            "valid": self.status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
            "result": self.detail,
            "updated": self.updated.isoformat(),
        }

    def check_page(
        self, user, timeout=None, article_metadata=None, force_update=None
    ):
        """
        Verifica disponibilidade e validade do conteúdo da página.

        Acessa a URL, verifica conteúdo contra os metadados do artigo,
        e propaga o status para o ArticleCollection pai.
        """
        detail = {}
        logging.info(f"Checking page {self.url} force_update={force_update} status={self.status}")
        if self.status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT:
            if not force_update:
                return detail

        try:
            self.status = choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE
    
            response = check_url(self.url, timeout)
            content = response.get("content")
            self.status = choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE

            if self.fmt in ("html", "xml"):
                if not article_metadata:
                    article = self.article
                    lang_code = self.lang.code2 if self.lang else None
                    article_metadata = article.get_metadata_items(lang_code)
                response = check_content(article_metadata, content, self.fmt)
                detail.update(response)
                try:
                    rate = response["rate"]
                except KeyError:
                    raise Exception("Unable to check content")

                if rate >= 0.5:
                    self.status = choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
                else:
                    # detail["content"] = content
                    # detail["article_metadata"] = article_metadata
                    self.status = choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH
        except Exception as e:
            detail["error"] = str(e)

        self.detail = detail
        self.updated_by = user

        try:
            self.save()
        except Exception as e:
            logging.info(f"Erro ao salvar ARticleWebPage")
            logging.exception(e)

        logging.info(f"data: {self.data}")
        return self.data

    # ── Factory ──

    @classmethod
    def get_or_create_from_item(cls, user, article, collection, item):
        """
        Cria ou atualiza uma ArticleWebPage a partir de um dict de URL.

        Parameters
        ----------
        item : dict
            {"url": ..., "format": ..., "lang": ..., "purpose": ...}

        Returns
        -------
        ArticleWebPage
        """
        if not item["url"]:
            raise ValueError(f"ArticleWebPage.get_or_create_from_item requires url: {item}")
        lang_obj = Language.objects.filter(code2=item["lang"]).first()
        page, created = cls.objects.get_or_create(
            article=article,
            collection=collection,
            purpose=item["purpose"],
            fmt=item["format"],
            lang=lang_obj,
            defaults={"url": item["url"], "creator": user},
        )
        if not created:
            page.update_url_if_changed(item["url"], user)
        return page


def article_source_path(instance, filename):
    """Define o caminho para upload de arquivos de fonte de artigos"""
    # filename é "{sps_pkg_name}.xml"; não usa instance.sps_pkg_name para
    # não baixar o XML novamente antes de salvar o arquivo
    subdir = "/".join(os.path.splitext(filename)[0].split("-"))
    return f"article_sources/{subdir}/{filename}"


class ArticleSource(CommonControlField):
    """
    Represent article sources with URL or file

    Guarda o XML coletado (ex.: do OPAC via counter_dict) para não repetir
    o download enquanto a data de atualização na fonte (source_date)
    não mudar.

    Fields:
        created
        updated
        url
        file
        source_date
        status
    """

    class StatusChoices(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        COMPLETED = "completed", _("Completed")
        ERROR = "error", _("Error")
        REPROCESS = "reprocess", _("Reprocess")
        URL_ERROR = "url_error", _("URL Error")
        XML_ERROR = "xml_error", _("XML Error")
        NOT_PUBLIC = "not_public", _("Not public")

    url = models.URLField(
        verbose_name=_("Article URL"),
        max_length=200,
        blank=True,
        null=True,
        help_text=_("Article URL"),
    )
    file = models.FileField(
        verbose_name=_("Article file"),
        upload_to=article_source_path,
        null=True,
        blank=True,
        help_text=_("Upload article file"),
    )
    source_date = models.CharField(
        verbose_name=_("Source date"),
        # data (YYYY-MM-DD) ou data e hora completas (ISO 8601),
        # ex.: updated do OPAC "2026-10-28T02:42:17"
        max_length=32,
        null=True,
        blank=True,
        help_text=_("Date of data collection or original data date"),
    )
    status = models.CharField(
        verbose_name=_("Status"),
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        help_text=_("Processing status of the article source"),
    )
    pid_provider_xml = models.ForeignKey(
        PidProviderXML,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("PID Provider XML"),
        help_text=_("Related PID Provider XML instance"),
    )
    detail = models.JSONField(null=True, blank=True, default=None)
    pid = models.CharField(max_length=24, null=True, blank=True)
    collection = models.ForeignKey(
        Collection,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name=_("Collection"),
        help_text=_("Related Collection instance"),
    )

    base_form_class = CoreAdminModelForm

    panels = [
        FieldPanel("url", read_only=True),
        FieldPanel("file", read_only=True),
        FieldPanel("source_date", read_only=True),
        FieldPanel("status"),
        FieldPanel("collection", read_only=True),
        FieldPanel("pid", read_only=True),
        FieldPanel("pid_provider_xml", read_only=True),
        FieldPanel("detail", read_only=True),
    ]

    @staticmethod
    def autocomplete_custom_queryset_filter(search_term):
        return ArticleSource.objects.filter(
            Q(url__icontains=search_term) | Q(file__icontains=search_term)
        )

    def autocomplete_label(self):
        return str(self)

    class Meta:
        verbose_name = _("Article Source")
        verbose_name_plural = _("Article Sources")
        indexes = [
            models.Index(fields=["url"]),
            models.Index(fields=["source_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["status", "updated"]),
            models.Index(fields=["pid_provider_xml"]),
        ]

    def __str__(self):
        if self.url:
            return f"{self.url}"
        elif self.file:
            return f"{self.file.name}"
        return f"ArticleSource #{self.pk}"

    @classmethod
    def get(cls, url):
        if url:
            try:
                return cls.objects.get(url__iexact=url)
            except cls.MultipleObjectsReturned:
                return cls.objects.filter(url__iexact=url).first()

        raise ValueError("ArticleSource.get requires url")

    @classmethod
    def create(
        cls,
        user,
        url=None,
        source_date=None,
        collection=None,
        pid=None,
        is_public=None,
        detail=None,
    ):
        if not url:
            raise ValueError("ArticleSource.create requires url")

        try:
            obj = cls()
            obj.creator = user
            obj.url = url
            obj.source_date = source_date
            obj.collection = collection
            obj.pid = pid
            obj.detail = detail
            if is_public is False:
                obj.status = cls.StatusChoices.NOT_PUBLIC
            else:
                obj.status = cls.StatusChoices.PENDING
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(url=url)

    @classmethod
    def create_or_update(
        cls,
        user,
        url=None,
        source_date=None,
        collection=None,
        pid=None,
        force_update=None,
        auto_solve_pid_conflict=False,
        is_public=None,
        detail=None,
        expected_pid_v3=None,
    ):
        """
        Cria ou atualiza o ArticleSource e garante XML e PidProviderXML.

        O XML só é baixado novamente se ainda não existe em disco, se
        source_date mudou (o documento foi atualizado na fonte) ou se
        force_update=True.
        """
        try:
            obj = cls.get(url=url)
            source_changed = bool(source_date) and obj.source_date != source_date
            changed = obj.update(
                source_date,
                collection,
                pid,
                is_public,
                detail,
            )
        except cls.DoesNotExist:
            obj = cls.create(
                user,
                url=url,
                source_date=source_date,
                collection=collection,
                pid=pid,
                is_public=is_public,
                detail=detail,
            )
            source_changed = False
            changed = True
        add_pid_provider_changed = obj.add_pid_provider(
            user,
            force_update,
            auto_solve_pid_conflict,
            expected_pid_v3=expected_pid_v3,
            source_changed=source_changed,
        )
        if changed or add_pid_provider_changed:
            obj.updated_by = user
            obj.save()
        return obj

    def update(
        self,
        source_date,
        collection,
        pid,
        is_public,
        detail=None,
    ):
        changed = False
        if self.source_date != source_date:
            self.source_date = source_date
            changed = True
        if self.collection != collection:
            self.collection = collection
            changed = True
        if self.pid != pid:
            self.pid = pid
            changed = True
        if detail is not None and self.detail != detail:
            self.detail = detail
            changed = True
        if is_public is False and self.status != ArticleSource.StatusChoices.NOT_PUBLIC:
            self.status = ArticleSource.StatusChoices.NOT_PUBLIC
            changed = True
        elif (
            is_public is True
            and self.status == ArticleSource.StatusChoices.NOT_PUBLIC
        ):
            self.status = ArticleSource.StatusChoices.PENDING
            changed = True
        return changed

    def get_pid_provider_xml_id(self):
        try:
            return self.pid_provider_xml.id
        except AttributeError:
            pass

    @property
    def has_file(self):
        return bool(self.file) and os.path.isfile(self.file.path)

    @cached_property
    def xml_with_pre(self):
        if self.has_file:
            try:
                return list(XMLWithPre.create(path=self.file.path))[0]
            except Exception:
                pass
        if self.pid_provider_xml:
            try:
                return self.pid_provider_xml.xml_with_pre
            except AttributeError:
                pass
        if self.url:
            try:
                return list(XMLWithPre.create(uri=self.url))[0]
            except Exception:
                pass

    @cached_property
    def sps_pkg_name(self):
        try:
            return self.xml_with_pre.sps_pkg_name
        except Exception:
            pass

    def request_xml(self):
        if not self.url:
            raise ValueError("URL is required")

        try:
            xml_with_pre = list(XMLWithPre.create(uri=self.url))[0]
        except NonRetryableError as e:
            raise RequestXMLException(
                f"Non-retryable error while requesting XML: {e}"
            ) from e
        except Exception as e:
            raise XMLException(f"Error while requesting XML: {e}") from e

        self.save_file(
            f"{xml_with_pre.sps_pkg_name}.xml",
            xml_with_pre.tostring(pretty_print=True),
        )
        # evita nova leitura do XML recém-baixado
        self.__dict__["xml_with_pre"] = xml_with_pre
        self.__dict__.pop("sps_pkg_name", None)

    def save_file(self, filename, content):
        try:
            self.file.delete(save=False)
        except Exception:
            pass
        self.file.save(filename, ContentFile(content), save=False)

    # Métodos para controle de status
    def mark_as_processing(self):
        """Marca como processando"""
        self.status = self.StatusChoices.PROCESSING
        self.save()

    def mark_as_completed(self):
        """Marca como concluído"""
        self.status = self.StatusChoices.COMPLETED

    def mark_as_error(self):
        """Marca como erro"""
        self.status = self.StatusChoices.ERROR

    def mark_as_url_error(self):
        """Marca como erro de URL"""
        self.status = self.StatusChoices.URL_ERROR

    def mark_as_xml_error(self):
        """Marca como erro de XML"""
        self.status = self.StatusChoices.XML_ERROR

    def mark_for_reprocess(self):
        """Marca para reprocessamento"""
        self.status = self.StatusChoices.REPROCESS
        self.save()

    # Métodos de consulta por status
    @classmethod
    def get_pending(cls):
        """Retorna fontes pendentes"""
        return cls.objects.filter(status=cls.StatusChoices.PENDING)

    @classmethod
    def get_for_reprocess(cls):
        """Retorna fontes marcadas para reprocessamento"""
        return cls.objects.filter(status=cls.StatusChoices.REPROCESS)

    @classmethod
    def get_processing(cls):
        """Retorna fontes em processamento"""
        return cls.objects.filter(status=cls.StatusChoices.PROCESSING)

    @classmethod
    def get_completed(cls):
        """Retorna fontes concluídas"""
        return cls.objects.filter(status=cls.StatusChoices.COMPLETED)

    @classmethod
    def get_with_errors(cls):
        """Retorna fontes com erro"""
        return cls.objects.filter(
            status__in=[
                cls.StatusChoices.ERROR,
                cls.StatusChoices.URL_ERROR,
                cls.StatusChoices.XML_ERROR,
            ]
        )

    @classmethod
    def get_needs_processing(cls):
        """Retorna fontes que precisam ser processadas (pending + reprocess)"""
        return cls.objects.filter(
            status__in=[cls.StatusChoices.PENDING, cls.StatusChoices.REPROCESS]
        )

    def add_pid_provider(
        self,
        user,
        force_update=False,
        auto_solve_pid_conflict=False,
        expected_pid_v3=None,
        source_changed=False,
    ):
        """
        Executa o pipeline de obtenção de XML e registro de PID para este
        ArticleSource. Evita refazer etapas já concluídas, a menos que
        ``force_update=True``.

        Etapas:
            1. request_xml  — baixa o XML da URL e salva em ``self.file``
               • Pula se ``self.file`` já existe em disco, ``source_changed``
                 é False e ``force_update`` é False
            2. request_pid  — registra o XML no PidProvider e associa ``self.pid_provider_xml``
               • Pula se ``self.pid_provider_xml`` já está associado, o XML
                 não foi baixado novamente e ``force_update`` é False

        Se uma etapa anterior falhou (ex: tem arquivo mas não tem
        pid_provider_xml), somente a etapa faltante é executada.
        """
        changed = False
        try:
            if self.status == ArticleSource.StatusChoices.NOT_PUBLIC:
                if not force_update:
                    return changed

            xml_requested = False
            if force_update or source_changed or not self.has_file:
                # faz download do xml
                self.request_xml()
                xml_requested = True
                changed = True

            if force_update or xml_requested or not self.pid_provider_xml:
                # atribui pid_provider_xml
                self.request_pid(
                    user, force_update, auto_solve_pid_conflict, expected_pid_v3
                )
                changed = True

            if changed:
                self.mark_as_completed()
                if self.detail:
                    for key in ("error_type", "error_msg", "traceback"):
                        self.detail.pop(key, None)
        except Exception as e:
            if isinstance(e, XMLException):
                self.mark_as_xml_error()
            elif isinstance(e, RequestXMLException):
                self.mark_as_url_error()
            else:
                self.mark_as_error()
            self.detail = self.detail or {}
            self.detail.update(
                {
                    "error_type": str(type(e)),
                    "error_msg": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
            changed = True
        return changed

    def request_pid(
        self, user, force_update, auto_solve_pid_conflict, expected_pid_v3=None
    ):
        # import local: pid_provider.provider depende de tracker e profiling
        from pid_provider.provider import PidProvider

        xml_with_pre = self.xml_with_pre
        if not xml_with_pre:
            raise XMLException(f"Unable to read XML of {self}")

        if expected_pid_v3 and xml_with_pre.v3 != expected_pid_v3:
            raise ArticleSourcePidV3MismatchError(
                f"PID v3 mismatch: source={expected_pid_v3}, xml={xml_with_pre.v3}"
            )

        collection_acron = self.collection and self.collection.acron
        response = PidProvider().provide_pid_for_xml_with_pre(
            xml_with_pre,
            f"{collection_acron}_{xml_with_pre.v3}",
            user,
            # PidProviderXML.origin_date guarda somente a data (YYYY-MM-DD)
            origin_date=self.source_date and self.source_date[:10],
            force_update=force_update,
            is_published=None,
            origin=self.url,
            registered_in_core=False,
            auto_solve_pid_conflict=auto_solve_pid_conflict,
        )
        error_msg = response.get("error_msg") or response.get("error_message")
        v3 = response.get("v3")
        if error_msg or not v3:
            raise UnableToRegisterPIDError(error_msg or response)

        # Associa o PidProviderXML ao ArticleSource
        try:
            self.pid_provider_xml = PidProviderXML.get_by_pid_v3(v3)
        except PidProviderXML.DoesNotExist:
            raise UnableToRegisterPIDError(f"Unable to get by pid v3: {v3}")
