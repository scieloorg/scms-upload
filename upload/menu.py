from wagtail.admin.menu import Menu, SubmenuMenuItem


class UploadSectionMenu(Menu):
    def render_component(self, request):
        components = []
        items = sorted(
            self.menu_items_for_request(request), key=lambda item: item.order
        )
        for item in items:
            if not isinstance(item, SubmenuMenuItem):
                components.append(item.render_component(request))
                continue

            section = item.menu.render_component(request)
            for index, component in enumerate(section):
                component.name = f"{item.name}-{component.name}"
                component.attrs = {
                    **component.attrs,
                    "aria-label": f"{item.label}: {component.label}",
                }
                if index == 0:
                    component.classname += " upload-menu-section"
                    component.attrs["data-upload-section"] = str(item.label)
                components.append(component)

        return components
