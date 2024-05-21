from article.tasks import initiate_article_availability_check


def run(pid_v3, username=None, user_id=None):
    initiate_article_availability_check.apply_async(
        kwargs=dict(
            username=username,
            user_id=user_id,
            article_pid_v3=pid_v3,
        )
    )