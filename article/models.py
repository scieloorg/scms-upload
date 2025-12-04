import logging
import sys
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.models.article_titles import ArticleTitles
from packtools.sps.models.article_toc_sections import ArticleTocSections
from packtools.sps.models.dates import ArticleDates
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article.forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from collection import choices as collection_choices
from collection.models import Collection, Language, WebSiteConfiguration
from core.models import CommonControlField, HTMLTextModel
from doi.models import DOIWithLang
from issue.models import TOC, Issue, TocSection
from journal.models import Journal, JournalSection, OfficialJournal
from package.models import SPSPkg
from pid_provider.models import PidProviderXML
from researcher.models import Researcher

from . import choices
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()


class Article(ClusterableModel, CommonControlField):
    """
    No contexto de Upload, Article deve conter o mínimo de campos,
    suficiente para o processo de ingresso / validações,
    pois os dados devem ser obtidos do XML
    """

    pp_xml = models.ForeignKey(
        PidProviderXML,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    sps_pkg = models.ForeignKey(
        SPSPkg, blank=True, null=True, on_delete=models.SET_NULL
    )
    # PID v3
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)
    pid_v2 = models.CharField(_("PID v2"), max_length=23, blank=True, null=True)

    # Article type
    article_type = models.CharField(
        _("Article type"),
        max_length=32,
        choices=choices.ARTICLE_TYPE,
        blank=True,
        null=True,
    )

    # Article status
    status = models.CharField(
        _("Article status"),
        max_length=32,
        choices=choices.ARTICLE_STATUS,
        blank=True,
        null=True,
    )
    position = models.PositiveIntegerField(_("Position"), blank=True, null=True)
    
    # futuramente substituir first_publication_date por first_pubdate_iso
    first_publication_date = models.DateField(null=True, blank=True)
    first_pubdate_iso = models.CharField(
        _("First publication date ISO"), max_length=10, blank=True, null=True
    )
    # Page
    elocation_id = models.CharField(
        _("Elocation ID"), max_length=64, blank=True, null=True
    )
    fpage = models.CharField(_("First page"), max_length=16, blank=True, null=True)
    lpage = models.CharField(_("Last page"), max_length=16, blank=True, null=True)

    # External models
    issue = models.ForeignKey(Issue, blank=True, null=True, on_delete=models.SET_NULL)
    journal = models.ForeignKey(
        Journal, blank=True, null=True, on_delete=models.SET_NULL
    )
    related_items = models.ManyToManyField(
        "self", symmetrical=False, through="RelatedItem", related_name="related_to"
    )

    sections = models.ManyToManyField(JournalSection, verbose_name=_("sections"))

    panel_article_ids = MultiFieldPanel(
        heading="Article identifiers", classname="collapsible"
    )
    panel_article_ids.children = [
        # FieldPanel("pid_v2"),
        FieldPanel("pid_v3", read_only=True),
        # FieldPanel("aop_pid"),
    ]

    panel_article_details = MultiFieldPanel(
        heading="Article details", classname="collapsible"
    )
    panel_article_details.children = [
        FieldPanel("first_pubdate_iso", read_only=True),
        FieldPanel("article_type", read_only=True),
        FieldPanel("status", read_only=True),
        InlinePanel(relation_name="title_with_lang", label="Title with Language"),
        FieldPanel("elocation_id", read_only=True),
        FieldPanel("fpage", read_only=True),
        FieldPanel("lpage", read_only=True),
    ]

    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel("issue", classname="collapsible", read_only=True),
    ]

    base_form_class = ArticleForm

    class Meta:
        indexes = [
            models.Index(fields=["pid_v3"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["position", "fpage", "-first_pubdate_iso"]

        permissions = (
            (MAKE_ARTICLE_CHANGE, _("Can make article change")),
            (REQUEST_ARTICLE_CHANGE, _("Can request article change")),
        )

    @classmethod
    def autocomplete_custom_queryset_filter(cls, term):
        return cls.objects.filter(
            Q(sps_pkg__sps_pkg_name__endswith=term)
            | Q(title_with_lang__text__icontains=term)
        )

    def autocomplete_label(self):
        return str(self)

    def __str__(self):
        return self.sps_pkg.sps_pkg_name

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
            pubdate
            and pubdate
            <= datetime.now(timezone.utc).isoformat()[:10]
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
        # TODO completar com itens que identifique o artigo
        return dict(
            xml=self.sps_pkg and self.sps_pkg.xml_uri,
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

    @classmethod
    def delete_unlink_articles(cls, user, journal, issue=None):
        result = {}
        result.update(cls.delete_by_pp_xml_status(user, journal, issue))
        result.update(cls.delete_by_duplicated_pkg_name(user, journal, issue))
        if result:
            logging.info(f"result: {result}")
        return result

    @classmethod
    def delete_by_pp_xml_status(cls, user, journal, issue=None):
        params = {}
        if issue:
            params["issue"] = issue

        to_update = []
        to_delete = []
        qs = cls.objects.filter(
            pp_xml__isnull=True,
            journal=journal,
            **params,
        )
        for item in qs.only("id", "pid_v3", "updated_by", "pp_xml"):
            try:
                item.pp_xml = PidProviderXML.objects.get(v3=item.pid_v3)
                item.updated_by = user
                to_update.append(item)
            except PidProviderXML.DoesNotExist:
                to_delete.append(item.id)  # Adiciona à lista
            except Exception as e:
                logging.exception(e)
            logging.info(f"{to_update}")
            logging.info(f"{to_delete}")

        if not to_delete and not to_update:
            return {}

        # Processa os itens acumulados para atualização (pp_xml)
        if to_update:
            cls.objects.bulk_update(to_update, ["pp_xml", "updated_by"])
        # Processa os IDs acumulados para deleção (sem pp_xml)
        if to_delete:
            # Usa a lista diretamente no id__in
            deleted_info = cls.objects.filter(id__in=to_delete).delete()
        return {"updated": len(to_update), "deleted": len(to_delete)}

    @classmethod
    def delete_by_duplicated_pkg_name(cls, user, journal, issue=None):
        params = {}
        if issue:
            params["issue"] = issue

        qs = cls.objects.filter(**params)
        duplicated_pkg_names = (
            qs.values("sps_pkg__sps_pkg_name")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .values_list("sps_pkg__sps_pkg_name", flat=True)
        )
        logging.info(f"duplicated_pkg_names: {params} {len(duplicated_pkg_names)}")
        if not duplicated_pkg_names:
            return {}

        # Para cada nome duplicado, mantém apenas o registro mais recente
        to_keep = []
        for pkg_name in duplicated_pkg_names:
            # Pega todos os registros com esse nome, ordena por ID (ou data)
            keep = (
                qs.filter(sps_pkg__sps_pkg_name=pkg_name)
                .order_by("-updated")  # ou '-created_at' se tiver campo de data
                .values_list("id", flat=True)[0]
            )
            # Adiciona todos exceto o primeiro (mais recente) para deletar
            logging.info(f"keep: {keep}")
            to_keep.append(keep)
        logging.info(f"to_keep: {to_keep}")
        # Deleta os registros duplicados
        deleted_count = qs.exclude(id__in=to_keep).delete()
        return {"deleted": deleted_count[0]}

    @classmethod
    def get(cls, pid_v3):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)
        raise ValueError("Article.get requires pid_v3")

    @classmethod
    def create_or_update(cls, user, sps_pkg, issue=None, journal=None, position=None):
        if not sps_pkg or sps_pkg.pid_v3 is None:
            raise ValueError("create_article requires sps_pkg with pid_v3")

        try:
            obj = cls.get(sps_pkg.pid_v3)
            obj.updated_by = user
        except cls.DoesNotExist:
            obj = cls()
            obj.pid_v3 = sps_pkg.pid_v3
            obj.creator = user

        obj.sps_pkg = sps_pkg

        xml_with_pre = sps_pkg.xml_with_pre
        obj.pid_v2 = xml_with_pre.v2
        obj.article_type = xml_with_pre.xmltree.find(".").get("article-type")

        if journal:
            obj.journal = journal
        else:
            obj.add_journal(user)
        if issue:
            obj.issue = issue
        else:
            obj.add_issue(user)

        obj.status = obj.status or choices.AS_READY_TO_PUBLISH
        obj.add_pages()
        obj.add_position(position, xml_with_pre.fpage)
        obj.add_article_publication_date()
        obj.add_pp_xml()
        obj.save()

        obj.add_sections(user)
        obj.add_article_titles(user)
        obj.add_doi_with_lang(user, xml_with_pre.article_doi_with_lang)
        return obj

    def add_doi_with_lang(self, user, article_doi_with_lang):
        for item in article_doi_with_lang:
            try:
                ArticleDOIWithLang.get_or_create(
                    user, self, item["value"], item["lang"]
                )
            except Exception as e:
                logging.exception(e)

    def add_pp_xml(self, save=False):
        if not self.pp_xml:
            try:
                self.pp_xml = PidProviderXML.objects.get(v3=self.pid_v3)
            except PidProviderXML.DoesNotExist:
                pass
            else:
                if save:
                    self.save()
                return self

    def add_related_item(self, target_doi, target_article_type):
        self.save()
        # TODO
        # item = RelatedItem()
        # item.item_type = target_article_type
        # item.source_article = self
        # item.target_article = target_location
        # item.save()
        # self.related_items.add(item)

    def add_pages(self):
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.fpage = xml_with_pre.fpage
        self.fpage_seq = xml_with_pre.fpage_seq
        self.lpage = xml_with_pre.lpage
        self.elocation_id = xml_with_pre.elocation_id

    def add_issue(self, user):
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.issue = Issue.get(
            journal=self.journal,
            volume=xml_with_pre.volume,
            supplement=xml_with_pre.suppl,
            number=xml_with_pre.number,
        )

    def add_journal(self, user):
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.journal = Journal.get(
            official_journal=OfficialJournal.get(
                issn_electronic=xml_with_pre.journal_issn_electronic,
                issn_print=xml_with_pre.journal_issn_print,
            ),
        )

    def add_article_titles(self, user):
        titles = ArticleTitles(
            xmltree=self.sps_pkg.xml_with_pre.xmltree,
        ).article_title_list
        self.title_with_lang.all().delete()
        for title in titles:
            try:
                obj = ArticleTitle.create_or_update(
                    user,
                    parent=self,
                    text=title.get("html_text"),
                    language=Language.get(
                        code2=title.get("language") or title.get("lang")
                    ),
                )
                self.title_with_lang.add(obj)
            except Exception as e:
                logging.exception(e)

    def add_sections(self, user):
        self.sections.all().delete()

        xml_sections = ArticleTocSections(
            xmltree=self.sps_pkg.xml_with_pre.xmltree,
        )

        items = xml_sections.article_section
        items.extend(xml_sections.sub_article_section)

        try:
            toc = TOC.objects.get(issue=self.issue)
        except TOC.DoesNotExist:
            toc = TOC.create_or_update(user, self.issue, ordered=False)

        group = None
        for item in items:
            logging.info(f"section: {item}")
            if not item.get("text"):
                continue
            section = self.journal.get_section(
                user,
                obj_lang=Language.get(code2=item.get("lang")),
                code=item.get("code"),
                text=item.get("text"),
            )
            self.sections.add(section)
            group = group or section.code or TocSection.create_group(self.issue)
            TocSection.create_or_update(user, toc, group, section)

    def add_article_publication_date(self):
        if self.sps_pkg.is_public:
            # atualiza somente se o artigo é considerado público
            value = self.sps_pkg.pub_date
            self.first_pubdate_iso = value
            self.first_publication_date = datetime.fromisoformat(value)
            self.save()

    def add_position(self, position=None, fpage=None):
        try:
            self.position = int(position or fpage)
            return
        except (ValueError, TypeError):
            pass

        # gera position
        if not self.created:
            self.save()
        position = TocSection.get_section_position(self.issue, self.sections) or 0

        sections = [item.text for item in self.sections.all()]
        self.position = (
            position * 10000
            + Article.objects.filter(sections__text__in=sections).count()
        )

    @property
    def multilingual_sections(self):
        return TocSection.multilingual_sections(self.issue, self.sections)

    @property
    def display_sections(self):
        return str(self.multilingual_sections)

    def update_status(self, new_status=None, rollback=False):
        # AS_UPDATE_SUBMITTED = "update-submitted"
        # AS_ERRATUM_SUBMITTED = "erratum-submitted"
        # AS_REQUIRE_UPDATE = "required-update"
        # AS_REQUIRE_ERRATUM = "required-erratum"
        # AS_PREPARE_TO_PUBLISH = "prepare-to-publish"
        # AS_READY_TO_PUBLISH = "ready-to-publish"
        # AS_SCHEDULED_TO_PUBLISH = "scheduled-to-publish"
        # AS_PUBLISHED = "published"

        # TODO create PublicationEvent

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

    def get_urls(self, website_url):
        journal_acron = self.journal.journal_acron
        pid_v2 = self.pid_v2
        pid_v3 = self.pid_v3

        for item in self.htmls:
            lang = item.get("lang")
            if not lang:
                continue
            yield f"{website_url}/j/{journal_acron}/a/{pid_v3}/?lang={lang}"
            yield f"{website_url}/scielo.php?script=sci_arttext&pid={pid_v2}&tlng={lang}"

        for item in self.pdfs:
            lang = item.get("lang")
            if not lang:
                continue
            yield f"{website_url}/j/{journal_acron}/a/{pid_v3}/?lang={lang}&format=pdf"
            yield f"{website_url}/scielo.php?script=sci_pdf&pid={pid_v2}&tlng={lang}"


class ArticleDOIWithLang(Orderable, DOIWithLang):
    article = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="doi_with_lang"
    )

    class Meta:
        verbose_name = _("Article DOI with Language")
        verbose_name_plural = _("Article DOIs with Language")

    def __unicode__(self):
        return f"{self.lang}: {self.doi}"

    def __str__(self):
        return f"{self.lang}: {self.doi}"

    @classmethod
    def get(cls, article=None, doi=None, lang=None):
        if lang and isinstance(lang, str):
            lang = Language.get(code2=lang)

        if article and doi and lang:
            try:
                return cls.objects.get(article=article, doi__iexact=doi, lang=lang)
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
            f"ArticleDOIWithLang.get missing params {dict(article=article, doi=doi, lang=lang)}"
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
            f"ArticleDOIWithLang.create missing params {dict(article=article, doi=doi, lang=lang)}"
        )

    @classmethod
    def get_or_create(cls, user, article=None, doi=None, lang=None):
        if article and doi and lang:
            # cria ou obtém
            try:
                return cls.get(article, doi, lang)
            except cls.DoesNotExist:
                return cls.create(user, article, doi, lang)
        # só obtém
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
        return f"{self.source_article} - {self.target_article} ({self.item_type})"

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


class PublicationEvent:
    article = ParentalKey(
        Article,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="publication_events",
    )
    website = models.ForeignKey(
        WebSiteConfiguration, null=True, blank=True, on_delete=models.SET_NULL
    )
    creator = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(verbose_name=_("Creation date"), auto_now_add=True)
    is_public = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Publication")
        verbose_name_plural = _("Publications")

        unique_together = [("website", "created")]
        indexes = [
            models.Index(fields=["website"]),
            models.Index(fields=["created"]),
        ]
        ordering = ["article", "website", "-created"]

    def __str__(self):
        return f"{self.website} {self.is_public} {self.created}"

    @property
    def data(self):
        return {
            "website": self.website,
            "is_public": self.is_public,
            "created": self.created.isoformat(),
        }

    @classmethod
    def create(cls, article, website, is_public, user=None):
        if article or website:
            try:
                obj = cls()
                obj.article = article
                obj.website = website
                obj.is_public = is_public
                obj.creator = user
                obj.save()
                return obj
            except IntegrityError:
                return cls.objects.get(
                    article=article, website=website, created=obj.created
                )
        raise ValueError(
            f"PublicationEvent.create missing params {dict(article=article, website=website)}"
        )

    @staticmethod
    def get_current(article, website):
        return (
            PublicationEvent.objects.filter(article=article, website=website)
            .order_by("-created")
            .first()
        )
