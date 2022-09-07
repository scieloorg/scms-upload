from django.contrib.auth import get_user_model


User = get_user_model()


def get_users(include_staff=False):
    return User.objects.filter(is_staff=include_staff).all()
