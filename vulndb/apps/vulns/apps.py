from django.apps import AppConfig


class VulnsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vulndb.apps.vulns"
    label = "vulns"
    verbose_name = "Уязвимости"
