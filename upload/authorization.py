from team.authorization import get_user_permission_journal_ids


def user_can_act_on_package(user, permission, package):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True

    journal = package.effective_journal
    journal_id = journal.pk if journal else None

    return journal_id in get_user_permission_journal_ids(user, "upload", permission)
