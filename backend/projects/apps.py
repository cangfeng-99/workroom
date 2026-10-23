from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'projects'

    def ready(self) -> None:
        # Local, additive log redaction: one-time invitation tokens must not
        # end up in request/server access logs. No logger is disabled and no
        # settings are changed.
        from projects.invitation_logging import install

        install()
