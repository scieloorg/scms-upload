from .. import controller
from django.contrib.auth import get_user_model


User = get_user_model()


def run(user_id=None):
    user = User.objects.first()
    controller.load_config(user)
