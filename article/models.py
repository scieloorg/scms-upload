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

from migration import choices as migration_choices
from migration.models import MigratedArticle, ClassicWebsiteConfiguration
from article.page_checker import check_url, check_content, format_url, format_classic_url
from article.forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from collection.choices import PUBLIC
from collection.models import Language, Collection
from core.models import CommonControlField, HTMLTextModel
from doi.models import DOIWithLang
from issue.models import TOC, Issue, TocSection
from journal.models import Journal, JournalSection, OfficialJournal
from package.models import SPSPkg
from pid_provider.models import PidProviderXML
from pid_provider.choices import PPXML_STATUS_INVALID
from . import choices
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()

# Constantes de Entrada (Webpage Status)
ARTICLE_WEBPAGE_STATUS_UNAVAILABLE = "unavailable"
ARTICLE_WEBPAGE_STATUS_AVAILABLE = "available"
ARTICLE_WEBPAGE_STATUS_VALID_CONTENT = "valid_content"
ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH = "content_mismatch"
ARTICLE_WEBPAGE_STATUS_NOT_CHECKED = "not-checked"

# Constantes de Saída (PID Status)
PID_STATUS_CLASSIC_MATCHED = "classic_ok"
PID_STATUS_CLASSIC_MISMATCHED = "classic_nok"
PID_STATUS_CLASSIC_NOT_FOUND = "classic_nfound"
PID_STATUS_CLASSIC_FOUND = "classic_found"


def get_pid_status_from_webpage_status(article_status: str) -> str:
    """
    Realiza a correspondência entre o status da página e o status do PID.
    """
    mapping = {
        choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE: migration_choices.PID_STATUS_CLASSIC_FOUND,
        choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT: migration_choices.PID_STATUS_CLASSIC_MATCHED,
        choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH: migration_choices.PID_STATUS_CLASSIC_MISMATCHED,
        choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE: migration_choices.PID_STATUS_CLASSIC_NOT_FOUND,
        choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED: migration_choices.PID_STATUS_UNKNOWN,
    }

    # Retorna o valor mapeado ou o status de 'not found' por padrão
    return mapping.get(article_status, migration_choices.PID_STATUS_UNKNOWN)


# ============================================================
# Article
# ============================================================


class Article(ClusterableModel, CommonControlField):
    """
    Modelo que representa um artigo no contexto de Upload.

    No contexto de Upload, Article deve conter o mínimo de campos,
    suficiente para o processo de ingresso/validações, pois os dados
    devem ser obtidos do XML.
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
    pid_v3 = models.CharField(
        _("PID v3"), max_length=23, blank=True, null=True, unique=True
    )
    pid_v2 = models.CharField(
        _("PID v2"), max_length=23, blank=True, null=True
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
        FieldPanel("pid_v2", read_only=True),
        FieldPanel("pid_v3", read_only=True),
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
    panel_collections = MultiFieldPanel(
        heading=_("Collections"), classname="collapsible"
    )
    panel_collections.children = [
        InlinePanel("article_collections", label="Collections"),
    ]

    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel("issue", classname="collapsible", read_only=True),
        panel_collections,
    ]

    base_form_class = ArticleForm

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
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
    def get(cls, pid_v3):
        if pid_v3:
            try:
                return cls.objects.get(pid_v3=pid_v3)
            except cls.MultipleObjectsReturned:
                qs = cls.objects.filter(pid_v3=pid_v3).order_by("-updated")
                obj = qs.first()
                if obj is None:
                    raise cls.DoesNotExist
                qs.exclude(pk=obj.pk).delete()
                return obj
        raise ValueError("Article.get requires pid_v3")

    @classmethod
    def delete_items_duplicated_by_pid_v2(cls, pid_v2):
        try:
            return cls.objects.get(pid_v2=pid_v2)
        except cls.MultipleObjectsReturned:
            items = cls.objects.filter(pid_v2=pid_v2).order_by("-updated")
            obj = items.first()
            items.exclude(id=obj.id).delete()
            return obj
        except cls.DoesNotExist:
            raise

    @classmethod
    def delete_items_duplicated_by_sps_pkg_name(cls, sps_pkg_name):
        try:
            return cls.objects.get(sps_pkg__sps_pkg_name=sps_pkg_name)
        except cls.MultipleObjectsReturned:
            items = cls.objects.filter(
                sps_pkg__sps_pkg_name=sps_pkg_name
            ).order_by("-updated")
            obj = items.first()
            items.exclude(id=obj.id).delete()
            return obj
        except cls.DoesNotExist:
            raise

    # ── create_or_update ──

    @classmethod
    def create_or_update(cls, user, sps_pkg, issue=None, journal=None, position=None):
        if not sps_pkg:
            raise ValueError("create_article requires sps_pkg with pid_v2")

        xml_with_pre = sps_pkg.xml_with_pre
        if not xml_with_pre:
            raise ValueError(f"SPSPkg {sps_pkg} is missing xml_with_pre")

        pid_v2 = xml_with_pre.v2
        if not pid_v2:
            raise ValueError(f"SPSPkg {sps_pkg} xml_with_pre is missing pid_v2")
        try:
            obj = cls.delete_items_duplicated_by_sps_pkg_name(sps_pkg.sps_pkg_name)
        except cls.DoesNotExist:
            try:
                obj = cls.delete_items_duplicated_by_pid_v2(pid_v2)
            except cls.DoesNotExist:
                obj = cls()
                obj.creator = user

        obj.pid_v3 = sps_pkg.pid_v3
        obj.pid_v2 = pid_v2
        obj.sps_pkg = sps_pkg
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

    # ── add_* helpers ──

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
        if not self.created:
            self.save()
        position = TocSection.get_section_position(self.issue, self.sections) or 0
        sections = [item.text for item in self.sections.all()]
        self.position = (
            position * 10000
            + Article.objects.filter(sections__text__in=sections).count()
        )

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

    def get_html_urls(self, website_url, purpose):
        """
        Gera dicts de URL para HTML do artigo.

        Parameters
        ----------
        website_url : str
        purpose : str
            ARTICLE_WEBPAGE_PURPOSE_CLASSIC, ARTICLE_WEBPAGE_PURPOSE_PUBLIC
            ou ARTICLE_WEBPAGE_PURPOSE_QA.

        Yields
        ------
        dict  {"url", "format", "lang", "purpose"}
        """
        pid_v2 = self.pid_v2
        pid_v3 = self.pid_v3
        is_classic = purpose == choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC

        if is_classic:
            journal_acron = None
        else:
            journal_acron = self.journal.journal_acron

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

    def get_pdf_urls(self, website_url, purpose):
        """
        Gera dicts de URL para PDF do artigo.

        Parameters
        ----------
        website_url : str
        purpose : str

        Yields
        ------
        dict  {"url", "format", "lang", "purpose"}
        """
        pid_v2 = self.pid_v2
        pid_v3 = self.pid_v3
        is_classic = purpose == choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC

        for item in self.pdfs:
            lang = item.get("lang")
            if not lang:
                continue
            if is_classic:
                url = format_classic_url(
                    website_url, pid_v2=pid_v2, format="pdf", lang_code=lang
                )
            else:
                journal_acron = self.journal.journal_acron
                url = format_url(
                    website_url, pid_v3, journal_acron, format="pdf", lang_code=lang
                )
            yield {
                "url": url,
                "format": "pdf",
                "lang": lang,
                "purpose": purpose,
            }

    def get_webpage_items(self, website_url, purpose):
        """Gera todos os itens de página (HTML + PDF) para um purpose."""
        yield from self.get_html_urls(website_url, purpose)
        yield from self.get_pdf_urls(website_url, purpose)

    def get_main_article_url(self, website_url):
        return format_url(website_url, self.pid_v3, self.journal.journal_acron)

    # ── repetitions / dedup ──

    @classmethod
    def get_repeated_items(cls, field_name, issue=None):
        if issue:
            queryset = cls.objects.filter(issue=issue)
        else:
            queryset = cls.objects.all()
        return (
            queryset.values(field_name)
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .values_list(field_name, flat=True)
        )

    @classmethod
    def exclude_articles_with_invalid_pid_v2(cls, issue=None):
        from proc.models import ArticleProc

        filters = {
            "pid__isnull": False,
            "migrated_data__isnull": False,
            "sps_pkg__isnull": False,
        }
        if issue:
            filters["issue_proc__issue"] = issue

        article_procs = ArticleProc.objects.filter(
            **filters
        ).select_related("migrated_data", "sps_pkg")

        sps_pkg_id_list = [
            ap.sps_pkg_id for ap in article_procs if ap.sps_pkg_id
        ]
        articles_by_sps_pkg = {}
        if sps_pkg_id_list:
            for article in (
                Article.objects.select_related("sps_pkg", "pp_xml")
                .filter(sps_pkg_id__in=sps_pkg_id_list)
                .only("id", "pid_v2", "sps_pkg_id", "pp_xml_id")
            ):
                articles_by_sps_pkg[article.sps_pkg_id] = article

        events = []
        sps_pkg_ids = set()
        pp_xml_ids = set()
        article_ids = []

        for article_proc in article_procs:
            try:
                article = articles_by_sps_pkg.get(article_proc.sps_pkg_id)
                if not article or not article.pid_v2:
                    continue
                if not MigratedArticle.valid_pid(article.pid_v2):
                    article_ids.append(article.id)
                    if article.sps_pkg_id:
                        sps_pkg_ids.add(article.sps_pkg_id)
                    if article.pp_xml_id:
                        pp_xml_ids.add(article.pp_xml_id)
            except Exception as e:
                events.append(
                    f"Error checking pid_v2 for ArticleProc {article_proc}: {e}"
                )

        if not article_ids:
            events.append("No migrated articles with invalid pid_v2 found")
            return events

        with transaction.atomic():
            deleted_articles, _ = cls.objects.filter(id__in=article_ids).delete()
            events.append(f"Articles deletados: {deleted_articles}")
            if sps_pkg_ids:
                deleted_sps, _ = SPSPkg.objects.filter(
                    id__in=sps_pkg_ids
                ).delete()
                events.append(f"SPSPkg deletados: {deleted_sps}")
            if pp_xml_ids:
                deleted_pp, _ = PidProviderXML.objects.filter(
                    id__in=pp_xml_ids
                ).delete()
                events.append(f"PidProviderXML deletados: {deleted_pp}")

        return events

    @classmethod
    def exclude_inconvenient_articles(cls, issue, user, timeout=None):
        results = {"events": [], "numbers": {}, "exceptions": []}

        try:
            events = cls.exclude_articles_with_invalid_pid_v2(issue)
            results["events"].extend(events)
        except Exception as e:
            results["exceptions"].append(
                {
                    "step": "exclude_articles_with_invalid_pid_v2",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )

        for field_name in ("pid_v2", "sps_pkg__sps_pkg_name"):
            repeated_values = list(cls.get_repeated_items(field_name, issue))
            results["numbers"][f"repeated_by_{field_name}"] = len(repeated_values)
            for value in repeated_values:
                try:
                    events = cls.exclude_repetitions(
                        user, field_name, value, timeout=timeout
                    )
                    results["events"].extend(events)
                except Exception as e:
                    results["exceptions"].append(
                        {
                            "step": f"repeated_by_{field_name}",
                            "value": value,
                            "traceback": traceback.format_exc(),
                        }
                    )

        return results

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
            sps_pkg__pkg_name = self.sps_pkg.sps_pkg_name
            sps_pkg__xml_with_pre__pkg_name = (
                self.sps_pkg.xml_with_pre.sps_pkg_name
            )
            pp_xml__xml_with_pre__pkg_name = (
                self.pp_xml.xml_with_pre.sps_pkg_name
            )
            return (
                sps_pkg__pkg_name
                == pp_xml__xml_with_pre__pkg_name
                == sps_pkg__xml_with_pre__pkg_name
            )
        except Exception as e:
            if self.pp_xml is not None:
                if self.pp_xml.proc_status != PPXML_STATUS_INVALID:
                    self.pp_xml.proc_status = PPXML_STATUS_INVALID
                    self.pp_xml.save()
            return False

    @classmethod
    def fix_sps_pkg_names(cls, issue):
        items = cls.objects.filter(
            issue=issue,
            sps_pkg__isnull=False,
            issue__supplement__isnull=False,
        ).exclude(
            Q(sps_pkg__sps_pkg_name__contains="-s"),
        )

        response = []
        for item in items:
            data = {}
            try:
                data["pid_v3"] = item.pid_v3
                data["pid_v2"] = item.pid_v2
                try:
                    data["sps_pkg__pkg_name"] = item.sps_pkg.sps_pkg_name
                    data["sps_pkg__pkg_name_fixed"] = item.fix_sps_pkg_name()
                except Exception:
                    data["sps_pkg__pkg_name_exception"] = traceback.format_exc()
                try:
                    data["pp_xml__pkg_name"] = item.pp_xml.pkg_name
                    data["pp_xml__pkg_name_fixed"] = item.pp_xml.fix_pkg_name(
                        data.get("sps_pkg__pkg_name")
                    )
                except Exception:
                    data["pp_xml__pkg_name_exception"] = traceback.format_exc()
            except Exception:
                data["exception"] = traceback.format_exc()
            response.append(data)
        return response

    def fix_sps_pkg_name(self):
        if self.sps_pkg:
            return self.sps_pkg.fix_sps_pkg_name()

    @classmethod
    def exclude_repetitions(cls, user, field_name, field_value, timeout=None):
        """
        Remove artigos duplicados para um dado campo.

        Usa o status agregado de ArticleCollection para ranking.
        """
        repeated_items = cls.objects.filter(**{field_name: field_value})
        total_initial = repeated_items.count()

        if total_initial <= 1:
            return [
                f"{field_name}='{field_value}': {total_initial} artigo(s), "
                "nenhuma ação necessária"
            ]

        events = [
            f"{field_name}='{field_value}': {total_initial} artigos encontrados"
        ]

        # ── Fase 1: pré-ranking via SQL usando ArticleCollection ──
        candidate_ids = list(
            repeated_items.annotate(
                has_valid_collection=models.Exists(
                    ArticleCollection.objects.filter(
                        article_id=models.OuterRef("pk"),
                        status=choices.ARTICLE_COLLECTION_STATUS_VALID,
                    )
                ),
                has_pp_xml=models.Case(
                    models.When(pp_xml__isnull=False, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
            )
            .order_by("-has_valid_collection", "-has_pp_xml", "-updated")
            .values_list("id", flat=True)[:2]
        )

        # ── Fase 2: check HTTP dos finalistas ──
        for article in cls.objects.filter(id__in=candidate_ids):
            for art_col in article.article_collections.all():
                art_col.check_pages(
                    user=user, timeout=timeout, force_update=True
                )

        events.append(
            f"Disponibilidade verificada para {len(candidate_ids)} finalista(s)"
        )

        # ── Fase 3: decisão ──
        repeated_items = cls.objects.filter(**{field_name: field_value})
        item_to_keep_id = cls.choose_item_to_keep(repeated_items)

        if not item_to_keep_id:
            item_to_keep_id = (
                repeated_items.order_by("-updated")
                .values_list("id", flat=True)
                .first()
            )

        if not item_to_keep_id:
            events.append("Erro: nenhum item encontrado para manter")
            return events

        events.append(f"Artigo mantido: ID {item_to_keep_id}")

        # ── Fase 4: deleção em bulk ──
        items_to_delete = repeated_items.exclude(id=item_to_keep_id)
        sps_pkg_ids = set(
            items_to_delete.exclude(sps_pkg__isnull=True).values_list(
                "sps_pkg_id", flat=True
            )
        )
        pp_xml_ids = set(
            items_to_delete.exclude(pp_xml__isnull=True).values_list(
                "pp_xml_id", flat=True
            )
        )
        article_ids = list(items_to_delete.values_list("id", flat=True))
        total_to_delete = len(article_ids)
        events.append(f"Artigos a deletar: {total_to_delete}")

        if not total_to_delete:
            return events

        with transaction.atomic():
            deleted_articles, _ = cls.objects.filter(
                id__in=article_ids
            ).delete()
            events.append(f"Articles deletados: {deleted_articles}")
            if sps_pkg_ids:
                deleted_sps, _ = SPSPkg.objects.filter(
                    id__in=sps_pkg_ids
                ).delete()
                events.append(f"SPSPkg deletados: {deleted_sps}")
            if pp_xml_ids:
                deleted_pp, _ = PidProviderXML.objects.filter(
                    id__in=pp_xml_ids
                ).delete()
                events.append(f"PidProviderXML deletados: {deleted_pp}")

        return events

    @classmethod
    def choose_item_to_keep(cls, queryset):
        return (
            queryset.annotate(
                has_valid_collection=models.Exists(
                    ArticleCollection.objects.filter(
                        article_id=models.OuterRef("pk"),
                        status=choices.ARTICLE_COLLECTION_STATUS_VALID,
                    )
                ),
                has_pp_xml=models.Case(
                    models.When(pp_xml__isnull=False, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
            )
            .order_by("-has_valid_collection", "-has_pp_xml", "-updated")
            .values_list("id", flat=True)
            .first()
        )

    # ── ArticleCollection: ponto de entrada ──

    def create_or_update_article_collections(self, user, force_update=None):
        """
        Obtém ou cria ArticleCollection para cada coleção do journal
        e delega a criação das ArticleWebPages.
        """
        art_col = None
        if not self.article_collections.exists() or force_update:
            for journal_proc in self.journal.journalproc_set.all():
                collection = journal_proc.collection
                art_col = ArticleCollection.get_or_create(user, self, collection)
                art_col.create_or_update_pages(user)
        return art_col

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

        if self.pid_v2:
            items.append(("pid_v2", self.pid_v2))
        if self.pid_v3:
            items.append(("pid_v3", self.pid_v3))
        if self.elocation_id:
            items.append(("elocation_id", self.elocation_id))
        if self.fpage:
            items.append(("fpage", self.fpage))
        if self.lpage:
            items.append(("lpage", self.lpage))

        try:
            xmltree = self.sps_pkg.xml_with_pre.xmltree
            contribs = xmltree.findall(
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

    def check_availability(self, user, collection=None, collection_id=None, purpose=None):
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
        for art_col in qs:
            yield from art_col.check_pages(
                user=user, purpose=purpose,
            )

    def get_classic_website_availability(self, collection):
        status = self.article_collections.filter(
            collection=collection,
            purpose=choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC,
        ).first().status 
        valid = status == choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE
        return {"valid": valid, "new_pid_status": get_pid_status_from_webpage_status(status)}
        
    def get_public_website_availability(self, collection):
        status = self.article_collections.filter(
            collection=collection,
            purpose=choices.ARTICLE_WEBPAGE_PURPOSE_PUBLIC,
        ).first().status 
        valid = status == choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE
        return {"valid": valid, "new_pid_status": get_pid_status_from_webpage_status(status)}
        

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

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="article_collections",
    )
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name="article_collections",
    )

    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=choices.ARTICLE_COLLECTION_STATUS,
        default=choices.ARTICLE_COLLECTION_STATUS_NOT_CHECKED,
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

    def update_aggregate_status(self):
        """Recalcula status a partir das ArticleWebPage filhas."""
        pages = self.pages.all()
        if not pages.exists():
            self.status = choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED
        elif pages.exclude(
            status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
        ).exists():
            self.status = choices.ARTICLE_WEBPAGE_STATUS_PARTIAL
        else:
            self.status = choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE
        self.save(update_fields=["status", "updated"])

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
        from collection.models import WebSiteConfiguration

        article = self.article
        existing_ids = set()

        # ── Websites novos (QA / PUBLIC) ──
        for ws_config in WebSiteConfiguration.objects.filter(
            collection=self.collection,
            enabled=True,
        ):
            purpose = ws_config.purpose  # "PUBLIC" ou "QA"
            for item in article.get_webpage_items(ws_config.url, purpose):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self, item
                )
                existing_ids.add(page.id)

        # ── Site clássico ──
        classic_ws = self.classic_website
        if classic_ws:
            purpose = choices.ARTICLE_WEBPAGE_PURPOSE_CLASSIC
            for item in article.get_html_urls(
                classic_ws.url, purpose
            ):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self, item
                )
                existing_ids.add(page.id)
                # obter apenas 1
                break
            for item in article.get_pdf_urls(
                classic_ws.url, purpose
            ):
                page = ArticleWebPage.get_or_create_from_item(
                    user, self, item
                )
                # obter apenas 1
                existing_ids.add(page.id)

        # Remove páginas órfãs
        self.pages.exclude(id__in=existing_ids).delete()
       
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
        article_metadata = self.article.get_metadata_by_lang()

        pages = self.pages.all()
        if purpose:
            pages = pages.filter(purpose=purpose)
        if not force_update:
            pages = pages.exclude(
                status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
            )

        for page in pages.select_related("lang"):
            lang_code = page.lang.code2 if page.lang else None
            yield page.check_page(
                user,
                timeout,
                article_metadata=article_metadata.get(lang_code),
                force_update=force_update,
            )


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

    article_collection = models.ForeignKey(
        ArticleCollection,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    purpose = models.CharField(
        _("Purpose"),
        max_length=8,
        choices=choices.ARTICLE_WEBPAGE_PURPOSE,
        help_text=_("Distinguishes between public, QA, and classic website pages."),
    )
    fmt = models.CharField(_("Format"), max_length=4, null=True, blank=True)
    lang = models.ForeignKey(
        Language,
        verbose_name=_("Language"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    url = models.CharField(_("URL"), max_length=265)
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
        FieldPanel("article_collection", read_only=True),
        FieldPanel("purpose", read_only=True),
        FieldPanel("url", read_only=True),
        FieldPanel("fmt", read_only=True),
        FieldPanel("lang", read_only=True),
        FieldPanel("status", read_only=True),
        FieldPanel("detail", read_only=True),
    ]

    class Meta:
        verbose_name = _("Article web page")
        verbose_name_plural = _("Article web pages")
        unique_together = ("article_collection", "purpose", "fmt", "lang")
        indexes = [
            models.Index(fields=["article_collection", "status"]),
            models.Index(fields=["article_collection", "purpose"]),
            models.Index(fields=["purpose", "status"]),
        ]

    def __str__(self):
        return f"{self.url} [{self.purpose}/{self.fmt}/{self.lang}] {self.status}"

    # ── Propagação ──

    def propagate_status(self):
        """Propaga status para o ArticleCollection pai."""
        self.article_collection.update_aggregate_status()

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
        }

    def check_page(
        self, user, timeout=None, article_metadata=None, force_update=None
    ):
        """
        Verifica disponibilidade e validade do conteúdo da página.

        Acessa a URL, verifica conteúdo contra os metadados do artigo,
        e propaga o status para o ArticleCollection pai.
        """
        detail = {
            "url": self.url,
            "format": self.fmt,
            "lang": self.lang.code2 if self.lang else None,
            "purpose": self.purpose,
            "status": self.status,
            "force_update": force_update,
        }

        if self.status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT:
            if not force_update:
                return detail

        try:
            response = check_url(self.url, timeout)
            content = response.get("content")
            if not content:
                raise ValueError("No content retrieved from URL")

            self.status = choices.ARTICLE_WEBPAGE_STATUS_AVAILABLE

            if not article_metadata:
                article = self.article_collection.article
                lang_code = self.lang.code2 if self.lang else None
                article_metadata = article.get_metadata_items(lang_code)
            if not article_metadata:
                raise ValueError(
                    "No article metadata available for content check"
                )

            response = check_content(article_metadata, content)
            if response.get("error"):
                raise ValueError(response["error"])
 
            detail.update(response)
            rate = response.get("rate", 0)
            if rate > 0.8:
                self.status = choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
            else:
                detail["content"] = content
                detail["article_metadata"] = article_metadata
                self.status = choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH
        except Exception as e:
            detail["error"] = str(e)
            self.status = choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE

        self.detail = detail
        self.updated_by = user
        self.save()
        self.propagate_status()

        detail["status"] = self.status
        detail["valid"] = (self.status == choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT)
        
        return detail

    # ── Factory ──

    @classmethod
    def get_or_create_from_item(cls, user, article_collection, item):
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
        lang_obj = Language.objects.filter(code2=item["lang"]).first()
        page, created = cls.objects.get_or_create(
            article_collection=article_collection,
            purpose=item["purpose"],
            fmt=item["format"],
            lang=lang_obj,
            defaults={"url": item["url"], "creator": user},
        )
        if not created:
            page.update_url_if_changed(item["url"], user)
        return page