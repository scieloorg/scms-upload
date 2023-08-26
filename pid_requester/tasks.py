import logging

from django.contrib.auth import get_user_model

from config import celery_app
from pid_requester.controller import PidRequester

User = get_user_model()


def _get_user(request, username=None, user_id=None):
    try:
        return User.objects.get(pk=request.user.id)
    except AttributeError:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)


@celery_app.task(bind=True, name="request_pid_for_file")
def request_pid_for_file(
    self,
    username=None,
    file_path=None,
    is_published=None,
):
    user = _get_user(self.request, username=username)

    pid_requester = PidRequester()
    for resp in pid_requester.request_pid_for_xml_zip(
        file_path, user, is_published=is_published
    ):
        logging.info(resp)
    # return response
