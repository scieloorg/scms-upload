import mimetypes
import logging
import os
from datetime import datetime
from zipfile import ZipFile
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.core.files.base import ContentFile
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from wagtail.admin.edit_handlers import FieldPanel, InlinePanel, MultiFieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel
from packtools.utils import SPPackage
from packtools.sps.models.article_assets import ArticleAssets

from core.models import CommonControlField
from doi.models import DOIWithLang
from issue.models import Issue
from journal.models import Journal, OfficialJournal
from researcher.models import Researcher
from collection.models import Language, Collection
from xmlsps.xml_sps_lib import get_xml_with_pre, XMLWithPre
from . import choices
from .forms import ArticleForm, RelatedItemForm, RequestArticleChangeForm
from .permission_helper import MAKE_ARTICLE_CHANGE, REQUEST_ARTICLE_CHANGE

User = get_user_model()


class CollectionArticleId(ClusterableModel, CommonControlField):
    # Armazena os IDs dos artigos no contexto de cada coleção
    # serve para conseguir recuperar artigos pelo ID do site clássico
    collection = models.ForeignKey(
        Collection, on_delete=models.SET_NULL, null=True, blank=True
    )
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)
    pid_v2 = models.CharField(_("PID v2"), max_length=23, blank=True, null=True)
    aop_pid = models.CharField(_("AOP PID"), max_length=23, blank=True, null=True)

    @classmethod
    def get(cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)

        if collection:
            if pid_v2:
                return cls.objects.get(
                    Q(aop_pid=pid_v2) | Q(pid_v2=pid_v2), collection=collection
                )
            if aop_pid:
                return cls.objects.get(
                    Q(aop_pid=aop_pid) | Q(pid_v2=aop_pid), collection=collection
                )

        if pid_v2:
            return cls.objects.get(Q(aop_pid=pid_v2) | Q(pid_v2=pid_v2))
        if aop_pid:
            return cls.objects.get(Q(aop_pid=aop_pid) | Q(pid_v2=aop_pid))

    @classmethod
    def create_or_update(
        cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None, creator=None
    ):
        try:
            obj = cls.get(
                pid_v3=pid_v3, pid_v2=pid_v2, aop_pid=aop_pid, collection=collection
            )
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator
            obj.created = datetime.utcnow()
        obj.collection = collection or obj.collection
        obj.aop_pid = aop_pid or obj.aop_pid
        obj.pid_v3 = pid_v3 or obj.pid_v3
        obj.pid_v2 = pid_v2 or obj.pid_v2
        obj.save()
        return obj


class Article(ClusterableModel, CommonControlField):
    # PID v3
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)

    # Identificadores no contexto das coleção / compatibilidade com legado
    aids = models.ManyToManyField(CollectionArticleId)

    # Article type
    article_type = models.CharField(
        _("Article type"),
        max_length=32,
        choices=choices.ARTICLE_TYPE,
        blank=False,
        null=False,
    )

    # Article status
    status = models.CharField(
        _("Article status"),
        max_length=32,
        choices=choices.ARTICLE_STATUS,
        blank=True,
        null=True,
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

    @classmethod
    def get(cls, pid_v3=None, pid_v2=None, aop_pid=None, collection=None):
        if pid_v3:
            return cls.objects.get(pid_v3=pid_v3)

        if collection:
            if pid_v2:
                return cls.objects.get(
                    Q(aids__aop_pid=pid_v2) | Q(aids__pid_v2=pid_v2),
                    collection=collection,
                )
            if aop_pid:
                return cls.objects.get(
                    Q(aids__aop_pid=aop_pid) | Q(aids__pid_v2=aop_pid),
                    collection=collection,
                )

    @classmethod
    def get_or_create(
        cls,
        pid_v3,
        pid_v2=None,
        aop_pid=None,
        creator=None,
        issn_electronic=None,
        issn_print=None,
        issnl=None,
        volume=None,
        number=None,
        suppl=None,
        publication_year=None,
        collection=None,
    ):
        try:
            return cls.get(pid_v3, pid_v2, aop_pid, collection)
        except cls.DoesNotExist:
            obj = cls()
            obj.pid_v3 = pid_v3
            obj.created = datetime.utcnow()
            obj.creator = creator

            if collection:
                obj.save()
                obj.aids.add(
                    CollectionArticleId.create_or_update(
                        collection=collection,
                        pid_v3=pid_v3,
                        pid_v2=pid_v2,
                        aop_pid=aop_pid,
                        creator=creator,
                    )
                )

            if issn_electronic or issn_print or issnl:
                official_journal = OfficialJournal.get_or_create(
                    issn_print=issn_print,
                    issn_electronic=issn_electronic,
                    issnl=issnl,
                )
                obj.journal = Journal.get_or_create(official_journal)

                if volume or number or suppl or publication_year:
                    obj.issue = Issue.get_or_create(
                        official_journal=obj.journal.official_journal,
                        volume=volume,
                        supplement=suppl,
                        number=number,
                        publication_year=publication_year,
                        user=creator,
                    )
            obj.save()
            return obj

    def add_type(self, article_type):
        self.article_type = article_type

    def add_related_item(self, target_doi, target_article_type):
        self.save()
        # TODO
        # item = RelatedItem()
        # item.item_type = target_article_type
        # item.source_article = self
        # item.target_article = target_location
        # item.save()
        # self.related_items.add(item)

    def add_pages(self, fpage=None, fpage_seq=None, lpage=None, elocation_id=None):
        self.fpage = fpage
        self.fpage_seq = fpage_seq
        self.lpage = lpage
        self.elocation_id = elocation_id

    def add_issue(
        self,
        official_journal=None,
        publication_year=None,
        volume=None,
        number=None,
        suppl=None,
        user=None,
    ):
        self.issue = Issue.get_or_create(
            official_journal,
            volume,
            suppl,
            number,
            publication_year,
            user,
        )

    def add_journal(
        self,
        official_journal=None,
        publication_year=None,
        volume=None,
        number=None,
        suppl=None,
        user=None,
    ):
        self.issue = Issue.get_or_create(
            official_journal,
            volume,
            suppl,
            number,
            publication_year,
            user,
        )

    autocomplete_search_field = "pid_v3"

    def autocomplete_label(self):
        return self.pid_v3

    panel_article_ids = MultiFieldPanel(
        heading="Article identifiers", classname="collapsible"
    )
    panel_article_ids.children = [
        # FieldPanel("pid_v2"),
        FieldPanel("pid_v3"),
        # FieldPanel("aop_pid"),
        InlinePanel(relation_name="doi_with_lang", label="DOI with Language"),
    ]

    panel_article_details = MultiFieldPanel(
        heading="Article details", classname="collapsible"
    )
    panel_article_details.children = [
        FieldPanel("article_type"),
        FieldPanel("status"),
        InlinePanel(relation_name="title_with_lang", label="Title with Language"),
        InlinePanel(relation_name="author", label="Authors"),
        FieldPanel("elocation_id"),
        FieldPanel("fpage"),
        FieldPanel("lpage"),
    ]

    panels = [
        panel_article_ids,
        panel_article_details,
        FieldPanel("issue", classname="collapsible"),
    ]

    def __str__(self):
        return f"{self.pid_v3}"

    class Meta:
        permissions = (
            (MAKE_ARTICLE_CHANGE, _("Can make article change")),
            (REQUEST_ARTICLE_CHANGE, _("Can request article change")),
        )

    base_form_class = ArticleForm


class ArticleAuthor(Orderable, Researcher):
    author = ParentalKey("Article", on_delete=models.CASCADE, related_name="author")


class ArticleDOIWithLang(Orderable, DOIWithLang):
    doi_with_lang = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="doi_with_lang"
    )


class Title(CommonControlField):
    title = models.TextField(_("Title"))
    lang = models.CharField(_("Language"), max_length=64)

    panels = [
        FieldPanel("title"),
        FieldPanel("lang"),
    ]

    def __str__(self):
        return f"{self.lang.upper()}: {self.title}"

    class Meta:
        abstract = True


class ArticleTitle(Orderable, Title):
    title_with_lang = ParentalKey(
        "Article", on_delete=models.CASCADE, related_name="title_with_lang"
    )


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
    deadline = models.DateField(_("Deadline"), blank=False, null=False)

    change_type = models.CharField(
        _("Change type"),
        max_length=32,
        choices=choices.REQUEST_CHANGE_TYPE,
        blank=False,
        null=False,
    )
    comment = RichTextField(_("Comment"), max_length=512, blank=True, null=True)

    article = models.ForeignKey(
        Article, on_delete=models.CASCADE, blank=True, null=True
    )
    pid_v3 = models.CharField(_("PID v3"), max_length=23, blank=True, null=True)
    demanded_user = models.ForeignKey(
        User, on_delete=models.CASCADE, blank=False, null=False
    )

    panels = [
        FieldPanel("pid_v3", classname="collapsible"),
        FieldPanel("deadline", classname="collapsible"),
        FieldPanel("change_type", classname="collapsible"),
        AutocompletePanel("demanded_user", classname="collapsible"),
        FieldPanel("comment", classname="collapsible"),
    ]

    def __str__(self) -> str:
        return f"{self.article or self.pid_v3} - {self.deadline}"

    base_form_class = RequestArticleChangeForm


def not_optimised_sps_packages_directory_path(instance, filename):
    # pacote padrão recebido de produtores de xml mas com PID v3 validado
    return f"not_optimised_sps_packages/{instance.subdirs}.zip"


def optimised_sps_packages_directory_path(instance, filename):
    # pacote pronto para publicar com href com conteúdo registrado no minio
    return f"optimised_sps_packages/{instance.subdirs}.zip"


class ArticlePackages(CommonControlField):
    """
    Guardas os zips de pacote não-otimizado, otimizado e de seus components
    """

    # ISSN-acron-vol-num-suppl
    sps_pkg_name = models.TextField(_("New name"), null=True, blank=True)
    article = models.ForeignKey(
        Article, on_delete=models.SET_NULL, null=True, blank=True
    )
    optimised_zip_file = models.FileField(
        upload_to=optimised_sps_packages_directory_path, null=True, blank=True
    )
    not_optimised_zip_file = models.FileField(
        upload_to=not_optimised_sps_packages_directory_path, null=True, blank=True
    )
    # componentes do pacote otimizado
    components = models.ManyToManyField("ArticleComponent")

    class Meta:
        indexes = [
            models.Index(fields=["article"]),
        ]

    def __str__(self):
        return f"{self.article}"

    @property
    def subdirs(self):
        issn = (
            self.official_journal.issnl
            or self.official_journal.issn_electronic
            or self.official_journal.issn_print
            or "issn"
        )
        return f"{issn}/{self.article.issue.publication_year}/{self.sps_pkg_name}"

    @property
    def official_journal(self):
        try:
            return self.article.journal.official_journal
        except AttributeError:
            return self.article.issue.official_journal

    @classmethod
    def get(cls, article=None, sps_pkg_name=None):
        logging.info(f"Get ArticlePackages {article} {sps_pkg_name}")
        if article:
            return cls.objects.get(article=article)
        if sps_pkg_name:
            return cls.objects.get(sps_pkg_name=sps_pkg_name)

    @classmethod
    def get_or_create(cls, article=None, sps_pkg_name=None, creator=None):
        try:
            logging.info(f"Get or create ArticlePackages {article}")
            obj = cls.get(article=article, sps_pkg_name=sps_pkg_name)
            obj.updated_by = creator
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = creator

        obj.article = article or obj.article
        obj.sps_pkg_name = sps_pkg_name or obj.sps_pkg_name
        obj.save()
        return obj

    def add_component(
        self,
        sps_filename,
        user,
        category=None,
        lang=None,
        collection_acron=None,
        former_href=None,
        uri=None,
    ):
        component = ArticleComponent.create_or_update(
            sps_filename=sps_filename,
            category=category,
            article=self.article,
            lang=lang,
            uri=uri,
            user=user,
        )
        if collection_acron and former_href:
            component.add_former_location(collection_acron, former_href, user)
        self.components.add(component)
        self.save()

    def add_sps_package_file(self, filename, content, user):
        logging.info(f"ArticlePackages.add_sps_package_file: {filename}")
        self.not_optimised_zip_file.save(filename, ContentFile(content))
        self._create_optimised_sps_package()
        self.updated = datetime.utcnow()
        self.updated_by = user
        self.save()

    def _create_optimised_sps_package(self):
        logging.info(f"ArticlePackages._create_optimised_sps_package {self.article}")
        try:
            with TemporaryDirectory() as targetdir:
                logging.info(f"Cria diretorio destino {targetdir}")

                with TemporaryDirectory() as workdir:
                    logging.info(f"Cria diretorio de trabalho {workdir}")

                    optimised_zip_sps_name = os.path.basename(
                        self.not_optimised_zip_file.path
                    )
                    target = os.path.join(targetdir, optimised_zip_sps_name)

                    package = SPPackage.from_file(
                        self.not_optimised_zip_file.path, workdir
                    )
                    package.optimise(new_package_file_path=target, preserve_files=False)

                with open(target, "rb") as fp:
                    logging.info(f"Save optimised package {optimised_zip_sps_name}")
                    self.optimised_zip_file.save(
                        optimised_zip_sps_name, ContentFile(fp.read())
                    )
        except Exception as e:
            raise exceptions.BuildAndAddOptimisedSPSPackageError(
                _("Unable to build and add optimised sps package {}").format(
                    self.article
                )
            )

    def get_xml_with_pre(self):
        for xml_with_pre in XMLWithPre.create(self.optimised_zip_file.path):
            return xml_with_pre

    def update_xml(self, xml_with_pre):
        with ZipFile(self.optimised_zip_file.path) as zf:
            zf.writestr(self.sps_pkg_name + ".xml", xml_with_pre.tostring())

    def publish_package(self, minio_push_file_content, user):
        logging.info(f"ArticlePackages.publish_package {self.article}")
        try:
            journal = self.article.issue.official_journal
        except AttributeError:
            journal = self.article.official_journal

        mimetypes.init()

        subdir = "/".join(
            [
                journal.issnl or journal.issn_electronic or journal.issn_print,
                self.article.issue.publication_year,
                self.sps_pkg_name,
            ]
        )
        xml_with_pre = None

        local_to_remote = {}
        with ZipFile(self.optimised_zip_file.path) as optimised_fp:
            for item in optimised_fp.namelist():
                with optimised_fp.open(item) as optimised_item_fp:
                    name, ext = os.path.splitext(item)
                    if ext == ".xml":
                        xml_name = item
                        xml_with_pre = get_xml_with_pre(
                            optimised_item_fp.read().decode("utf-8")
                        )
                        continue

                    response = self._register_remote_file(
                        minio_push_file_content,
                        content=optimised_item_fp.read(),
                        ext=ext,
                        subdir=subdir,
                        sps_filename=item,
                        user=user,
                    )
                    try:
                        local_to_remote[item] = response["uri"]
                    except KeyError:
                        pass
                    yield response

            if xml_with_pre:
                if local_to_remote:
                    # Troca href local por href remoto (sps_filename -> uri)
                    xml_article_assets = ArticleAssets(xml_with_pre.xmltree)
                    xml_article_assets.replace_names(local_to_remote)
                response = self._register_remote_file(
                    minio_push_file_content,
                    content=xml_with_pre.tostring(),
                    ext=".xml",
                    subdir=subdir,
                    sps_filename=xml_name,
                    user=user,
                )
                yield response

    def _register_remote_file(
        self, minio_push_file_content, content, ext, subdir, sps_filename, user
    ):
        try:
            # fput_content(self, content, mimetype, object_name)
            logging.info(f"ArticlePackages._register_remote_file {sps_filename}")
            response = minio_push_file_content(
                content=content,
                mimetype=mimetypes.types_map[ext],
                object_name=f"{subdir}/{sps_filename}",
            )
            self.add_component(
                sps_filename=sps_filename,
                user=user,
                uri=response["uri"],
            )
            return response
        except Exception as e:
            logging.info(response)
            logging.exception(e)
            message = _("Unable to register file in minio {} {}").format(
                sps_filename, response
            )
            return dict(
                e=e,
                migrated_item_name="remote_file",
                migrated_item_id=sps_filename,
                message=message,
                action_name="minio_push_file_content",
            )


class FormerLocation(CommonControlField):
    """
    Propósito de guardar o padrão do site clássico de acesso a pdf, material suplementar e imagens
    /img/revistas/...
    /pdf/...
    de modo que o site atual possa redirecionar para o destino atual
    """

    href = models.TextField(_("Classic website location"), null=True, blank=True)
    collection_acron = models.TextField(_("Collection acron"), null=False, blank=False)

    class Meta:
        indexes = [
            models.Index(fields=["collection_acron"]),
            models.Index(fields=["href"]),
        ]

    def __str__(self):
        return f"{self.collection_acron} {self.href}"

    @classmethod
    def get_or_create(cls, collection_acron=None, href=None, user=None):
        logging.info(f"FormerLocation.get_or_create {collection_acron} {href}")
        try:
            return cls.objects.get(collection_acron=collection_acron, href=href)
        except cls.DoesNotExist:
            obj = cls()
            obj.href = href
            obj.collection_acron = collection_acron
            obj.creator = user
            obj.save()
            return obj


class ArticleComponent(CommonControlField):
    """
    Guarda informação de um componente do pacote (imagem, pdf, xml etc)
    category: rendition, asset, supplmat, xml
    sps_filename: basename no padrão SPS
    uri: location no Minio
    """

    article = models.ForeignKey(
        Article, on_delete=models.SET_NULL, null=True, blank=True
    )
    category = models.TextField(_("Category"), null=False, blank=False)
    lang = models.ForeignKey(Language, null=True, blank=True, on_delete=models.SET_NULL)
    sps_filename = models.TextField(_("SPS filename"), null=False, blank=False)
    uri = models.URLField(_("URI"), null=True, blank=True)
    former_locations = models.ManyToManyField(
        FormerLocation, verbose_name=_("Classic website locations")
    )

    class Meta:
        indexes = [
            models.Index(fields=["article"]),
            models.Index(fields=["sps_filename"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return f"{self.sps_filename}"

    @classmethod
    def get(cls, sps_filename=None):
        logging.info(f"ArticleComponent.get {sps_filename}")
        if sps_filename:
            return cls.objects.get(sps_filename=sps_filename)

    @classmethod
    def create_or_update(
        cls, sps_filename, category=None, article=None, lang=None, uri=None, user=None
    ):
        logging.info(
            f"ArticleComponent.create_or_update {sps_filename} {category} {lang} {uri}"
        )
        try:
            obj = cls.get(sps_filename)
            obj.updated_by = user
            obj.updated = datetime.utcnow()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.sps_filename = sps_filename
        try:
            obj.article = article or obj.article
            obj.category = category or obj.category
            obj.uri = uri or obj.uri
            if lang:
                obj.lang = Language.get_or_create(code2=lang, user=user)
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateArticleComponentError(
                _("Unable to ArticleComponent.create_or_update {} {} {} {}").format(
                    article, sps_filename, type(e), e
                )
            )

    def add_former_location(self, collection_acron, href, user):
        logging.info(f"ArticleComponent.add_former_location {collection_acron} {href}")
        self.former_locations.add(
            FormerLocation.get_or_create(
                collection_acron=collection_acron, href=href, user=user
            )
        )
        self.save()
