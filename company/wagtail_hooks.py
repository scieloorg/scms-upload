from wagtail.contrib.modeladmin.options import ModelAdmin, modeladmin_register

from company.models import Company, CompanyMember
from company.permission_helper import (
    CompanyPermissionHelper,
    CompanyMemberPermissionHelper,
)


class CompanyAdmin(ModelAdmin):
    model = Company
    menu_label = "Companies"
    menu_icon = "group"
    list_display = ("name", "acronym", "location", "created", "updated")
    search_fields = ("name", "acronym")
    list_filter = ("created", "updated")
    permission_helper_class = CompanyPermissionHelper


class CompanyMemberAdmin(ModelAdmin):
    model = CompanyMember
    menu_label = "Company Members"
    menu_icon = "user"
    list_display = ("user", "company", "role", "is_active_member", "created")
    search_fields = ("user__username", "user__email", "company__name")
    list_filter = ("role", "is_active_member", "created")
    permission_helper_class = CompanyMemberPermissionHelper


modeladmin_register(CompanyAdmin)
modeladmin_register(CompanyMemberAdmin)
