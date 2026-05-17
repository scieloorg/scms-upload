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

from migration.models import MigratedArticle
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


class Article(ClusterableModel, CommonControlField):
    """
    Modelo que representa um artigo no contexto de Upload.
    
    No contexto de Upload, Article deve conter o mínimo de campos,
    suficiente para o processo de ingresso/validações, pois os dados
    devem ser obtidos do XML.
    
    Attributes
    ----------
    pid_v3 : CharField
        Identificador persistente versão 3 (único).
    pid_v2 : CharField
        Identificador persistente versão 2.
    sps_pkg : ForeignKey
        Referência ao pacote SPS que contém o artigo.
    pp_xml : ForeignKey
        Referência ao registro no PidProvider XML.
    article_type : CharField
        Tipo do artigo (ex: research-article, editorial, etc).
    status : CharField
        Status do artigo no fluxo de publicação.
    issue : ForeignKey
        Referência ao fascículo que contém o artigo.
    journal : ForeignKey
        Referência ao periódico.
    
    Methods
    -------
    create_or_update(user, sps_pkg, issue=None, journal=None, position=None)
        Cria ou atualiza um artigo a partir de um pacote SPS.
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
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True, unique=True)
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
    fpage_seq = models.CharField(_("First page seq"), max_length=16, blank=True, null=True)
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
    panel_webpages = MultiFieldPanel(
        heading=_("Article webpages"), classname="collapsible"
    )
    panel_webpages.children = [
        InlinePanel("article_webpages", label="Webpages"),
    ]

    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel("issue", classname="collapsible", read_only=True),
        panel_webpages,
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
        """
        Obtém um artigo pelo PID v3, removendo duplicatas se necessário.
        
        Se múltiplos artigos existem com o mesmo pid_v3, mantém o mais
        recentemente atualizado e deleta os demais.
        
        Parameters
        ----------
        pid_v3 : str
            Identificador persistente versão 3.
            
        Returns
        -------
        Article
            Artigo correspondente ao pid_v3.
            
        Raises
        ------
        ValueError
            Se pid_v3 não foi informado.
        Article.DoesNotExist
            Se nenhum artigo é encontrado com o pid_v3.
        """
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
            items = cls.objects.filter(sps_pkg__sps_pkg_name=sps_pkg_name).order_by("-updated")
            obj = items.first()
            items.exclude(id=obj.id).delete()
            return obj
        except cls.DoesNotExist:
            raise

    @classmethod
    def create_or_update(cls, user, sps_pkg, issue=None, journal=None, position=None):
        """
        Cria ou atualiza um artigo a partir de um pacote SPS.
        
        Processa o pacote SPS para extrair informações do XML, cria ou
        atualiza o artigo e seus relacionamentos (títulos, seções, DOIs,
        etc).
        
        Parameters
        ----------
        user : User
            Usuário que está criando/atualizando o artigo.
        sps_pkg : SPSPkg
            Pacote SPS que contém o artigo.
        issue : Issue, optional
            Fascículo do artigo. Se não informado, será obtido do XML.
        journal : Journal, optional
            Periódico do artigo. Se não informado, será obtido do XML.
        position : int, optional
            Posição do artigo no fascículo.
            
        Returns
        -------
        Article
            Artigo criado ou atualizado.
            
        Raises
        ------
        ValueError
            Se sps_pkg não é informado ou está inválido.
        """
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
        """
        Extrai informações de paginação do XML do pacote SPS.
        
        Popula os campos de primeira página, última página e elocation_id
        a partir dos dados extraídos do XML do pacote.
        """
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.fpage = xml_with_pre.fpage
        self.fpage_seq = xml_with_pre.fpage_seq
        self.lpage = xml_with_pre.lpage
        self.elocation_id = xml_with_pre.elocation_id

    def add_issue(self, user):
        """
        Obtém e associa o fascículo do artigo baseado no XML.
        
        Extrai as informações de volume, suplemento e número do XML
        do pacote SPS e localiza ou cria o fascículo correspondente.
        
        Parameters
        ----------
        user : User
            Usuário que está realizando a operação.
        """
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.issue = Issue.get(
            journal=self.journal,
            volume=xml_with_pre.volume,
            supplement=xml_with_pre.suppl,
            number=xml_with_pre.number,
        )

    def add_journal(self, user):
        """
        Obtém e associa o periódico do artigo baseado no XML.
        
        Extrai as informações ISSN do XML do pacote SPS e localiza
        ou cria o periódico correspondente.
        
        Parameters
        ----------
        user : User
            Usuário que está realizando a operação.
        """
        xml_with_pre = self.sps_pkg.xml_with_pre
        self.journal = Journal.get(
            official_journal=OfficialJournal.get(
                issn_electronic=xml_with_pre.journal_issn_electronic,
                issn_print=xml_with_pre.journal_issn_print,
            ),
        )

    def add_article_titles(self, user):
        """
        Extrai e armazena títulos do artigo em múltiplos idiomas.
        
        Processa os títulos do XML do pacote SPS, cria ou obtém as
        linguagens correspondentes, e associa os títulos ao artigo.
        Remove títulos anteriores antes de adicionar novos.
        
        Parameters
        ----------
        user : User
            Usuário que está realizando a operação.
        """
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
        """
        Extrai e associa seções do artigo a partir do XML.
        
        Processa as seções do XML do pacote SPS, cria ou obtém as
        linguagens correspondentes, associa as seções ao artigo e
        atualiza a tabela de conteúdo (TOC) do fascículo.
        Remove seções anteriores antes de adicionar novas.
        
        Parameters
        ----------
        user : User
            Usuário que está realizando a operação.
        """
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

    @property
    def collections(self):
        from collection.models import Collection

        return Collection.objects.filter(
            articleproc__sps_pkg=self.sps_pkg,
        ).distinct()

    @property
    def collections_acron(self):
        from collection.models import Collection

        return list(
            Collection.objects.filter(
                articleproc__sps_pkg=self.sps_pkg,
            )
            .values_list("acron", flat=True)
            .distinct()
            .order_by("acron")
        )

    @property
    def collections_name(self):
        from collection.models import Collection

        return list(
            Collection.objects.filter(
                articleproc__sps_pkg=self.sps_pkg,
            )
            .values_list("name", flat=True)
            .distinct()
            .order_by("name")
        )

    @property
    def display_collections(self):
        if not self.sps_pkg_id:
            return ""
        return ", ".join(self.collections_acron)

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

    def get_html_urls(self, website_url, classic=True, new=True, only_first=None):
        pid_v2 = self.pid_v2
        pid_v3 = self.pid_v3
        journal_acron = None
        if new:
            journal_acron = self.journal.journal_acron

        for item in self.htmls:
            lang = item.get("lang")
            if not lang:
                continue
            if classic:
                url = format_classic_url(website_url, pid_v2=pid_v2, format="html", lang_code=lang)
                yield {"url": url, "format": "html", "lang": lang, "website": "classic"}
            if new:
                url = format_url(website_url, pid_v3, journal_acron, format="html", lang_code=lang)
                yield {"url": url, "format": "html", "lang": lang, "website": "new"}
            if only_first:
                return

    def get_pdf_urls(self, website_url, classic=True, new=True, only_first=None):
        pid_v2 = self.pid_v2
        pid_v3 = self.pid_v3
        
        for item in self.pdfs:
            lang = item.get("lang")
            if not lang:
                continue
            if classic:
                url = format_classic_url(website_url, pid_v2=pid_v2, format="pdf", lang_code=lang)
                yield {"url": url, "format": "pdf", "lang": lang, "website": "classic"}
            if new:
                journal_acron = self.journal.journal_acron
                url = format_url(website_url, pid_v3, journal_acron, format="pdf", lang_code=lang)
                yield {"url": url, "format": "pdf", "lang": lang, "website": "new"}
            if only_first:
                return

    def get_webpage_items(self, website_url):
        yield from self.get_html_urls(website_url)
        yield from self.get_pdf_urls(website_url)

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
        """
        Remove artigos migrados com pid_v2 inválido.
        
        Localiza e deleta artigos migrados cujos últimos 5 dígitos do
        pid_v2 não correspondem à ordem (v121) do documento em
        MigratedArticle.document.order. Usa ArticleProc.migrated_data
        para acessar os dados de migração. Aplicável apenas a artigos
        migrados.
        
        Parameters
        ----------
        issue : Issue, optional
            Se fornecido, filtra apenas artigos deste fascículo.
            
        Returns
        -------
        list[str]
            Lista de eventos/mensagens descrevendo as ações realizadas.
        """
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

        # Bulk-fetch Article records to avoid N+1 queries via ArticleProc.article
        sps_pkg_id_list = [
            ap.sps_pkg_id for ap in article_procs if ap.sps_pkg_id
        ]
        articles_by_sps_pkg = {}
        if sps_pkg_id_list:
            for article in Article.objects.select_related("sps_pkg", "pp_xml").filter(
                sps_pkg_id__in=sps_pkg_id_list
            ).only("id", "pid_v2", "sps_pkg_id", "pp_xml_id"):
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
                    # houve um erro o sistema de migração que criou pid_v2 aleatoriamente no lugar de usar o pid_v2 original
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
                deleted_sps, _ = SPSPkg.objects.filter(id__in=sps_pkg_ids).delete()
                events.append(f"SPSPkg deletados: {deleted_sps}")

            if pp_xml_ids:
                deleted_pp, _ = PidProviderXML.objects.filter(id__in=pp_xml_ids).delete()
                events.append(f"PidProviderXML deletados: {deleted_pp}")

        return events

    @classmethod
    def exclude_inconvenient_articles(cls, issue, user, timeout=None):
        """
        Orquestra a limpeza de artigos problemáticos em um fascículo.
        
        Executa as seguintes operações em fases:
        1. Remove artigos migrados com pid_v2 inválido
        2. Remove duplicatas por pid_v2 e sps_pkg_name
        
        Parameters
        ----------
        issue : Issue
            Fascículo a ser processado.
        user : User
            Usuário que autoriza a limpeza.
        timeout : int, optional
            Timeout em segundos para verificações HTTP.
            
        Returns
        -------
        dict
            Dicionário contendo:
            - events: lista de eventos/mensagens de ação
            - numbers: contagem de itens repetidos por campo
            - exceptions: lista de exceções capturadas durante o processo
        """
        results = {"events": [], "numbers": {}, "exceptions": []}

        # Fase 1: pid_v2 inválidos (artigos migrados com erro)
        try:
            events = cls.exclude_articles_with_invalid_pid_v2(issue)
            results["events"].extend(events)
        except Exception as e:
            results["exceptions"].append({
                "step": "exclude_articles_with_invalid_pid_v2",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

        # Fase 2: duplicatas
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
                    results["exceptions"].append({
                        "step": f"repeated_by_{field_name}",
                        "value": value,
                        "traceback": traceback.format_exc(),
                    })

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
            sps_pkg__xml_with_pre__pkg_name = self.sps_pkg.xml_with_pre.sps_pkg_name
            pp_xml__xml_with_pre__pkg_name = self.pp_xml.xml_with_pre.sps_pkg_name
            return sps_pkg__pkg_name == pp_xml__xml_with_pre__pkg_name == sps_pkg__xml_with_pre__pkg_name
        except Exception as e:
            if self.pp_xml is not None:
                if self.pp_xml.proc_status != PPXML_STATUS_INVALID:
                    self.pp_xml.proc_status = PPXML_STATUS_INVALID
                    self.pp_xml.save()
            return False

    @classmethod
    def fix_sps_pkg_names(cls, issue):
        # Seleciona artigos do fascículo de suplemento cujo
        # sps_pkg_name não contém "-s", indicando nome incorreto
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
                except Exception as e:
                    data["sps_pkg__pkg_name_exception"] = traceback.format_exc()

                try:
                    data["pp_xml__pkg_name"] = item.pp_xml.pkg_name
                    data["pp_xml__pkg_name_fixed"] = item.pp_xml.fix_pkg_name(data.get("sps_pkg__pkg_name"))
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
        Remove artigos duplicados para um dado campo.
        
        Remove artigos duplicados para um campo específico (pid_v2 ou
        sps_pkg_name). Mantém exatamente 1 artigo, descartando os demais
        mesmo que vários estejam publicados no site público.

        Processo em 4 fases:
        1. Ranking SQL com status persistido (annote para ranking)
        2. Check HTTP apenas dos 2 melhores candidatos
        3. Decisão final com status atualizado
        4. Deleção em bulk dos demais
        
        Parameters
        ----------
        user : User
            Usuário responsável pela ação.
        field_name : str
            Nome do campo a verificar (ex: "pid_v2" ou "sps_pkg__sps_pkg_name").
        field_value : str
            Valor do campo que identifica duplicatas.
        timeout : int, optional
            Timeout em segundos para verificações HTTP.
            
        Returns
        -------
        list[str]
            Lista de eventos/mensagens descrevendo o processo.
        """
        repeated_items = cls.objects.filter(**{field_name: field_value})
        total_initial = repeated_items.count()

        if total_initial <= 1:
            return [
                f"{field_name}='{field_value}': {total_initial} artigo(s), "
                "nenhuma ação necessária"
            ]

        events = [f"{field_name}='{field_value}': {total_initial} artigos encontrados"]

        # ── Fase 1: pré-ranking via SQL ──
        candidate_ids = list(
            repeated_items
            .annotate(
                has_valid_public_webpage=models.Exists(
                    ArticleWebPage.objects.filter(
                        article_id=models.OuterRef("pk"),
                        status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
                        website__purpose=PUBLIC,
                    )
                ),
                has_pp_xml=models.Case(
                    models.When(pp_xml__isnull=False, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
            )
            .order_by("-has_valid_public_webpage", "-has_pp_xml", "-updated")
            .values_list("id", flat=True)[:2]
        )

        # ── Fase 2: check HTTP só dos finalistas ──
        # Confirma o estado real antes de decidir.
        # Se o 1º candidato cai, o 2º assume.
        for article in cls.objects.filter(id__in=candidate_ids):
            for check_fn, params in article.get_check_url_and_params(
                user, timeout=timeout, force_update=True
            ):
                try:
                    check_fn(**params)
                except Exception as e:
                    logging.exception(e)

        events.append(
            f"Disponibilidade verificada para {len(candidate_ids)} finalista(s)"
        )

        # ── Fase 3: decisão com status atualizado ──
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
            items_to_delete
            .exclude(sps_pkg__isnull=True)
            .values_list("sps_pkg_id", flat=True)
        )
        pp_xml_ids = set(
            items_to_delete
            .exclude(pp_xml__isnull=True)
            .values_list("pp_xml_id", flat=True)
        )
        article_ids = list(items_to_delete.values_list("id", flat=True))

        total_to_delete = len(article_ids)
        events.append(f"Artigos a deletar: {total_to_delete}")

        if not total_to_delete:
            return events

        with transaction.atomic():
            deleted_articles, _ = cls.objects.filter(id__in=article_ids).delete()
            events.append(f"Articles deletados: {deleted_articles}")

            if sps_pkg_ids:
                deleted_sps, _ = SPSPkg.objects.filter(id__in=sps_pkg_ids).delete()
                events.append(f"SPSPkg deletados: {deleted_sps}")

            if pp_xml_ids:
                deleted_pp, _ = PidProviderXML.objects.filter(
                    id__in=pp_xml_ids
                ).delete()
                events.append(f"PidProviderXML deletados: {deleted_pp}")

        return events
        
    @classmethod
    def choose_item_to_keep(cls, queryset):
        """
        Escolhe qual artigo duplicado deve ser mantido.
        
        Dado um queryset de artigos duplicados, retorna o ID do único
        que deve ser mantido. Entre múltiplos artigos publicados no
        site público, escolhe o mais confiável. Os demais serão deletados.

        Critérios de seleção (em ordem de prioridade):
        1. Webpage com conteúdo válido no site público
        2. Registro no PidProvider (pp_xml existe)
        3. Mais recentemente atualizado
        
        Parameters
        ----------
        queryset : QuerySet
            QuerySet de artigos duplicados.
            
        Returns
        -------
        int or None
            ID do artigo que deve ser mantido, ou None se nenhum encontrado.
        """
        return (
            queryset
            .annotate(
                has_valid_public_webpage=models.Exists(
                    ArticleWebPage.objects.filter(
                        article_id=models.OuterRef("pk"),
                        status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
                        website__purpose=PUBLIC,
                    )
                ),
                has_pp_xml=models.Case(
                    models.When(pp_xml__isnull=False, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
            )
            .order_by(
                "-has_valid_public_webpage",
                "-has_pp_xml",
                "-updated",
            )
            .values_list("id", flat=True)
            .first()
        )

    def create_or_update_urls(
        self,
        user,
        website,
    ):
        qs = self.article_webpages.filter(
            article=self,
            website=website,
        )
        webpage_items = list(self.get_webpage_items(website.url))
        ids = set()
        for item in webpage_items:
            lang = item.get("lang")
            ids.add(
                ArticleWebPage.create_or_update(
                    user,
                    self,
                    website,
                    item.get("url"),
                    item.get("format"),
                    lang,
                ).id
            )
        qs.exclude(id__in=ids).delete()

    def get_main_article_url(self, website_url):
        return format_url(website_url, self.pid_v3, self.journal.journal_acron)

    def get_webpage_id_and_lang_items(self, collection=None, website=None):
        params = {}
        if collection:
            params["website__collection"] = collection
        if website:
            params["website"] = website
        ids = set()
        for webpage in self.article_webpages.filter(**params):
            ids.add((webpage.id, webpage.lang.code2))
        return ids

    def get_check_url_and_params(
        self,
        user,
        force_update=False,
        article_metadata=None,
        timeout=None,
        website=None,
    ):
        article_metadata = article_metadata or self.get_metadata_by_lang()
        excluded_items = {}
        if not force_update:
            excluded_items["status"] = choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
        
        webpages = self.article_webpages.exclude(**excluded_items)
        if website:
            webpages = webpages.filter(website=website)
        for webpage in webpages:
            yield webpage.check_availability, {
                "user": user,
                "timeout": timeout,
                "article_metadata": article_metadata.get(webpage.lang.code2),
                "force_update": force_update,
            }

    def get_metadata_by_lang(self):
        langs = self.article_langs
        metadata = {}
        for lang in langs:
            metadata[lang] = self.get_metadata_items(lang)
        return metadata
        
    def get_metadata_items(self, lang=None):
        """
        Retorna lista de tuplas (label, valor) com os metadados do artigo.
        
        Extrai os metadados do artigo (títulos, DOIs, seções, PIDs,
        paginação, autores) pronta para ser usada com check_metadata ou
        compute_rate.
 
        Parameters
        ----------
        lang : str, optional
            Código de idioma (ex: "pt", "en", "es").
            Quando informado, filtra títulos, DOIs e seções pelo idioma.
            Campos sem idioma (PIDs, paginação, autores) são sempre incluídos.
 
        Returns
        -------
        list[tuple]
            Lista de tuplas (label, valor) com os metadados.
            Exemplo:
            [
                ("title.1", "Acesso aberto..."),
                ("doi.1", "10.1590/..."),
                ("author.1", "Maria da Silva"),
                ("section.1", "Artigos Originais"),
                ("pid_v2", "S0001-37652021000100101"),
                ...
            ]
        """
        items = []
        lang_filter = {"language__code2": lang} if lang else {}
 
        # Títulos
        for i, title in enumerate(self.title_with_lang.filter(**lang_filter), 1):
            if title.text:
                items.append((f"title.{i}", title.text))
 
        # DOIs
        doi_lang_filter = {"lang__code2": lang} if lang else {}
        for i, doi in enumerate(self.doi_with_lang.filter(**doi_lang_filter), 1):
            if doi.doi:
                items.append((f"doi.{i}", doi.doi))
 
        # Seções
        for i, section in enumerate(self.sections.filter(**lang_filter), 1):
            if section.text:
                items.append((f"section.{i}", section.text))
 
        # PIDs
        if self.pid_v2:
            items.append(("pid_v2", self.pid_v2))
        if self.pid_v3:
            items.append(("pid_v3", self.pid_v3))
 
        # Paginação / elocation
        if self.elocation_id:
            items.append(("elocation_id", self.elocation_id))
        if self.fpage:
            items.append(("fpage", self.fpage))
        if self.lpage:
            items.append(("lpage", self.lpage))
 
        # Autores (do XML via sps_pkg — independente de idioma)
        try:
            xmltree = self.sps_pkg.xml_with_pre.xmltree
            contribs = xmltree.findall(
                ".//front/article-meta/contrib-group/contrib[@contrib-type='author']"
            )
            for i, contrib in enumerate(contribs, 1):
                # usa somente surname pois não é possível garantir a ordem de given-names e surname
                surname = contrib.findtext("name/surname") or ""
                if surname:
                    items.append((f"author.{i}", surname))
        except (AttributeError, TypeError):
            pass
 
        return items
    
    def check_webpages_availability(self, user, website, timeout=None, force_update=None):
        article_metadata_by_lang = self.get_metadata_by_lang()
        for webpage in self.article_webpages.filter(website=website):
            article_metadata = article_metadata_by_lang.get(webpage.lang.code2)
            webpage.check_availability(
                user, timeout, article_metadata, force_update)

    def all_webpages_available(self, collection=None, website=None):
        # collection (PUBLIC e QA)
        # website (PUBLIC ou QA)
        params = {}
        if website:
            params["website"] = website
        if collection:
            params["website__collection"] = collection
        if self.article_webpages.exists():
            return not self.article_webpages.exclude(
                status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
            ).filter(**params).exists()
        return False

    def any_webpage_available(self, website=None, website_id=None, collection=None):
        # está presente em algum website
        params = {}
        if website_id:
            params["website_id"] = website_id
        if website:
            params["website"] = website
        if collection:
            params["website__collection"] = collection
        return self.article_webpages.filter(
            status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
            **params,
        ).exists()

    def public_webpages(self, collection=None):
        # está presente em no PUBLIC website
        params = {}
        if collection:
            params["website__collection"] = collection
        params["website__purpose"] = PUBLIC
        return self.article_webpages.filter(
            status=choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT,
            **params
        ).exists()

    def get_availability_stats(self, collection=None, website=None):
        params = {}
        if website:
            params["website"] = website
        if collection:
            params["website__collection"] = collection
        qs = self.article_webpages.filter(**params)
        total = len(qs)
        if not total:
            return {}
        stats = (
            qs.values("status")
            .annotate(count=Count("id"))
        )
        return {
            item["status"]: round(item["count"] * 100 / total, 1)
            for item in stats
        }


class ArticleDOIWithLang(Orderable, DOIWithLang):
    """
    Modelo que associa DOIs com idiomas específicos a um artigo.
    
    Permite que um artigo tenha múltiplos DOIs, cada um vinculado a um
    idioma específico.
    
    Attributes
    ----------
    article : ParentalKey
        Referência ao artigo relacionado.
    doi : CharField
        Identificador de objeto digital (herança de DOIWithLang).
    lang : ForeignKey
        Idioma associado ao DOI (herança de DOIWithLang).
    
    Methods
    -------
    get(article=None, doi=None, lang=None)
        Obtém DOI(s) com base nos parâmetros.
    create(user, article=None, doi=None, lang=None)
        Cria um novo DOI para o artigo.
    get_or_create(user, article=None, doi=None, lang=None)
        Obtém ou cria um DOI para o artigo.
    """
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
    """
    Modelo que armazena títulos de artigos em diferentes idiomas.
    
    Associa um título HTML a um artigo e seu idioma correspondente.
    
    Attributes
    ----------
    parent : ParentalKey
        Referência ao artigo relacionado.
    text : TextField
        Texto do título em HTML (herança de HTMLTextModel).
    language : ForeignKey
        Idioma do título (herança de HTMLTextModel).
    """
    parent = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="title_with_lang"
    )

    panels = [
        FieldPanel("text", read_only=True),
        FieldPanel("language", read_only=True),
    ]


class RelatedItem(CommonControlField):
    """
    Modelo que representa relacionamentos entre artigos.
    
    Define relacionamentos entre um artigo de origem e um artigo de
    destino, com um tipo de relacionamento específico (ex: erratum,
    correction, etc).
    
    Attributes
    ----------
    item_type : CharField
        Tipo do relacionamento (ex: erratum, correction, original-article).
    source_article : ForeignKey
        Artigo de origem do relacionamento.
    target_article : ForeignKey
        Artigo de destino do relacionamento.
    
    Methods
    -------
    __str__()
        Retorna representação textual do relacionamento.
    """
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
    """
    Modelo que representa solicitações de alteração em artigos.
    
    Permite solicitar alterações/atualizações em um artigo, como
    errata ou correções, com comentários detalhados sobre a mudança.
    
    Attributes
    ----------
    change_type : CharField
        Tipo de alteração solicitada (ex: erratum, update, correction).
    comment : TextField
        Comentários descrevendo a alteração solicitada.
    article : ForeignKey
        Artigo que será alterado.
    
    Methods
    -------
    __str__()
        Retorna representação textual da solicitação.
    """

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


class ArticleWebPage(CommonControlField):
    """
    Modelo que representa páginas web de artigos publicados.
    
    Armazena URLs de apresentação de artigos em websites específicos,
    com informações de formato, idioma e status de disponibilidade.
    
    Attributes
    ----------
    article : ParentalKey
        Referência ao artigo.
    website : ForeignKey
        Configuração do website onde o artigo é publicado.
    fmt : CharField
        Formato do conteúdo (ex: "html", "pdf").
    lang : ForeignKey
        Idioma da página.
    url : CharField
        URL da página.
    status : CharField
        Status da página (disponível, indisponível, conteúdo inválido, etc).
    detail : JSONField
        Detalhes do último check de disponibilidade.
    
    Methods
    -------
    get(article, website, url, fmt, lang=None)
        Obtém uma página específica.
    create(user, article, website, url, fmt, lang)
        Cria uma nova página.
    create_or_update(user, article, website, url, fmt, lang)
        Cria ou atualiza uma página.
    check_availability(user, timeout, article_metadata=None, force_update=None)
        Verifica disponibilidade da URL e valida conteúdo.
    """
    article = ParentalKey(
        Article,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="article_webpages",
    )
    website = models.ForeignKey(
        'collection.WebSiteConfiguration',
        verbose_name=_("Website"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text=_("Website configuration where this article webpage is published"),
    )
    fmt = models.CharField(_("Format"), max_length=4, null=True, blank=True)
    lang = models.ForeignKey(
        Language,
        verbose_name=_("Language"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    url = models.CharField(_("URL"), max_length=265, null=True, blank=True)
    status = models.CharField(
        _("Status"), max_length=16, null=True, blank=True, choices=choices.ARTICLE_WEBPAGE_STATUS,
        default=choices.ARTICLE_WEBPAGE_STATUS_NOT_CHECKED,
    )
    detail = models.JSONField(_("Detail"), null=True, blank=True)
    
    panels = [
        FieldPanel("article", read_only=True),
        FieldPanel("website", read_only=True),
        FieldPanel("url", read_only=True),
        FieldPanel("fmt", read_only=True),
        FieldPanel("lang", read_only=True),
        FieldPanel("status", read_only=True),
        FieldPanel("detail", read_only=True),
    ]

    class Meta:
        unique_together = ("article", "website", "url", "fmt", "lang")
        indexes = [
            models.Index(fields=["url"]),
            models.Index(fields=["article", "website", "fmt", "lang"]),
        ]

    @classmethod
    def get(cls, article, website, url, fmt, lang=None):
        return cls.objects.get(
            article=article,
            website=website,
            url=url,
            fmt=fmt,
            lang=lang,
        )

    @classmethod
    def create(
        cls,
        user,
        article,
        website,
        url,
        fmt,
        lang,
    ):
        try:
            obj = cls(
                article=article,
                website=website,
                url=url,
                fmt=fmt,
                lang=lang,
                creator=user,
            )
            obj.save()
            return obj
        except IntegrityError:
            return cls.get(article, website, url, fmt, lang)

    @classmethod
    def create_or_update(
        cls,
        user,
        article,
        website,
        url,
        fmt,
        lang,
    ):
        try:
            if lang:
                lang = Language.objects.filter(code2=lang).first()
            return cls.get(article, website, url, fmt, lang)
        except cls.DoesNotExist:
            return cls.create(
                user=user,
                article=article,
                website=website,
                url=url,
                fmt=fmt,
                lang=lang,
            )

    def check_availability(self, user, timeout, article_metadata=None, force_update=None):
        """
        Verifica disponibilidade e validade do conteúdo da página.
        
        Acessa a URL da página, verifica se está disponível e valida
        se o conteúdo contém os metadados esperados do artigo. Atualiza
        o status da página com o resultado da verificação.
        
        Parameters
        ----------
        user : User
            Usuário que está realizando a verificação.
        timeout : int
            Timeout em segundos para a requisição HTTP.
        article_metadata : list[tuple], optional
            Metadados do artigo para validação de conteúdo.
            Se não fornecido, será extraído do artigo.
        force_update : bool, optional
            Se True, ignora status anterior e refaz a verificação.
            
        Returns
        -------
        dict
            Dicionário com detalhes da verificação (URL, status, erros, taxa de acurácia).
        """
        detail = {
            "url": self.url,
            "format": self.fmt,
            "lang": self.lang.code2 if self.lang else None,
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
                article_metadata = self.article.get_metadata_items(self.lang.code2 if self.lang else None)
            if not article_metadata:
                raise ValueError("No article metadata available for content check")
            
            response = check_content(article_metadata, content)
            if response.get("error"):
                raise ValueError(response["error"])
            rate = response.get("rate", 0)
            if rate > 0.8:
                self.status = choices.ARTICLE_WEBPAGE_STATUS_VALID_CONTENT
            else:
                self.status = choices.ARTICLE_WEBPAGE_STATUS_CONTENT_MISMATCH
            detail.update(response)
        except Exception as e:
            detail = {"error": str(e)}
            self.status = choices.ARTICLE_WEBPAGE_STATUS_UNAVAILABLE
        self.detail = detail
        self.updated_by = user
        self.save()
        detail["status"] = self.status
        return detail