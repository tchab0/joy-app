from django.apps import AppConfig


class PlanningConfig(AppConfig):
    name = "planning"
    verbose_name = "Planning"

    def ready(self):
        from planning import signals  # noqa: F401
