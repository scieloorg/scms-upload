import logging
import traceback
from datetime import datetime, timezone

from django.db import transaction
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.models.article_titles import ArticleTitles
from packtools.sps.models.article_toc_sections import ArticleTocSections
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from article.forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from collection.models import Language
from core.models import CommonControlField, HTMLTextModel
from doi.models import DOIWithLang
from issue.models import TOC, Issue, TocSection
from journal.models import Journal, JournalSection, OfficialJournal
from package.models import SPSPkg
from pid_provider.models import PidProviderXML
from pid_provider.choices import PPXML_STATUS_INVALID
from tracker import choices as tracker_choices
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
        FieldPanel("pid_v2", read_only=True),
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
                self.pp_xml = PidProviderXML.get_by_pid_v3(pid_v3=self.pid_v3)
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
                language_code2 = title.get("language") or title.get("lang")
                if not language_code2:
                    raise ValueError(f"Missing language for article title: {title}")
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
            # atualiza somente se o artigo é considerado público
            value = self.sps_pkg.pub_date
            self.first_pubdate_iso = value
            self.first_publication_date = datetime.fromisoformat(value).date()
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
    
    @classmethod
    def get_repeated_items(cls, field_name, journal=None):
        if journal:
            queryset = cls.objects.filter(journal=journal)
        else:
            queryset = cls.objects.all()
        return (
            queryset.values(field_name)
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .values_list(field_name, flat=True)
        )

    @classmethod
    def select_articles(cls, journal_id_list=None, issue_id_list=None):
        kwargs = {}
        if journal_id_list:
            kwargs["journal__id__in"] = journal_id_list
        if issue_id_list:
            kwargs["issue__id__in"] = issue_id_list
        return cls.objects.filter(**kwargs).values_list("id", flat=True)
    
    def is_valid_record(self):
        try:
            if self.pp_xml is None:
                try:
                    self.pp_xml = PidProviderXML.get_by_pid_v3(self.pid_v3)
                except PidProviderXML.DoesNotExist:
                    return False
            sps_pkg__pkg_name = self.sps_pkg.xml_with_pre.sps_pkg_name
            pp_xml__pkg_name = self.pp_xml.xml_with_pre.spspkg_name
            return self.pkg_name == pp_xml__pkg_name == sps_pkg__pkg_name
        except Exception as e:
            if self.pp_xml is not None:
                if self.pp_xml.proc_status != PPXML_STATUS_INVALID:
                    self.pp_xml.proc_status = PPXML_STATUS_INVALID
                    self.pp_xml.save()
            return False

    @classmethod
    def fix_sps_pkg_names(cls, items):
        response = []
        for item in items:
            data = {}
            try:
                data["pid_v3"] = item.pid_v3
                data["pid_v2"] = item.pid_v2
                
                try:
                    data["sps_pkg__pkg_name"] = item.sps_pkg.sps_pkg_name
                    data["sps_pkg__pkg_name_fixed"] = item.fix_sps_pkg_name()
                except Exception as e:
                    data["sps_pkg__pkg_name_exception"] = traceback.format_exc()

                try:
                    data["pp_xml__pkg_name"] = item.pp_xml.pkg_name
                    data["pp_xml__pkg_name_fixed"] = item.pp_xml.fix_pkg_name(data["sps_pkg__pkg_name"])
                except Exception as e:
                    data["pp_xml__pkg_name_exception"] = traceback.format_exc()

            except Exception as e:
                data["exception"] = traceback.format_exc()
            response.append(data)
        return response

    def fix_sps_pkg_name(self):
        if self.sps_pkg:
            return self.sps_pkg.fix_sps_pkg_name()

    @classmethod
    def exclude_repetitions(cls, user, field_name, field_value, timeout=None):
        """
        Remove artigos duplicados baseado em um campo específico,
        mantendo o artigo mais relevante (publicado e válido tem prioridade).
        """
        repeated_items = cls.objects.filter(**{field_name: field_value})
        total_initial = repeated_items.count()
        
        if total_initial <= 1:
            return [f"{field_name}='{field_value}': {total_initial} artigo(s), nenhuma ação necessária"]
        
        events = [f"{field_name}='{field_value}': {total_initial} artigos encontrados"]
        
        # Atualiza status de disponibilidade antes de decidir qual manter
        cls.update_availability_status(user, timeout, repeated_items)
        
        # Recarrega queryset após atualização de status
        repeated_items = cls.objects.filter(**{field_name: field_value})
        
        item_to_keep_id = cls.choose_item_to_keep(repeated_items)
        if not item_to_keep_id:
            # Fallback: mantém o mais recentemente atualizado
            item_to_keep_id = repeated_items.order_by('-updated').values_list('id', flat=True).first()
        
        if not item_to_keep_id:
            events.append("Erro: nenhum item encontrado para manter")
            return events
        
        events.append(f"Artigo mantido: ID {item_to_keep_id}")
        
        # Coleta IDs relacionados em uma única passagem
        items_to_delete = repeated_items.exclude(id=item_to_keep_id).select_related('sps_pkg', 'pp_xml')
        
        sps_pkg_ids = set()
        pp_xml_ids = set()
        article_ids = []
        
        for item in items_to_delete:
            article_ids.append(item.id)
            if item.sps_pkg_id:
                sps_pkg_ids.add(item.sps_pkg_id)
            if item.pp_xml_id:
                pp_xml_ids.add(item.pp_xml_id)
        
        total_to_delete = len(article_ids)
        events.append(f"Artigos a deletar: {total_to_delete}")
        
        if not total_to_delete:
            return events
        
        # Executa deleções em transação atômica
        with transaction.atomic():
            deleted_articles, _ = cls.objects.filter(id__in=article_ids).delete()
            events.append(f"Articles deletados: {deleted_articles}")
            
            if sps_pkg_ids:
                deleted_sps, _ = SPSPkg.objects.filter(id__in=sps_pkg_ids).delete()
                events.append(f"SPSPkg deletados: {deleted_sps}")
            
            if pp_xml_ids:
                deleted_pp, _ = PidProviderXML.objects.filter(id__in=pp_xml_ids).delete()
                events.append(f"PidProviderXML deletados: {deleted_pp}")
        
        return events

    @classmethod
    def choose_item_to_keep(cls, queryset):
        result = {}
        for item in queryset.order_by("-updated"):
            valid = item.is_valid_record()
            try:
                published = item.availability_status.first().completed
            except AttributeError:
                published = False
            result.setdefault((published, valid), []).append(item)
        status = (
            (True, True),
            (True, False),
            (False, True),
            (False, False),
        )
        for key in status:
            items = result.get(key) or []
            if len(items) >= 1:
                return items[0].id

    @classmethod
    def update_availability_status(cls, user, timeout=None, queryset=None, filters=None):
        if not queryset:
            queryset = cls.objects
        if filters:
            queryset = queryset.filter(**filters)
        else:
            queryset = queryset.all()
        for item in queryset:
            try:
                item.availability_status.first().retry(user, timeout, force_update=True)
            except Exception:
                pass


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
