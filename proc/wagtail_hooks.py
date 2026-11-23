from django.urls import include, path
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.snippets.models import register_snippet
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from wagtail.permission_policies.base import BasePermissionPolicy
from django.urls import reverse
from wagtail.snippets.views.snippets import (
    CreateView as SnippetCreateView,
    EditView as SnippetEditView,
    IndexView as SnippetIndexView,
    InspectView as SnippetInspectView,
    SnippetViewSet,
    SnippetViewSetGroup,
)
import django_filters

from config.menu import get_menu_order
from core.views import CommonControlFieldViewSet
from django.db.models import Count
from django.utils.html import format_html

from htmlxml.models import HTMLXML, Html2xmlIssue, Html2xmlProblem
from package.models import SPSPkg

from .models import ArticleProc, IssueProc, JournalProc, ProblemReport, ProcReport


class HTMLXMLFilterSet(django_filters.FilterSet):
    has_images = django_filters.BooleanFilter(
        field_name='html_img_total',
        lookup_expr='gt',
        label=_('Has Images'),
        method='filter_has_images'
    )
    
    has_tables = django_filters.BooleanFilter(
        field_name='html_table_total', 
        lookup_expr='gt',
        label=_('Has Tables'),
        method='filter_has_tables'
    )
    
    has_attention_demands = django_filters.BooleanFilter(
        field_name='attention_demands',
        lookup_expr='gt', 
        label=_('Has Attention Demands'),
        method='filter_has_attention_demands'
    )
    
    review_severity = django_filters.ChoiceFilter(
        label=_("Review: severity"),
        choices=[
            ("critical", _("critical")),
            ("major", _("major")),
            ("minor", _("minor")),
            ("info", _("information")),
            ("ok", _("ok")),
        ],
    )
    review_problem = django_filters.NumberFilter(
        field_name="review_issues__problem",
        label=_("Review: problem (id)"),
    )

    def filter_has_images(self, queryset, name, value):
        if value is True:
            return queryset.filter(html_img_total__gt=0)
        elif value is False:
            return queryset.filter(html_img_total=0)
        return queryset
    
    def filter_has_tables(self, queryset, name, value):
        if value is True:
            return queryset.filter(html_table_total__gt=0)
        elif value is False:
            return queryset.filter(html_table_total=0)
        return queryset
    
    def filter_has_attention_demands(self, queryset, name, value):
        if value is True:
            return queryset.filter(attention_demands__gt=0)
        elif value is False:
            return queryset.filter(attention_demands=0)
        return queryset

    class Meta:
        model = HTMLXML
        fields = [
            'html2xml_status',
            'quality', 
            'pdf_langs',
            'html_translation_langs',
            'article_type',
            'empty_body',
            'has_images',
            'has_tables',
            'has_attention_demands',
            'review_severity',
            'review_problem',
        ]


class JournalProcViewSet(CommonControlFieldViewSet):
    model = JournalProc
    menu_label = _("Journal Processing")
    menu_icon = "folder"
    menu_order = 200
    add_to_settings_menu = False
    
    list_display = [
        "journal",
        "pid",
        "availability_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
    ]
    list_filter = [
        "collection",
        "availability_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
    ]
    search_fields = [
        "acron",
        "pid",
        "journal__title",
        "journal__official_journal__issn_print",
        "journal__official_journal__issn_electronic",
    ]


class IssueProcViewSet(CommonControlFieldViewSet):
    model = IssueProc
    inspect_view_enabled = True
    menu_label = _("Issue Processing")
    
    menu_icon = "folder"
    menu_order = 300
    add_to_settings_menu = False

    list_display = [
        "issue",
        "__str__",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "updated",
    ]
    list_filter = [
        "collection",
        "migration_status",
        "docs_status",
        "files_status",
        "qa_ws_status",
        "public_ws_status",
        "issue__publication_year",
    ]
    search_fields = [
        "journal_proc__acron",
        "journal_proc__journal__title",
        "issue_folder",
        "issue__publication_year",
        "issue__volume",
        "issue__number",
        "issue__supplement",
        "pid",
    ]


class HTMLXMLViewSet(CommonControlFieldViewSet):
    model = HTMLXML
    menu_label = _("XML from HTML")
    menu_icon = "doc-full"
    menu_order = 300
    add_to_settings_menu = False
    inspect_view_enabled = True
    filterset_class = HTMLXMLFilterSet

    list_per_page = 10

    list_display = [
        "migrated_article",
        "html2xml_status",
        "review_severity",
        "review_text_lost",
        "html_translation_langs",
        "pdf_langs",
        "n_paragraphs",
        "n_references",
        "created_updated",
    ]
    search_fields = [
        "migrated_article__pid",
        "html2xml_status",
        "article_type",
    ]


class SPSPkgFilterSet(django_filters.FilterSet):
    has_ppx = django_filters.BooleanFilter(
        field_name='ppx_id',
        lookup_expr='isnull',
        exclude=True,
        label=_('Has pid provider xml')
    )

    class Meta:
        model = SPSPkg
        fields = [
            'origin',
            'registered_in_core',
            'valid_texts',
            'valid_components',
            'is_public',
            'has_ppx',
        ]


class SPSPkgViewSet(CommonControlFieldViewSet):
    model = SPSPkg
    menu_label = _("SPS Package")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10
    filterset_class = SPSPkgFilterSet  # <--- Filtro customizado associado

    list_display = [
        "sps_pkg_name",
        "pid_v3",
        "registered_in_core",
        "valid_texts",
        "valid_components",
        "is_public",
        "xml_uri",
        "created",
        "updated",
    ]

    # Obs: list_filter foi removido para evitar conflitos com o filterset_class
    search_fields = [
        "pid_v3",
        "sps_pkg_name",
    ]


class ArticleProcFilterSet(django_filters.FilterSet):
    has_sps_pkg = django_filters.BooleanFilter(
        field_name='sps_pkg_id',
        lookup_expr='isnull',
        exclude=True,
        label=_('Has SPS Package')
    )
    has_sps_pkg_article = django_filters.BooleanFilter(
        field_name='sps_pkg__article',
        lookup_expr='isnull',
        exclude=True,
        label=_('Has SPS Package Article')
    )

    class Meta:
        model = ArticleProc
        fields = [
            'collection',
            'pid_status',
            'migration_status',
            'xml_status',
            'sps_pkg_status',
            'qa_ws_status',
            'public_ws_status',
            'has_sps_pkg',
            'has_sps_pkg_article',
        ]


class ArticleProcViewSet(CommonControlFieldViewSet):
    model = ArticleProc
    menu_label = _("Article Processing")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 10
    list_display = [
        "__str__",
        "collection",
        "xml_status",
        "sps_pkg_status",
        "migration_status",
        "qa_ws_status",
        "public_ws_status",
        "pid_status",
        "updated",
    ]
    filterset_class = ArticleProcFilterSet
    search_fields = [
        "sps_pkg__pid_v3",
        "pid",
        "sps_pkg__sps_pkg_name",
        "pkg_name",
        "issue_proc__issue_folder",
        "issue_proc__journal_proc__acron",
    ]


class ProcReportViewSet(CommonControlFieldViewSet):
    model = ProcReport
    menu_label = _("Processing Report")
    inspect_view_enabled = True
    menu_icon = "doc-full"
    menu_order = 200
    add_to_settings_menu = False

    list_per_page = 50

    list_display = [
        "pid",
        "collection",
        "task_name",
        "report_date",
        "updated",
        "created",
    ]
    list_filter = [
        "task_name",
        "collection",
        "item_type",
    ]
    search_fields = [
        "pid",
        "collection__name",
        "task_name",
        "report_date",
    ]


class _CollectionInstanceMixin:
    """Recusa abrir registros de coleções que o usuário não gerencia."""

    instance_action = "view"

    def get_object(self, queryset=None):
        from django.core.exceptions import PermissionDenied

        obj = super().get_object(queryset)
        if not self.permission_policy.user_has_permission_for_instance(
            self.request.user, self.instance_action, obj
        ):
            raise PermissionDenied
        return obj


class SuperuserOnlyPermissionPolicy(BasePermissionPolicy):
    """
    Relatórios de problemas são exclusivos de administradores: só
    superusuários ativos veem o menu, a lista, o detalhe, o download e
    podem gerar ou apagar relatórios.
    """

    def user_has_permission(self, user, action):
        return bool(user.is_authenticated and user.is_active and user.is_superuser)

    def user_has_any_permission(self, user, actions):
        return self.user_has_permission(user, None)

    def users_with_any_permission(self, actions):
        return get_user_model().objects.filter(is_active=True, is_superuser=True)

    def users_with_permission(self, action):
        return self.users_with_any_permission([action])


class ProblemReportPermissionPolicy(SuperuserOnlyPermissionPolicy):
    """
    Administradores: tudo. Gestores de coleção (autonomia para acompanhar a
    conversão sem depender da infraestrutura): veem, baixam e geram os
    relatórios de conversão HTML -> XML das coleções que gerenciam; não
    apagam e não veem os relatórios de problemas de migração/publicação.
    """

    def user_has_permission(self, user, action):
        if super().user_has_permission(user, action):
            return True
        from htmlxml.permissions import can_review

        return action in ("view", "add") and user.is_active and can_review(user)

    def user_has_any_permission(self, user, actions):
        return any(self.user_has_permission(user, action) for action in actions)

    def users_with_any_permission(self, actions):
        from htmlxml.permissions import CollectionManagerPermissionPolicy

        return CollectionManagerPermissionPolicy(self.model).users_with_any_permission(actions)

    def user_has_permission_for_instance(self, user, action, instance):
        if SuperuserOnlyPermissionPolicy.user_has_permission(self, user, action):
            return True
        if not self.user_has_permission(user, action):
            return False
        return instance.pk in set(manager_reports(ProblemReport.objects.filter(pk=instance.pk), user).values_list("pk", flat=True))

    def instances_user_has_permission_for(self, user, action):
        if SuperuserOnlyPermissionPolicy.user_has_permission(self, user, action):
            return self.model.objects.all()
        if not self.user_has_permission(user, action):
            return self.model.objects.none()
        return manager_reports(self.model.objects.all(), user)


def manager_reports(qs, user):
    """
    Relatórios de conversão HTML -> XML cujo escopo está todo nas coleções
    que ``user`` gerencia (relatórios de "todas as coleções" ficam com os
    administradores).
    """
    from htmlxml.permissions import managed_collections

    collections = managed_collections(user)
    if collections is None:
        return qs
    acrons = {c.acron for c in collections}
    qs = qs.filter(report_type=ProblemReport.REPORT_HTML2XML)
    allowed = [
        pk for pk, scope in qs.values_list("pk", "scope")
        if (scope or {}).get("collection_acron_list")
        and set(scope["collection_acron_list"]) <= acrons
    ]
    return qs.filter(pk__in=allowed)


class ProblemReportIndexView(SnippetIndexView):
    """
    O botão "Add" vira "Gerar relatório" (situação atual, sob demanda).
    Relatórios não são editáveis: o título leva à tela de detalhe (só
    leitura, com o download) e a ação "Editar" não aparece.
    """

    add_item_label = _("Generate report")

    def get_add_url(self):
        if self.user_has_permission("view"):
            return reverse("proc:generate_problem_report")

    def get_edit_url(self, instance):
        return None

    def get_queryset(self):
        # quem abre a lista vê como erro o que ficou "gerando" além do limite
        ProblemReport.mark_stale()
        return manager_reports(super().get_queryset(), self.request.user)


class ProblemReportCreateView(SnippetCreateView):
    """Relatórios só são criados pela task; redireciona para o formulário."""

    def dispatch(self, request, *args, **kwargs):
        return redirect("proc:generate_problem_report")


class ProblemReportEditView(SnippetEditView):
    """Não há o que editar: redireciona para a tela de detalhe."""

    def dispatch(self, request, *args, **kwargs):
        return redirect("wagtailsnippets_proc_problemreport:inspect", kwargs["pk"])


class ProblemReportInspectView(_CollectionInstanceMixin, SnippetInspectView):
    """
    Detalhe só leitura, sem o botão "Editar"; gestores só abrem os
    relatórios das suas coleções.
    """

    def get_edit_url(self):
        return None


class ProblemReportViewSet(SnippetViewSet):
    model = ProblemReport

    @property
    def permission_policy(self):
        return ProblemReportPermissionPolicy(self.model)

    index_view_class = ProblemReportIndexView
    add_view_class = ProblemReportCreateView
    edit_view_class = ProblemReportEditView
    inspect_view_class = ProblemReportInspectView
    menu_label = _("Problem reports")
    inspect_view_enabled = True
    menu_icon = "warning"
    menu_order = 200
    add_to_settings_menu = False
    list_per_page = 50
    list_display = [
        "scope_label",
        "report_type",
        "status",
        "coverage",
        "total_items",
        "total_categories",
        "task_name",
        "download",
        "created",
        "expires_at",
    ]
    list_filter = ["report_type", "status", "task_name", "item_types"]
    search_fields = ["scope_label", "task_name"]
    inspect_view_fields = [
        "download",
        "report_type",
        "status",
        "notice",
        "coverage",
        "max_items",
        "language",
        "scope_label",
        "item_types",
        "total_items",
        "total_categories",
        "task_name",
        "created",
        "generated_at",
        "expires_at",
        "error",
    ]


class Html2xmlProblemIndexView(SnippetIndexView):
    """
    Problemas das coleções que o usuário gerencia, os mais graves e mais
    frequentes primeiro. "Adicionar" vira "Solicitar revisão".
    """

    add_item_label = _("Request review")

    def get_add_url(self):
        if self.user_has_permission("view"):
            return reverse("proc:request_html2xml_review")

    def get_base_queryset(self):
        from htmlxml.permissions import filter_by_managed_collections

        qs = filter_by_managed_collections(super().get_base_queryset(), self.request.user)
        return (
            qs.select_related("category", "collection")
            .annotate(
                n_articles=Count("issues", distinct=True),
                n_journals=Count("issues__journal_acron", distinct=True),
            )
            .order_by("category__severity_rank", "-n_articles", "collection__acron")
        )


class Html2xmlProblemEditView(_CollectionInstanceMixin, SnippetEditView):
    instance_action = "change"

    def save_instance(self):
        instance = self.form.save(commit=False)
        instance.updated_by = self.request.user
        instance.save()
        return instance


class Html2xmlProblemInspectView(_CollectionInstanceMixin, SnippetInspectView):
    pass


class Html2xmlIssueInspectView(_CollectionInstanceMixin, SnippetInspectView):
    pass


class Html2xmlProblemViewSet(SnippetViewSet):
    """
    Revisão da conversão HTML -> XML por problema e coleção: classificar
    (bug do conversor, dado, esperado, corrigido) e decidir se bloqueia a
    publicação vale para todos os artigos da coleção com o problema.
    """

    model = Html2xmlProblem
    index_view_class = Html2xmlProblemIndexView
    edit_view_class = Html2xmlProblemEditView
    inspect_view_class = Html2xmlProblemInspectView
    menu_label = _("HTML to XML review")
    menu_icon = "warning"
    menu_order = 310
    add_to_settings_menu = False
    inspect_view_enabled = True
    list_per_page = 50
    list_display = [
        "collection_acron",
        "severity_label",
        "check_label",
        "key",
        "articles",
        "journals",
        "status",
        "blocks_publication",
        "last_seen",
    ]
    list_filter = ["collection", "category__severity", "status", "blocks_publication", "category__check_code"]
    search_fields = ["category__check_code", "category__key", "note"]
    inspect_view_fields = [
        "collection_acron",
        "severity_label",
        "check_label",
        "key",
        "description",
        "nature_label",
        "example",
        "articles",
        "journals",
        "status",
        "blocks_publication",
        "note",
        "first_seen",
        "last_seen",
    ]

    @property
    def permission_policy(self):
        from htmlxml.permissions import CollectionManagerPermissionPolicy

        return CollectionManagerPermissionPolicy(self.model)


def _problem_articles(self):
    total = getattr(self, "n_articles", None)
    if total is None:
        total = self.issues.count()
    url = reverse("wagtailsnippets_htmlxml_html2xmlissue:list") + f"?problem={self.pk}"
    return format_html('<a href="{}">{}</a>', url, total)


def _problem_journals(self):
    total = getattr(self, "n_journals", None)
    if total is None:
        total = self.issues.values("journal_acron").distinct().count()
    return total


_problem_articles.short_description = _("Articles")
_problem_journals.short_description = _("Journals")
Html2xmlProblem.articles = _problem_articles
Html2xmlProblem.journals = _problem_journals


class Html2xmlIssueIndexView(SnippetIndexView):
    """Ocorrências são só para consulta: sem adicionar nem editar."""

    def get_add_url(self):
        return None

    def get_edit_url(self, instance):
        return None

    def get_base_queryset(self):
        from htmlxml.permissions import filter_by_managed_collections

        qs = filter_by_managed_collections(
            super().get_base_queryset(), self.request.user, "problem__collection"
        )
        return qs.select_related("problem__category").order_by(
            "problem__category__severity_rank", "collection_acron", "journal_acron", "issue_folder", "pid"
        )


class Html2xmlIssueViewSet(SnippetViewSet):
    """Ocorrências de cada problema, com o exemplo de cada artigo."""

    model = Html2xmlIssue
    index_view_class = Html2xmlIssueIndexView
    inspect_view_class = Html2xmlIssueInspectView
    inspect_view_enabled = True
    menu_label = _("HTML to XML problems by article")
    menu_icon = "list-ul"
    menu_order = 320
    add_to_settings_menu = False
    list_per_page = 50
    list_display = ["article", "category", "count", "example_html", "conversion_link"]
    list_filter = [
        "problem",
        "problem__category__severity",
        "problem__status",
        "collection_acron",
        "journal_acron",
    ]
    search_fields = ["pid", "journal_acron", "issue_folder", "example"]

    @property
    def permission_policy(self):
        from htmlxml.permissions import IssuePermissionPolicy

        return IssuePermissionPolicy(self.model)


class ProcessViewSetGroup(SnippetViewSetGroup):
    menu_label = _("Processing")
    menu_icon = "folder-open-inverse"
    menu_order = get_menu_order("processing")
    items = (
        JournalProcViewSet,
        IssueProcViewSet,
        ArticleProcViewSet,
        SPSPkgViewSet,
        HTMLXMLViewSet,
        Html2xmlProblemViewSet,
        Html2xmlIssueViewSet,
        ProcReportViewSet,
        ProblemReportViewSet,
    )


# Registra o grupo de snippets
register_snippet(ProcessViewSetGroup)


@hooks.register("register_admin_urls")
def register_disclosure_url():
    return [
        path("proc/", include("proc.urls", namespace="proc")),
    ]