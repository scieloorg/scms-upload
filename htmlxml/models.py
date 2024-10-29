import logging
import os
import sys

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
from scielo_classic_website.classic_ws import Document
from scielo_classic_website.models.document import GenerateBodyAndBackFromHTMLError
from wagtail.admin.panels import FieldPanel, InlinePanel, ObjectList, TabbedInterface
from wagtail.models import Orderable
from wagtailautocomplete.edit_handlers import AutocompletePanel

from core.forms import CoreAdminModelForm
from core.models import CommonControlField
from migration.models import MigratedArticle
from package.models import BasicXMLFile
# from tracker.models import EventLogger
from tracker import choices as tracker_choices

from . import choices, exceptions


def format_code_(data):
    data = data.replace("&", "&amp;")
    data = data.replace("<", "&lt;")
    data = data.replace(">", "&gt;")
    return data


def format_code(cols):
    # xml = ""
    # for item in cols["xml"]:
    #     xml += f"<li><pre><code>{format_code_(item)}</code></pre></li>"

    # if xml:
    #     xml = f"<ul>{xml}</ul>"

    # cols["html"] = "<pre><code>" + format_code_(cols["html"]) + "</code></pre>"
    # cols["xml"] = xml
    yield "<hr/>"
    yield "<h4>html</h4>"
    yield "<div><pre><code>" + format_code_(cols["html"]) + "</code></pre></div>"
    yield "<h4>xml</h4>"
    for item in cols["xml"]:
        yield f"<div><pre><code>{format_code_(item)}</code></pre></div>"


def _fromstring(xml_content):
    pref, xml = split_processing_instruction_doctype_declaration_and_xml(xml_content)
    return etree.fromstring(xml)


def body_and_back_directory_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    migrated_article = instance.bb_parent.migrated_article
    pkg_path = (
        f"{migrated_article.document.journal.acronym}/"
        f"{migrated_article.document.issue.issue_label}/"
        f"{migrated_article.pkg_name}"
    )
    return f"classic_website/{migrated_article.collection.acron}/html2xml/{pkg_path}/bb/{instance.version}/{filename}"


class BodyAndBackFile(BasicXMLFile, Orderable):
    bb_parent = ParentalKey("HTMLXML", related_name="bb_file")

    file = models.FileField(
        upload_to=body_and_back_directory_path, null=True, blank=True
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
            obj.save_file(pkg_name + ".xml", file_content)
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
    pkg_path = (
        f"{migrated_article.document.journal.acronym}/"
        f"{migrated_article.document.issue.issue_label}/"
        f"{migrated_article.pkg_name}"
    )
    return f"classic_website/{migrated_article.collection.acron}/html2xml/{pkg_path}/report/{filename}"


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

    @property
    def data(self):
        return dict(
            empty_body=self.empty_body,
            attention_demands=self.attention_demands,
            html_img_total=self.html_img_total,
            html_table_total=self.html_table_total,
            xml_supplmat_total=self.xml_supplmat_total,
            xml_media_total=self.xml_media_total,
            xml_fig_total=self.xml_fig_total,
            xml_table_wrap_total=self.xml_table_wrap_total,
            xml_eq_total=self.xml_eq_total,
            xml_graphic_total=self.xml_graphic_total,
            xml_inline_graphic_total=self.xml_inline_graphic_total,
            xml_ref_elem_citation_total=self.xml_ref_elem_citation_total,
            xml_ref_mixed_citation_total=self.xml_ref_mixed_citation_total,
            xml_text_lang_total=self.xml_text_lang_total,
            article_type=self.article_type,
            html_vs_xml=self._html_vs_xml,
        )

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

    @property
    def csv_report_content(self):
        rows = "\n".join(self._format_csv())
        return rows

    def _format_csv(self):
        for k, v in self.data.items():
            if k == "html_vs_xml":
                for item in v:
                    yield f"{item['html']}\t{item['xml']}"
            else:
                yield f"{k}\t{v}"

    @property
    def txt_report_content(self):
        rows = "\n".join(self._format_txt())
        return rows

    def _format_txt(self):
        for k, v in self.data.items():
            if k == "html_vs_xml":
                for item in v:
                    yield f"{item['html']}\t{item['xml']}"
            else:
                yield f"{k}\t{v}"

    def html_report_content(self, title):
        rows = "\n".join(self._format_html_numbers()) + "\n".join(
            self._format_html_match()
        )
        return (
            f"""<html>"""
            """<head>
              <title>Report</title>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous">
              <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js" integrity="sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL" crossorigin="anonymous"></script>            </head>"""
            f"""<body><div class="container"><title>Report {title}</title><h1>Report {title}</h1>{rows}</div></body></html>"""
        )

    def _format_html_numbers(self):
        yield "<div><div>"
        for k, v in self.data.items():
            if k == "html_vs_xml":
                continue
            else:
                yield (
                    f'<div class="row"><div class="col-sm">{k}</div>'
                    f'<div class="col-sm">{v}</div></div>'
                )
        yield "</div></div>"

    def _format_html_match(self):
        yield "<div>"
        for k, v in self.data.items():
            if k == "html_vs_xml":
                for item in v:
                    yield from format_code(item)
        yield "</div>"

    def tostring(self, node):
        return etree.tostring(node, encoding="utf-8", pretty_print=True).decode("utf-8")

    def get_a_href_stats(self, html, xml):
        nodes = html.xpath(".//a[@href]")
        for a in nodes:
            data = {}
            data["html"] = self.tostring(a)

            xml_nodes = []
            href = a.get("href")
            if "img/revistas" in href:
                name, ext = os.path.splitext(href)
                if ".htm" not in ext:
                    for item in xml.xpath(f".//xref[text()='{a.text}']"):
                        xml_nodes.append(self.tostring(item))

                    for item in xml.xpath(
                        f".//graphic[@xlink:href='{href}']",
                        namespaces={"xlink": "http://www.w3.org/1999/xlink"},
                    ):
                        xml_nodes.append(self.tostring(item))
            elif href.startswith("#"):
                for item in xml.xpath(f".//xref[text()='{a.text}']"):
                    xml_nodes.append(self.tostring(item))
            elif "@" in href or "@" in a.text:
                for item in xml.xpath(f".//email[text()='{a.text}']"):
                    xml_nodes.append(self.tostring(item))
            else:
                for item in xml.xpath(f".//ext-link[text()='{a.text}']"):
                    xml_nodes.append(self.tostring(item))
            data["xml"] = xml_nodes
            yield data

    def get_src_stats(self, html, xml):
        self.html_img_total = len(html.xpath(".//img[@src]"))
        nodes = html.xpath(".//*[@src]")
        for a in nodes:
            data = {}
            data["html"] = self.tostring(a)
            xml_nodes = []
            src = a.get("src")
            if "img/revistas" in src or src.startswith("/pdf"):
                if a.tag == "img":
                    for item in xml.xpath(
                        f".//graphic[@xlink:href='{src}'] | .//inline-graphic[@xlink:href='{src}']",
                        namespaces={"xlink": "http://www.w3.org/1999/xlink"},
                    ):
                        xml_nodes.append(self.tostring(item))
                else:
                    for item in xml.xpath(
                        f".//*[@xlink:href='{src}']",
                        namespaces={"xlink": "http://www.w3.org/1999/xlink"},
                    ):
                        xml_nodes.append(self.tostring(item))
            else:
                for item in xml.xpath(f".//*[@xlink:href='{src}']"):
                    xml_nodes.append(self.tostring(item))
            data["xml"] = xml_nodes
            yield data

    def get_a_name_stats(self, html, xml):
        for node in html.xpath(".//a[@name]"):
            data = {}
            data["html"] = self.tostring(node)
            xml_nodes = []
            name = node.get("name")
            if not name:
                continue
            if name.isalpha():
                for item in xml.xpath(f".//*[@id='{name}']"):
                    xml_nodes.append(self.tostring(item))
            elif name[0] == "t" and name[-1].isdigit():
                for item in xml.xpath(f".//table-wrap[@id='{name}']"):
                    xml_nodes.append(self.tostring(item))
            elif name[0] == "f" and name[-1].isdigit():
                for item in xml.xpath(f".//fig[@id='{name}']"):
                    xml_nodes.append(self.tostring(item))
            elif name[-1].isdigit():
                for item in xml.xpath(f".//*[@id='{name}']"):
                    xml_nodes.append(self.tostring(item))
            data["xml"] = xml_nodes
            yield data

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

    def html_vs_xml(self, html, xml):
        yield from self.get_a_href_stats(html, xml)
        yield from self.get_src_stats(html, xml)
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

    def evaluate_xml(self, html, xml):
        if html is None or xml is None:
            raise ValueError("Html2xmlAnalysis.evaluate_xml requires html and xml")
        self.article_type = xml.find(".").get("article-type")
        self.get_html_stats(xml)
        self.get_xml_stats(xml)
        self._html_vs_xml = list(self.html_vs_xml(html, xml))
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
        upload_to=generated_xml_report_directory_path, null=True, blank=True
    )
    n_paragraphs = models.IntegerField(default=0)
    n_references = models.IntegerField(default=0)
    record_types = models.CharField(max_length=16, blank=True, null=True)
    html_translation_langs = models.CharField(max_length=64, blank=True, null=True)
    pdf_langs = models.CharField(max_length=64, blank=True, null=True)

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

    @property
    def created_updated(self):
        return self.updated or self.created

    @classmethod
    def get(
        cls,
        migrated_article=None,
    ):
        if migrated_article:
            return cls.objects.get(migrated_article=migrated_article)
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

    @property
    def bb_files(self):
        return BodyAndBackFile.objects.filter(bb_parent=self)

    def html_to_xml(
        self,
        user,
        article_proc,
        body_and_back_xml,
    ):
        try:
            op = article_proc.start(user, "html_to_xml")
            self.html2xml_status = tracker_choices.PROGRESS_STATUS_DOING
            self.html_translation_langs = "-".join(
                sorted(article_proc.translations.keys())
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

            detail = {}
            document = Document(article_proc.migrated_data.data)
            document._translated_html_by_lang = article_proc.translations

            body_and_back = self._generate_xml_body_and_back(
                user, article_proc, document
            )
            xml_content = self._generate_xml_from_html(user, article_proc, document)

            detail = {"xml_content": bool(xml_content), "body_and_back": bool(body_and_back)}
            completed = bool(xml_content and body_and_back)
            if completed:
                self.html2xml_status = tracker_choices.PROGRESS_STATUS_DONE
            else:
                self.html2xml_status = tracker_choices.PROGRESS_STATUS_PENDING
            self.save()

            op.finish(
                user,
                completed=completed,
                exception=None,
                message_type=None,
                message=None,
                exc_traceback=None,
                detail=detail,
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()

            self.html2xml_status = tracker_choices.PROGRESS_STATUS_BLOCKED
            self.save()
            op.finish(
                user,
                completed=False,
                exception=e,
                message_type=None,
                message=None,
                exc_traceback=exc_traceback,
                detail=detail,
            )
        return xml_content

    @property
    def first_bb_file(self):
        try:
            return self.bb_files.first().text
        except Exception as e:
            return ""

    @property
    def latest_bb_file(self):
        try:
            return self.bb_files.latest("version").text
        except Exception as e:
            return ""

    def generate_report(self, user, article_proc):
        op = article_proc.start(user, "html_to_xml: generate report")
        try:
            detail = {}
            html = _fromstring(self.first_bb_file)

            for xml_with_pre in XMLWithPre.create(path=self.file.path):
                xml = xml_with_pre.xmltree

            self.evaluate_xml(html, xml)
            self.save_report(self.html_report_content(title=article_proc))

            if self.attention_demands == 0:
                self.quality = choices.HTML2XML_QA_AUTO_APPROVED
            else:
                self.quality = choices.HTML2XML_QA_NOT_EVALUATED
            self.save()
            op.finish(
                user,
                completed=True,
                detail={
                    "attention_demands": self.attention_demands,
                    "quality": self.quality,
                },
            )
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            op.finish(
                user,
                completed=False,
                exception=e,
                message_type=None,
                message=None,
                exc_traceback=exc_traceback,
                detail=detail,
            )

    def _generate_xml_body_and_back(self, user, article_proc, document):
        """
        Generate XML body and back from html_translation_langs and p records
        """
        done = False
        operation = article_proc.start(user, "html_to_xml: generate xml body + back")

        languages = document._translated_html_by_lang
        detail = {}
        detail.update(languages)

        try:
            document.generate_body_and_back_from_html(languages)
            done = True
            # guarda cada versão de body/back
        except GenerateBodyAndBackFromHTMLError as e:
            document.xml_body_and_back = ["<article><body/><back/></article>"]
            done = False

        if document.xml_body_and_back:
            for i, xml_body_and_back in enumerate(document.xml_body_and_back, start=1):
                BodyAndBackFile.create_or_update(
                    user=user,
                    bb_parent=self,
                    version=i,
                    file_content=xml_body_and_back,
                    pkg_name=article_proc.pkg_name,
                )
                detail["xml_to_html_steps"] = i
        operation.finish(user, done, detail=detail)
        return done

    def _generate_xml_from_html(self, user, article_proc, document):
        operation = article_proc.start(user, "html_to_xml: merge front + body + back")
        xml_content = None
        detail = {}
        try:
            xml_content = document.generate_full_xml(None).decode("utf-8")
            xml_file = article_proc.pkg_name + ".xml"
            self.save_file(xml_file, xml_content)
            detail["xml"] = xml_file
            operation.finish(user, bool(xml_content), detail=detail)
            return xml_content
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            operation.finish(
                user,
                completed=False,
                exception=e,
                message_type=None,
                message=None,
                exc_traceback=exc_traceback,
                detail=detail,
            )

    def save_report(self, content):
        # content = json.dumps(data)
        # self.report.save("html2xml.json", ContentFile(content))
        self.report.save("html2xml.html", ContentFile(content))
