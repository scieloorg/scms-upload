from wagtail.users.apps import WagtailUsersAppConfig


class ProtectedWagtailUsersAppConfig(WagtailUsersAppConfig):
    group_viewset = "core.wagtail_users_views.ProtectedGroupViewSet"
    user_viewset = "core.wagtail_users_views.ProtectedUserViewSet"
