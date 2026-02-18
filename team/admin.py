from wagtail_modeladmin.options import ModelAdmin, modeladmin_register

from team.models import (
    Company,
    CompanyTeamMember,
    JournalCompanyContract,
    JournalTeamMember,
)


class CompanyAdmin(ModelAdmin):
    model = Company
    menu_label = "Companies"
    menu_icon = "group"
    list_display = ("name", "url", "contact_email", "certified_since", "is_active", "created", "updated")
    list_filter = ("is_active", "certified_since", "created", "updated")
    search_fields = ("name", "contact_email", "url")


class JournalTeamMemberAdmin(ModelAdmin):
    model = JournalTeamMember
    menu_label = "Journal Team Members"
    menu_icon = "user"
    list_display = ("user", "journal", "role", "is_active_member", "created")
    list_filter = ("role", "is_active_member", "created")
    search_fields = ("user__username", "user__email", "journal__title")


class CompanyTeamMemberAdmin(ModelAdmin):
    model = CompanyTeamMember
    menu_label = "Company Team Members"
    menu_icon = "user"
    list_display = ("user", "company", "role", "is_active_member", "created")
    list_filter = ("role", "is_active_member", "created")
    search_fields = ("user__username", "user__email", "company__name")


class JournalCompanyContractAdmin(ModelAdmin):
    model = JournalCompanyContract
    menu_label = "Journal-Company Contracts"
    menu_icon = "doc-full"
    list_display = ("journal", "company", "is_active", "start_date", "end_date")
    list_filter = ("is_active", "start_date", "end_date")
    search_fields = ("journal__title", "company__name")


modeladmin_register(CompanyAdmin)
modeladmin_register(JournalTeamMemberAdmin)
modeladmin_register(CompanyTeamMemberAdmin)
modeladmin_register(JournalCompanyContractAdmin)
