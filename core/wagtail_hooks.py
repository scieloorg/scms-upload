"""File: core/wagtail_hooks.py."""

from django.templatetags.static import static
from django.utils.html import format_html
from wagtail import hooks
from wagtail.admin.navigation import get_site_for_user
from wagtail.admin.site_summary import SummaryItem

from article.models import Article
from collection.models import Collection
from config.menu import WAGTAIL_MENU_APPS_ORDER, get_menu_order
from journal.models import Journal

# @hooks.register("insert_global_admin_css", order=100)
# def global_admin_css():
#     """Add /static/css/custom.css to the admin."""
#     return format_html('<link rel="stylesheet" href="{}">', static("css/custom.css"))


# @hooks.register("insert_global_admin_js", order=100)
# def global_admin_js():
#     """Add /static/css/custom.js to the admin."""
#     return format_html('<script src="{}"></script>', static("/js/custom.js"))


@hooks.register("construct_homepage_summary_items", order=1)
def remove_all_summary_items(request, items):
    items.clear()


class CollectionSummaryItem(SummaryItem):
    order = 100
    template_name = "wagtailadmin/summary_items/collection_summary_item.html"

    def get_context_data(self, parent_context):
        site_details = get_site_for_user(self.request.user)
        total_collection = Collection.objects.count()
        return {
            "total_collection": total_collection,
            "site_name": site_details["site_name"],
        }

    def is_shown(self):
        return True


class JournalSummaryItem(SummaryItem):
    order = 200
    template_name = "wagtailadmin/summary_items/journal_summary_item.html"

    def get_context_data(self, parent_context):
        site_details = get_site_for_user(self.request.user)
        total_journal = Journal.objects.all().count()
        return {
            "total_journal": total_journal,
            "site_name": site_details["site_name"],
        }

    def is_shown(self):
        return True


class ArticleSummaryItem(SummaryItem):
    order = 300
    template_name = "wagtailadmin/summary_items/article_summary_item.html"

    def get_context_data(self, parent_context):
        site_details = get_site_for_user(self.request.user)
        total_article = Article.objects.all().count()
        return {
            "total_article": total_article,
            "site_name": site_details["site_name"],
        }


@hooks.register("construct_homepage_summary_items", order=2)
def add_items_summary_items(request, items):
    items.append(CollectionSummaryItem(request))
    items.append(JournalSummaryItem(request))
    items.append(ArticleSummaryItem(request))


@hooks.register("construct_main_menu")
def reorder_menu_items(request, menu_items):
    for item in menu_items:
        if item.label in WAGTAIL_MENU_APPS_ORDER:
            item.order = get_menu_order(item.label)


@hooks.register("construct_main_menu")
def remove_menu_items(request, menu_items):
    if not request.user.is_superuser:
        menu_items[:] = [
            item
            for item in menu_items
            if item.name not in ["documents", "explorer", "reports"]
        ]
