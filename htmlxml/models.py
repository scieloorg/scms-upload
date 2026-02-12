import logging
import os
import sys
import traceback
from io import BytesIO
from functools import cached_property
from zipfile import ZipFile, ZIP_DEFLATED

from django.core.files.base import ContentFile
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from lxml import etree
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from packtools.sps.pid_provider.xml_sps_lib import (
    XMLWithPre,
    split_processing_instruction_doctype_declaration_and_xml,
)
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from core.utils.file_utils import delete_files
from migration.models import MigratedArticle
from package.models import BasicXMLFile
from scielo_classic_website.classic_ws import Document
from scielo_classic_website.models.document import GenerateBodyAndBackFromHTMLError
# from tracker.models import EventLogger
from tracker import choices as tracker_choices
from tracker.models import UnexpectedEvent, format_traceback

from . import choices, exceptions


def escape_xpath_string(text):
    """Escapa texto para uso seguro em XPath."""
    if not text:
        return ""
    if "'" in text and '"' in text:
        parts = text.split("'")
        return "concat('" + "', \"'\", '".join(parts) + "')"
    return f'"{text}"' if "'" in text else f"'{text}'"


def get_xpath_for_a_href_stats(a, journal_acron):
    """Gera XPaths possíveis para elementos XML resultantes da conversão de <a href>."""
    href = (a.get("href") or "").strip()
    if not href:
        return []
    
    text = "".join(a.xpath(".//text()"))
    
    # Links internos
    if href.startswith("#"):
        rid = href[1:]
        xpaths = [f".//xref[@rid='{rid}']"]
        if text:
            xpaths.append(f".//xref[text()='{text}']")
        return xpaths
    
    # Emails
    if "@" in href or "@" in text:
        email = href[7:] if href.startswith("mailto:") else href
        xpaths = [f".//email[text()={escape_xpath_string(email)}]"]
        if text and text != email:
            xpaths.append(f".//email[text()='{text}']")
        return xpaths
    
    # Imagens e recursos gráficos
    _, ext = os.path.splitext(href.lower())
    is_image = (ext in {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.tif', '.tiff'} or
                "img/revistas" in href or f"/{journal_acron}/" in href)
    
    if is_image:
        xpaths = [f".//graphic[@xlink:href='{href}']"]
        if text:
            xpaths.append(f".//xref[text()='{text}']")
        return xpaths
    
    # Links externos (URLs completas)
    xpaths = []
    if text:
        xpaths.append(f".//ext-link[text()='{text}']")
    xpaths.append(f".//ext-link[@xlink:href='{href}']")
    return xpaths


def get_xpath_for_src_stats(element_tag, src, journal_acron):
    """
    Determina XPaths apropriados para análise de elementos src.

    Args:
        element_tag: Tag do elemento HTML (img, etc)
        src: Valor do atributo src

    Returns:
        list: Lista de expressões XPath para buscar no XML
    """
    if ":" in src:
        return [f".//ext-link[text()='{src}']"]

    # if "img/revistas" in src or src.startswith("/pdf"):
    if f"/{journal_acron}/" in src:
        if element_tag == "img":
            return [
                f".//graphic[@xlink:href='{src}']",
                f".//inline-graphic[@xlink:href='{src}']",
            ]

    return [f".//*[@xlink:href='{src}']"]


def get_xpath_for_name_stats(name):
    """
    Determina XPaths apropriados para análise de elementos name.

    Args:
        name: Valor do atributo name

    Returns:
        list: Lista de expressões XPath para buscar no XML
    """
    if not name:
        return []

    if name.isalpha():
        return [f".//*[@id='{name}']"]
    if name.startswith("t") and name[-1].isdigit():
        return [f".//table-wrap[@id='{name}']"]
    if name.startswith("f") and name[-1].isdigit():
        return [f".//fig[@id='{name}']"]
    if name[-1].isdigit():
        return [f".//*[@id='{name}']"]
    return []


def get_xml_nodes_to_string(xml, xpaths):
    if not xpaths:
        return ""

    xpath = "|".join(xpaths)
    items = []
    for item in xml.xpath(xpath, namespaces={"xlink": "http://www.w3.org/1999/xlink"}):
        items.append(xml_node_to_string(item))
    return items


# Extrair de Html2xmlAnalysis
def xml_node_to_string(node):
    """Era Html2xmlAnalysis.tostring()"""
    return etree.tostring(node, encoding="utf-8", pretty_print=True).decode("utf-8")


def format_html_numbers_section(statistics_list):
    """Era Html2xmlAnalysis._format_html_numbers()"""
    yield "<div><div>"
    for item in statistics_list:
        label = item.get('label', '')
        value = item.get('value', '')
        yield (
            f'<div class="row"><div class="col-sm">{label}</div>'
            f'<div class="col-sm">{value}</div></div>'
        )
    yield "</div></div>"


def format_html_match_section(html_vs_xml):
    """Era Html2xmlAnalysis._format_html_match()"""
    yield "<div>"
    for item in html_vs_xml:
        yield from format_code(item)
    yield "</div>"


def format_code_(data):
    data = data.replace("&", "&amp;")
    data = data.replace("<", "&lt;")
    data = data.replace(">", "&gt;")
    return data


def format_code(cols):
    yield "<hr/>"
    yield "<h4>html</h4>"
    yield "<div><pre><code>" + format_code_(cols["html"]) + "</code></pre></div>"
    yield "<h4>xml</h4>"
    for item in cols["xml"]:
        yield f"<div><pre><code>{format_code_(item)}</code></pre></div>"


def body_and_back_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    try:
        version = instance.version
        migrated_article = instance.bb_parent.migrated_article
    except AttributeError:
        version = None
        migrated_article = instance.migrated_article
    pkg_path = (
        "classic_website/"
        f"{migrated_article.collection.acron}/html2xml/"
        f"{migrated_article.document.journal.acronym}/"
        f"{migrated_article.document.issue.issue_label}/"
        f"{migrated_article.pkg_name}/bb"
    )
    
    if version:
        return f"{pkg_path}/{version}/{filename}"
    return f"{pkg_path}/{filename}"


class BodyAndBackFile(BasicXMLFile, Orderable):
    bb_parent = ParentalKey("HTMLXML", related_name="bb_file")

    file = models.FileField(
        upload_to=body_and_back_directory_path, null=True, blank=True, max_length=300
    )
    version = models.IntegerField()

    panels = [
        FieldPanel("file"),
        FieldPanel("version"),
    ]

    class Meta:

        indexes = [
            models.Index(fields=["version"]),
        ]

    def autocomplete_label(self):
        return f"{self.bb_parent} {self.version}"

    def __str__(self):
        return f"{self.bb_parent} {self.version}"

    @classmethod
    def get(cls, htmlxml, version):
        if not htmlxml:
            raise ValueError("BodyAndBackFile.requires htmlxml")
        if not version:
            raise ValueError("BodyAndBackFile.requires version")
        return cls.objects.get(bb_parent=htmlxml, version=version)

    @classmethod
    def create_or_update(cls, user, bb_parent, version, file_content, pkg_name):
        if not file_content:
            raise exceptions.CreateOrUpdateBodyAndBackFileError(
                _(
                    "Unable to create_or_update_body and back file with empty content {} {}"
                ).format(bb_parent, version)
            )
        try:
            obj = cls.get(bb_parent, version)
            obj.updated_by = user
        except cls.MultipleObjectsReturned:
            cls.objects.filter(bb_parent=bb_parent, version=version).delete()
            obj = cls()
            obj.creator = user
            obj.bb_parent = bb_parent
            obj.version = version
            obj.save()
        except cls.DoesNotExist:
            obj = cls()
            obj.creator = user
            obj.bb_parent = bb_parent
            obj.version = version
            obj.save()
        try:
            # cria / atualiza arquivo
            obj.save_file(pkg_name + ".xml", file_content, True)
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.CreateOrUpdateBodyAndBackFileError(
                _("Unable to create_or_update_body and back file {} {} {} {}").format(
                    bb_parent, version, type(e), e
                )
            )


def generated_xml_report_directory_path(instance, filename):
    migrated_article = instance.migrated_article
    return (
        f"classic_website/{migrated_article.collection.acron}/html2xml/"
        f"{migrated_article.document.journal.acronym}/"
        f"{migrated_article.document.issue.issue_label}/"
        f"{migrated_article.pkg_name}/"
        f"report/{filename}"
    )


class Html2xmlAnalysis(models.Model):
    comment = models.TextField(null=True, blank=True)

    empty_body = models.BooleanField(null=True, blank=True)

    attention_demands = models.IntegerField(null=True, blank=True, default=0)

    html_img_total = models.IntegerField(null=True, blank=True, default=0)
    html_table_total = models.IntegerField(null=True, blank=True, default=0)

    xml_supplmat_total = models.IntegerField(null=True, blank=True, default=0)
    xml_media_total = models.IntegerField(null=True, blank=True, default=0)
    xml_fig_total = models.IntegerField(null=True, blank=True, default=0)
    xml_table_wrap_total = models.IntegerField(null=True, blank=True, default=0)
    xml_eq_total = models.IntegerField(null=True, blank=True, default=0)
    xml_graphic_total = models.IntegerField(null=True, blank=True, default=0)
    xml_inline_graphic_total = models.IntegerField(null=True, blank=True, default=0)

    xml_ref_elem_citation_total = models.IntegerField(null=True, blank=True, default=0)
    xml_ref_mixed_citation_total = models.IntegerField(null=True, blank=True, default=0)
    xml_text_lang_total = models.IntegerField(null=True, blank=True, default=0)
    article_type = models.CharField(null=True, blank=True, max_length=32)

    @cached_property
    def analysis_data(self):
        """
        Retorna dados de análise como lista de dicionários com labels traduzíveis
        
        Returns:
            dict com duas chaves:
                - 'statistics': lista de dicionários com label/value para estatísticas
                - 'html_vs_xml': dados de comparação HTML vs XML
        """
        return [
            {
                'label': _('Body vazio'),
                'value': _('Sim') if self.empty_body else _('Não')
            },
            {
                'label': _('Pontos de atenção'),
                'value': self.attention_demands or 0
            },
            {
                'label': _('Tipo de artigo'),
                'value': self.article_type or _('Não identificado')
            },
            {
                'label': _('Tabelas no HTML'),
                'value': self.html_table_total or 0
            },
            {
                'label': _('Imagens no HTML'),
                'value': self.html_img_total or 0
            },
            {
                'label': _('Material suplementar no XML'),
                'value': self.xml_supplmat_total or 0
            },
            {
                'label': _('Elementos de mídia no XML'),
                'value': self.xml_media_total or 0
            },
            {
                'label': _('Figuras no XML'),
                'value': self.xml_fig_total or 0
            },
            {
                'label': _('Tabelas no XML'),
                'value': self.xml_table_wrap_total or 0
            },
            {
                'label': _('Equações no XML'),
                'value': self.xml_eq_total or 0
            },
            {
                'label': _('Gráficos no XML'),
                'value': self.xml_graphic_total or 0
            },
            {
                'label': _('Gráficos inline no XML'),
                'value': self.xml_inline_graphic_total or 0
            },
            {
                'label': _('Citações estruturadas (element-citation)'),
                'value': self.xml_ref_elem_citation_total or 0
            },
            {
                'label': _('Citações mistas (mixed-citation)'),
                'value': self.xml_ref_mixed_citation_total or 0
            },
            {
                'label': _('Idiomas do texto no XML'),
                'value': self.xml_text_lang_total or 0
            }
        ]

    panels = [
        FieldPanel("comment"),
        FieldPanel("report"),
        FieldPanel("attention_demands"),
        FieldPanel("article_type"),
        FieldPanel("html_table_total"),
        FieldPanel("html_img_total"),
        FieldPanel("empty_body"),
        FieldPanel("xml_text_lang_total"),
        FieldPanel("xml_table_wrap_total"),
        FieldPanel("xml_supplmat_total"),
        FieldPanel("xml_media_total"),
        FieldPanel("xml_fig_total"),
        FieldPanel("xml_eq_total"),
        FieldPanel("xml_graphic_total"),
        FieldPanel("xml_inline_graphic_total"),
        FieldPanel("xml_ref_elem_citation_total"),
        FieldPanel("xml_ref_mixed_citation_total"),
    ]

    class Meta:

        indexes = [
            models.Index(fields=["attention_demands"]),
        ]

    def html_report_content(self, title):
        """
        Gera o conteúdo HTML do relatório
        
        Args:
            title: Título do relatório
            
        Returns:
            str: HTML completo do relatório
        """
        stats = format_html_numbers_section(self.analysis_data or [])
        changes = format_html_match_section(self._html_vs_xml or [])      
        return (
            """<html>"""
            """<head>
            <title>Report</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous">
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js" integrity="sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL" crossorigin="anonymous"></script>
            </head>"""
            """<body>
            <div class="container">
                <h1>Report {}</h1>
                <div class="card mt-3">
                    <div class="card-header">
                        <h3>{}</h3>
                    </div>
                    <div class="card-body">
                        {}
                    </div>
                </div>
                <div class="card mt-3">
                    <div class="card-header">
                        <h3>{}</h3>
                    </div>
                    <div class="card-body">
                        {}
                    </div>
                </div>
            </div>
            </body></html>""".format(
                title,
                _('Estatísticas de Conversão HTML para XML'),
                "".join(stats),
                _('Trocas de HTML para XML'),
                "".join(changes),
            )
        )

    def get_a_href_stats(self, html, xml, journal_acron):
        for a in html.xpath(".//a[@href]"):
            xpaths = get_xpath_for_a_href_stats(a, journal_acron)
            yield {
                "html": xml_node_to_string(a),
                "xml": get_xml_nodes_to_string(xml, xpaths),
            }

    def get_src_stats(self, html, xml, journal_acron):
        """
        Analisa elementos src usando função xpath dedicada.
        """
        self.html_img_total = len(html.xpath(".//img[@src]"))

        for element in html.xpath(".//*[@src]"):
            src = element.get("src", "")

            # Usar função dedicada para determinar XPaths
            xpaths = get_xpath_for_src_stats(element.tag, src, journal_acron)

            yield {
                "html": xml_node_to_string(element),
                "xml": get_xml_nodes_to_string(xml, xpaths),
            }

    def get_a_name_stats(self, html, xml):
        """
        Analisa elementos name usando função xpath dedicada.
        """
        for node in html.xpath(".//a[@name]"):
            name = node.get("name", "")

            # Usar função dedicada para determinar XPaths
            xpaths = get_xpath_for_name_stats(name)

            yield {
                "html": xml_node_to_string(node),
                "xml": get_xml_nodes_to_string(xml, xpaths),
            }

    def get_html_stats(self, html):
        self.html_table_total = len(html.xpath(".//table"))
        self.html_img_total = len(html.xpath(".//img[@src]"))

    def get_xml_stats(self, xml):
        body = xml.find(".//body")
        self.empty_body = body is None or not body.xpath(".//text()")
        self.xml_supplmat_total = len(xml.xpath(".//supplementary-material")) + len(
            xml.xpath(".//inline-supplementary-material")
        )
        self.xml_media_total = len(xml.xpath(".//media"))
        self.xml_fig_total = len(xml.xpath(".//fig[@id]")) + len(
            xml.xpath(".//fig-group[@id]")
        )
        self.xml_table_wrap_total = len(xml.xpath(".//table-wrap[@id]"))
        self.xml_eq_total = len(xml.xpath(".//disp-formula[@id]"))
        self.xml_graphic_total = len(xml.xpath(".//graphic"))
        self.xml_inline_graphic_total = len(xml.xpath(".//inline-graphic"))
        self.xml_ref_elem_citation_total = len(xml.xpath(".//element-citation"))
        self.xml_ref_mixed_citation_total = len(xml.xpath(".//mixed-citation"))
        self.xml_text_lang_total = (
            len(xml.xpath(".//sub-article[@article-type='translation']")) + 1
        )

    def html_vs_xml(self, html, xml, journal_acron):
        yield from self.get_a_href_stats(html, xml, journal_acron)
        yield from self.get_src_stats(html, xml, journal_acron)
        yield from self.get_a_name_stats(html, xml)

    def identify_attention_demands(self):
        self.attention_demands = 0
        if self.html_table_total != self.xml_table_wrap_total:
            self.attention_demands += 1

        if (
            self.html_img_total
            != self.xml_graphic_total + self.xml_inline_graphic_total
        ):
            self.attention_demands += 1

        if self.empty_body:
            self.attention_demands += 1

        if self.xml_ref_elem_citation_total != self.xml_ref_mixed_citation_total:
            self.attention_demands += 1

        if (
            self.xml_ref_elem_citation_total == 0
            or self.xml_ref_mixed_citation_total == 0
        ):
            self.attention_demands += 1

        if self.xml_text_lang_total > 1:
            self.attention_demands += 1

        self.attention_demands += self.xml_inline_graphic_total
        self.attention_demands += self.xml_graphic_total
        self.attention_demands += self.xml_eq_total
        self.attention_demands += self.xml_table_wrap_total
        self.attention_demands += self.xml_fig_total
        self.attention_demands += self.xml_media_total
        self.attention_demands += self.xml_supplmat_total
        self.attention_demands += self.html_table_total

    def evaluate_xml(self, html, xml, journal_acron):
        if html is None or xml is None:
            raise ValueError("Html2xmlAnalysis.evaluate_xml requires html and xml")
        self.article_type = xml.find(".").get("article-type")
        self.get_html_stats(html)
        self.get_xml_stats(xml)
        self._html_vs_xml = list(self.html_vs_xml(html, xml, journal_acron))
        self.identify_attention_demands()
        self.save()


class HTMLXML(CommonControlField, ClusterableModel, Html2xmlAnalysis, BasicXMLFile):
    migrated_article = models.ForeignKey(
        MigratedArticle, on_delete=models.SET_NULL, null=True, blank=True
    )
    html2xml_status = models.CharField(
        _("Status"),
        max_length=16,
        choices=tracker_choices.PROGRESS_STATUS,
        default=tracker_choices.PROGRESS_STATUS_TODO,
    )
    quality = models.CharField(
        _("Quality"),
        max_length=16,
        choices=choices.HTML2XML_QA,
        default=choices.HTML2XML_QA_NOT_EVALUATED,
    )
    report = models.FileField(
        upload_to=generated_xml_report_directory_path, null=True, blank=True, max_length=300
    )
    n_paragraphs = models.IntegerField(default=0)
    n_references = models.IntegerField(default=0)
    record_types = models.CharField(max_length=16, blank=True, null=True)
    html_translation_langs = models.CharField(max_length=64, blank=True, null=True)
    pdf_langs = models.CharField(max_length=64, blank=True, null=True)
    bb_init_file = models.FileField(
        upload_to=body_and_back_directory_path,
        null=True,
        blank=True,
        verbose_name=_("Initial HTML file"),
        help_text=_("Initial HTML structured in body, back, ref-list"),
        max_length=300,
    )
    conversion_steps_zip_file = models.FileField(
        upload_to=body_and_back_directory_path, 
        null=True, 
        blank=True,
        verbose_name=_("Body and Back ZIP file"),
        help_text=_("ZIP file containing all body and back XML versions"),
        max_length=300,
    )
    panel_status = [
        FieldPanel("html2xml_status"),
        FieldPanel("quality"),
        FieldPanel("n_paragraphs"),
        FieldPanel("n_references"),
        FieldPanel("html_translation_langs"),
        FieldPanel("pdf_langs"),
        FieldPanel("record_types"),
    ]
    panel_bb_files = [
        FieldPanel("bb_init_file"),
        FieldPanel("conversion_steps_zip_file"),
        InlinePanel("bb_file", label=_("Body and Back XML files")),
    ]
    panel_output = [
        FieldPanel("file"),
        FieldPanel("report"),
    ]
    edit_handler = TabbedInterface(
        [
            ObjectList(panel_status, heading=_("Status")),
            ObjectList(panel_output, heading=_("Generated XML and Report")),
            ObjectList(panel_bb_files, heading=_("Body and Back XML Files")),
        ]
    )

    def __str__(self):
        return f"{self.migrated_article}"

    def autocomplete_label(self):
        return self.migrated_article

    class Meta:
        ordering = ["-updated"]

        indexes = [
            models.Index(fields=["html2xml_status"]),
            models.Index(fields=["quality"]),
            models.Index(fields=["migrated_article"]),
        ]

    @property
    def data(self):
        return {
            "html2xml_status": self.html2xml_status,
            "n_paragraphs": self.n_paragraphs,
            "n_references": self.n_references,
            "record_types": self.record_types,
            "html_translation_langs": self.html_translation_langs,
            "pdf_langs": self.pdf_langs,
        }

    @property
    def directory_path(self):
        return f"classic_website/{self.migrated_article.collection.acron}/html2xml/{self.migrated_article.path}"

    def get_meaningful_package_name(self):
        """Gera um nome de pacote significativo incluindo journal acron, issue folder e pkg_name"""
        if not self.migrated_article:
            return "unknown_package"
        
        try:
            journal_acron = self.migrated_article.document.journal.acronym
            issue_label = self.migrated_article.document.issue.issue_label
            pkg_name = self.migrated_article.pkg_name
            return f"{self.migrated_article.collection.acron}_{journal_acron}_{issue_label}_{pkg_name}"
        except AttributeError:
            # Fallback para caso algum atributo não exista
            return self.migrated_article.pkg_name or "unknown_package"

    @property
    def created_updated(self):
        return self.updated or self.created

    # @property
    # def has_images(self):
    #     """Retorna True se o HTML contém imagens"""
    #     return (self.html_img_total or 0) > 0
    
    # @property
    # def has_tables(self):
    #     """Retorna True se o HTML contém tabelas"""
    #     return (self.html_table_total or 0) > 0
    
    # @property
    # def has_attention_demands(self):
    #     """Retorna True se há pontos de atenção"""
    #     return (self.attention_demands or 0) > 0

    @classmethod
    def get(
        cls,
        migrated_article=None,
    ):
        if migrated_article:
            try:
                return cls.objects.get(migrated_article=migrated_article)
            except cls.MultipleObjectsReturned:
                # If multiple objects exist, return the most recently updated one
                # This handles legacy duplicate data gracefully
                return cls.objects.filter(
                    migrated_article=migrated_article
                ).order_by("-updated").first()
        raise ValueError("HTMLXML.get requires migrated_article")

    @classmethod
    def create_or_update(
        cls,
        user,
        migrated_article,
        html2xml_status=None,
        quality=None,
        n_references=None,
        record_types=None,
    ):
        try:
            obj = cls.get(migrated_article)
            obj.updated_by = user
            
            # Clean up duplicates if they exist by keeping only the most recent
            duplicates = cls.objects.filter(
                migrated_article=migrated_article
            ).exclude(pk=obj.pk)
            if duplicates.exists():
                logging.warning(
                    f"Found {duplicates.count()} duplicate HTMLXML records for "
                    f"migrated_article {migrated_article}. Deleting duplicates."
                )
                duplicates.delete()
        except cls.DoesNotExist:
            obj = cls()
            obj.migrated_article = migrated_article
            obj.creator = user
            obj.html2xml_status = tracker_choices.PROGRESS_STATUS_TODO
            obj.quality = choices.HTML2XML_QA_NOT_EVALUATED

        try:
            obj.html2xml_status = html2xml_status or obj.html2xml_status
            obj.quality = quality or obj.quality
            obj.n_paragraphs = migrated_article.n_paragraphs or 0
            obj.n_references = n_references or obj.n_references or 0
            obj.record_types = record_types or obj.record_types
            obj.save()
            return obj
        except Exception as e:
            raise exceptions.HTMLXMLCreateOrUpdateError(
                _(
                    "Unable to create or update the record of the conversion of HTML to XML for {} {} {}"
                ).format(migrated_article, type(e), e)
            )

    def html_to_xml(
        self,
        user,
        article_proc,
    ):
        detail = {}
        document = None
        xml_content = None
        report_content = None
        op = None
        
        try:
            op = article_proc.start(user, "html_to_xml")
            translations = article_proc.translations or {}
            translation_langs = list(translations.keys())

            self.html2xml_status = tracker_choices.PROGRESS_STATUS_DOING
            self.html_translation_langs = "-".join(
                sorted(translation_langs)
            )
            self.pdf_langs = "-".join(
                sorted(
                    [
                        item.lang or article_proc.main_lang
                        for item in article_proc.renditions
                    ]
                )
            )
            self.save()

            detail["exceptions"] = []
            detail["translation languages"] = translation_langs
            detail["xml_name"] = article_proc.pkg_name + ".xml"

            # Inicializar document
            document = Document(article_proc.migrated_data.data)
            self._generate_body_and_back(document, translations, detail)
            xml_content = self._generate_xml(document, detail["xml_name"], detail)

            report_content = None
            if xml_content:
                detail["xml_created"] = True
                if detail.get("xml_exceptions"):
                    detail["status"] = tracker_choices.PROGRESS_STATUS_PENDING
                else:
                    detail["status"] = tracker_choices.PROGRESS_STATUS_DONE
                self.html2xml_status = detail["status"]
                self.save()
                report_content = self.generate_report(str(article_proc), article_proc.issue_proc.journal_proc.acron, detail)
    
            self._save_zip(
                article_proc.pkg_name,
                document.xml_body_and_back,
                xml_content or "",
                report_content,
                detail.get("exceptions"),
                detail,
            )
            exception = None
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            exception = traceback.format_exc()
            self.html2xml_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()

        if op:
            op.finish(
                user,
                completed=detail.get("xml_created") or False,
                exception=exception,
                message_type=None,
                message=None,
                exc_traceback=None,
                detail=detail,
            )
        return detail

    def _generate_body_and_back(self, document, translations, detail):
        # Inicializar document
        document._translated_html_by_lang = translations
        document.generate_body_and_back_from_html(translations)

        if document.exceptions:    
            detail["body_and_back_exceptions"] = document.exceptions
            detail["exceptions"].extend(document.exceptions)

        index = 1
        if not document.xml_body_and_back:
            index = 0
            document.xml_body_and_back = ["<article><body></body><back></back></article>"]
        self.save_bb_init_file(document, index)

    def _generate_xml(self, document, xml_filename, detail):
        xml_content = document.generate_full_xml(None).decode("utf-8")
        if not xml_content:
            detail["xml_exceptions"] = document.exceptions
            detail["exceptions"].extend(document.exceptions)
            return None
        self.save_file(xml_filename, xml_content, True)
        return xml_content   

    @property
    def initial_html_tree(self):
        try:
            path = self.bb_init_file.path
        except (ValueError, AttributeError):
            try:
                path = list(self.bb_file.all())[1].file.path
            except (AttributeError, IndexError, TypeError):
                return None
        for xml_with_pre in XMLWithPre.create(path=path):
            return xml_with_pre.xmltree
        
    def save_bb_init_file(self, document, index):
        try:
            self.bb_init_file.delete(save=False)
        except (FileNotFoundError, AttributeError, TypeError):
            pass
        try:
            # o bb_file[0] contém o HTML original dentro de CDATA então não cria uma árvore de elementos
            # o bb_file[1] contém HTML original estruturado em body, back, ref-list
            self.bb_init_file.save(
                "initial_html.xml",
                ContentFile(document.xml_body_and_back[index]),
                save=True,
            )
        except Exception as e:
            logging.exception(e)

    def generate_report(self, report_title, journal_acron, detail):
        try:
            for xml_with_pre in XMLWithPre.create(path=self.file.path):
                xml = xml_with_pre.xmltree
                break
            html = self.initial_html_tree
            self.evaluate_xml(html, xml, journal_acron)
            report_content = self.html_report_content(title=report_title)
            self.save_report(report_content)
            if self.attention_demands == 0:
                self.quality = choices.HTML2XML_QA_AUTO_APPROVED
            else:
                self.quality = choices.HTML2XML_QA_NOT_EVALUATED
            self.save()
            return report_content
        except Exception as e:
            error = traceback.format_exc()
            detail["report_exceptions"] = (
                _("Error generating HTML to XML report: {} {}").format(e, error)
            )
            raise

    def _save_zip(self, pkg_name, xml_body_and_back_items, xml_content, report_content, exceptions, detail):
        errors = []
        try:
            # Criar o ZIP em memória
            zip_buffer = BytesIO()
            
            with ZipFile(zip_buffer, 'w', ZIP_DEFLATED) as zip_file:
                # Adicionar cada versão do XML ao ZIP
                if xml_body_and_back_items:
                    for i, xml_body_and_back in enumerate(xml_body_and_back_items, start=1):
                        try:
                            zip_file.writestr(f"step_{i:03d}.xml", xml_body_and_back)
                        except Exception as e:
                            errors.append(f"Failed to write step_{i:03d}.xml to zip: {e}")
                
                # Adicionar XML final se existir
                if xml_content:
                    try:
                        zip_file.writestr(f"{pkg_name}.xml", xml_content)
                    except Exception as e:
                        errors.append(f"Failed to write {pkg_name}.xml to zip: {e}")
                
                # Adicionar relatório se existir
                if report_content:
                    try:
                        zip_file.writestr(f"report.html", report_content)
                    except Exception as e:
                        errors.append(f"Failed to write report.html to zip: {e}")
                
                # Adicionar exceções se existirem
                if exceptions:
                    try:
                        exception_text = "\n".join([
                            f"[{i+1}] {exc}" for i, exc in enumerate(exceptions)
                        ])
                        zip_file.writestr(f"exceptions.txt", exception_text)
                    except Exception as e:
                        errors.append(f"Failed to write exceptions to zip file: {e}")

            # Salvar o arquivo ZIP no campo FileField
            zip_content = zip_buffer.getvalue()
            zip_filename = f"{pkg_name}.zip"
            
            # Deletar ZIP anterior se existir
            try:
                self.conversion_steps_zip_file.delete(save=False)
            except (FileNotFoundError, AttributeError, TypeError):
                pass
            
            # Salvar novo ZIP
            self.conversion_steps_zip_file.save(zip_filename, ContentFile(zip_content), save=True)

            # Limpar arquivos temporários de body and back
            try:
                for bb_file_ in self.bb_file.all():
                    try:
                        bb_file_.delete()
                    except Exception as e:
                        logging.exception(f"Error deleting body and back file {bb_file_.version}: {e}")
            except Exception as e:
                logging.exception(f"Error accessing body and back files for deletion: {e}")
            detail["zip_exceptions"] = errors
            return True

        except Exception as e:
            errors.append(f"Error creating or saving ZIP file: {e}")
            detail["zip_exceptions"] = errors
            return False

    def save_report(self, report_content):
        try:
            delete_files(self.report.path)
        except Exception as e:
            pass
        self.report.save(
            "report.html",
            ContentFile(report_content),
            save=True,
        )