from django.apps import AppConfig


class NotifyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vulndb.apps.notify"
    label = "notify"
    verbose_name = "Уведомления"
