from django.apps import AppConfig


class WorkspaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "workspace"
    verbose_name = "Workspaces"

    def ready(self):
        # Registers the bearer-token scheme with drf-spectacular. Imported
        # here because spectacular discovers extensions by subclassing, which
        # only happens once the module has been imported.
        from workspace import schema  # noqa: F401
