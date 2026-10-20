from team.authorization import get_user_permission_journal_ids


def user_can_act_on_package(user, permission, package):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True

    journal_id = package.journal_id
    if not journal_id and package.issue_id:
        journal_id = package.issue.journal_id
    if not journal_id and package.article_id:
        journal_id = package.article.journal_id

    return journal_id in get_user_permission_journal_ids(user, "upload", permission)
