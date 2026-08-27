from core.users.permission_policies import TeamModelPermissionPolicy
from team.authorization import user_has_active_journal_scope


class UploadModelPermissionPolicy(TeamModelPermissionPolicy):
    def __init__(self, model, denied_actions=()):
        super().__init__(model)
        self.denied_actions = frozenset(denied_actions)

    def user_has_permission(self, user, action):
        if action in self.denied_actions:
            return False
        if not user_has_active_journal_scope(user):
            return False

        return super().user_has_permission(user, action)

    def user_has_any_permission(self, user, actions):
        allowed_actions = set(actions) - self.denied_actions
        if not allowed_actions or not user_has_active_journal_scope(user):
            return False

        return super().user_has_any_permission(user, allowed_actions)

    def users_with_any_permission(self, actions):
        allowed_actions = set(actions) - self.denied_actions

        return super().users_with_any_permission(allowed_actions)
