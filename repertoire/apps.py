from django.apps import AppConfig


class RepertoireConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "repertoire"
    verbose_name = "Répertoire"

    def ready(self):
        from repertoire import signals  # noqa: F401
