"""
Botões customizados na listagem de snippets do módulo Upload.

Usa core.snippet_buttons para registro genérico e
upload.permissions para regras de negócio.
"""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.snippet_buttons import register_snippet_buttons, make_button
from . import choices
from .permission_helper import UploadPermissions


# ---------------------------------------------------------------
# Lazy import para evitar import circular
# ---------------------------------------------------------------
_BUTTON_MODELS = None


def _get_button_models():
    global _BUTTON_MODELS
    if _BUTTON_MODELS is None:
        from .models import (
            Package,
            QAPackage,
            ReadyToPublishPackage,
            ArchivedPackage,
        )
        _BUTTON_MODELS = (Package, QAPackage, ReadyToPublishPackage, ArchivedPackage)
    return _BUTTON_MODELS


# ---------------------------------------------------------------
# Gerador de botões condicionais
# ---------------------------------------------------------------
def _upload_buttons(obj, user):
    """
    Gera botões condicionais baseados em status e permissão.
    Equivalente ao antigo UploadButtonHelper.get_buttons_for_obj().
    """
    is_staff = UploadPermissions.user_is_staff(user)

    # Só mostra botões customizados se a validação terminou
    if hasattr(obj, "is_validation_finished") and not obj.is_validation_finished:
        return

    # Botão: Finalizar depósito
    if obj.status == choices.PS_VALIDATED_WITH_ERRORS:
        yield make_button(
            _("Finish deposit"),
            reverse("upload:finish_deposit") + f"?package_id={obj.id}",
            priority=10,
        )

    # Botões exclusivos de analista (staff)
    if is_staff:
        # Aceitar / Rejeitar / Delegar
        if obj.status in (
            choices.PS_PENDING_QA_DECISION,
            choices.PS_VALIDATED_WITH_ERRORS,
        ):
            yield make_button(
                _("Accept / Reject the package or delegate it"),
                reverse("upload:assign") + f"?package_id={obj.id}",
                priority=20,
            )

        # Arquivar
        if obj.status == choices.PS_UNEXPECTED:
            yield make_button(
                _("Archive"),
                reverse("upload:archive_package") + f"?package_id={obj.id}",
                priority=30,
            )


# ---------------------------------------------------------------
# Registro do hook
# ---------------------------------------------------------------
register_snippet_buttons(
    model_or_models=_get_button_models(),
    access_check=UploadPermissions.user_can_access,
    button_generator=_upload_buttons,
)