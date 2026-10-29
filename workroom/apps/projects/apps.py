from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.projects'
    verbose_name = '项目'

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registers the receivers)
