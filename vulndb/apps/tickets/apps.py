from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vulndb.apps.tickets"
    label = "tickets"
    verbose_name = "Заявки"
