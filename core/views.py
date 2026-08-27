from wagtail.snippets.views.snippets import CreateView, EditView, SnippetViewSet


class CommonControlFieldViewSet(SnippetViewSet):
    """
    Mixin para adicionar tracking de usuário em qualquer SnippetViewSet
    Compatível com Wagtail 6.4.2
    """

    class UserTrackingCreateView(CreateView):
        def save_instance(self):
            instance = self.form.save(commit=False)
            if not instance.pk:
                instance.creator = self.request.user
            instance.updated_by = self.request.user
            instance.save()
            if hasattr(self.form, "save_m2m"):
                self.form.save_m2m()
            return instance

    class UserTrackingEditView(EditView):
        def save_instance(self):
            instance = self.form.save(commit=False)
            instance.updated_by = self.request.user
            instance.save()
            if hasattr(self.form, "save_m2m"):
                self.form.save_m2m()
            return instance

    # Define as views customizadas
    add_view_class = UserTrackingCreateView
    edit_view_class = UserTrackingEditView

    def get_queryset(self, request=None):
        return self.model.objects.all()
