"""
Quem pode solicitar e revisar a conversão HTML -> XML: superusuários (todas
as coleções) e gestores ativos de coleção (``CollectionTeamMember`` com
papel ``manager``), só nas coleções que gerenciam.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q
from wagtail.permission_policies.base import BasePermissionPolicy


def managed_collections(user):
    """
    Coleções que ``user`` gerencia: None = todas (superusuário); lista
    vazia = nenhuma.
    """
    if not (user and user.is_authenticated and user.is_active):
        return []
    if user.is_superuser:
        return None
    from collection.models import Collection
    from team.models import CollectionTeamMember, TeamRole

    ids = CollectionTeamMember.objects.filter(
        user=user, role=TeamRole.MANAGER, is_active_member=True, collection__isnull=False
    ).values_list("collection_id", flat=True)
    return list(Collection.objects.filter(pk__in=ids).order_by("acron"))


def can_review(user):
    collections = managed_collections(user)
    return collections is None or bool(collections)


def managed_collection_ids(user):
    collections = managed_collections(user)
    if collections is None:
        return None
    return [c.pk for c in collections]


class CollectionManagerPermissionPolicy(BasePermissionPolicy):
    """
    Ver e editar: superusuários e gestores de coleção, restritos às suas
    coleções. Adicionar: ninguém (os registros são criados pela revisão).
    Apagar: só superusuários.

    ``collection_path``: caminho do campo da coleção a partir do modelo.
    """

    collection_path = "collection"

    def user_has_permission(self, user, action):
        if action == "add":
            return False
        if action == "delete":
            return bool(user.is_active and user.is_superuser)
        return can_review(user)

    def user_has_any_permission(self, user, actions):
        return any(self.user_has_permission(user, action) for action in actions)

    def users_with_any_permission(self, actions):
        from team.models import CollectionTeamMember, TeamRole

        managers = CollectionTeamMember.objects.filter(
            role=TeamRole.MANAGER, is_active_member=True
        ).values_list("user_id", flat=True)
        return get_user_model().objects.filter(
            Q(is_active=True) & (Q(is_superuser=True) | Q(pk__in=managers))
        )

    def users_with_permission(self, action):
        return self.users_with_any_permission([action])

    def _collection_id(self, instance):
        value = instance
        for part in self.collection_path.split("__"):
            value = getattr(value, part, None)
            if value is None:
                return None
        return value.pk

    def user_has_permission_for_instance(self, user, action, instance):
        if not self.user_has_permission(user, action):
            return False
        ids = managed_collection_ids(user)
        return ids is None or self._collection_id(instance) in ids

    def instances_user_has_permission_for(self, user, action):
        qs = self.model.objects.all()
        if not self.user_has_permission(user, action):
            return qs.none()
        return filter_by_managed_collections(qs, user, self.collection_path)


class IssuePermissionPolicy(CollectionManagerPermissionPolicy):
    collection_path = "problem__collection"


def filter_by_managed_collections(qs, user, collection_path="collection"):
    ids = managed_collection_ids(user)
    if ids is None:
        return qs
    return qs.filter(**{f"{collection_path}__in": ids})
