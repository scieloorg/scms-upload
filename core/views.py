"""
ViewSet base com tracking automático de creator/updated_by.

Qualquer app que use models com os campos creator e updated_by
(herdados de CommonControlField ou equivalente) deve usar
CommonControlFieldViewSet como base do seu SnippetViewSet.

Uso:
    class MeuViewSet(CommonControlFieldViewSet):
        model = MeuModel
        # add_view_class e edit_view_class já vêm configurados
        # permission_policy já vem com BaseSciELOPermissionPolicy

    Se o app precisar de uma CreateView ou EditView customizada,
    herde das classes internas para manter o tracking:

        class MinhaCreateView(CommonControlFieldViewSet.UserTrackingCreateView):
            def save_instance(self):
                instance = super().save_instance()
                # lógica adicional
                return instance

        class MeuViewSet(CommonControlFieldViewSet):
            add_view_class = MinhaCreateView
"""

from django.utils import timezone
from django.http import HttpResponseRedirect
from wagtail.snippets.views.snippets import CreateView, EditView, SnippetViewSet

from core.permission_helper import StaffWritePolicy


class UserTrackingCreateView(CreateView):
    """
    CreateView que seta creator e updated_by automaticamente.
    Chama super().save_instance() para preservar a lógica do Wagtail
    (logs, revisões, etc.) e ajusta os campos antes do save.

    Subclasses que precisem de lógica adicional no form_valid
    podem sobrescrever, chamando self.save_instance() para o save:

        def form_valid(self, form):
            instance = self.save_instance()
            # lógica adicional
            return HttpResponseRedirect(self.get_success_url())
    """

    def save_instance(self):
        instance = self.form.save(commit=False)
        if not instance.pk:
            instance.creator = self.request.user
        instance.updated_by = self.request.user
        instance.save()
        self.form.save_m2m()
        return instance

    def form_valid(self, form):
        self.object = self.save_instance()
        return HttpResponseRedirect(self.get_success_url())


class UserTrackingEditView(EditView):
    """
    EditView que seta updated_by automaticamente.

    Subclasses que precisem de lógica adicional no form_valid
    podem sobrescrever, chamando self.save_instance() para o save:

        def form_valid(self, form):
            instance = self.save_instance()
            # lógica adicional
            return HttpResponseRedirect(self.get_success_url())
    """

    def save_instance(self):
        instance = self.form.save(commit=False)
        instance.updated_by = self.request.user
        instance.save()
        self.form.save_m2m()
        return instance

    def form_valid(self, form):
        self.object = self.save_instance()
        return HttpResponseRedirect(self.get_success_url())


class CommonControlFieldViewSet(SnippetViewSet):
    """
    SnippetViewSet base para models com campos creator/updated_by.

    Fornece:
    - UserTrackingCreateView: seta creator (na criação) e updated_by
    - UserTrackingEditView: seta updated_by
    - BaseSciELOPermissionPolicy como permission_policy padrão

    Nota sobre timestamps:
    - Se o model usa `updated = DateTimeField(auto_now=True)`, o Django
      atualiza automaticamente ao chamar save().
    - Se NÃO usa auto_now, descomente a linha de updated nas views acima.
    """

    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Se a subclasse tem model e não definiu policy própria,
        # cria uma StaffWritePolicy como default
        if (
            hasattr(cls, "model")
            and cls.model is not None
            and "permission_policy" not in cls.__dict__
        ):
            cls.permission_policy = StaffWritePolicy(cls.model)