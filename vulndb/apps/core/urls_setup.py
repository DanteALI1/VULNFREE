from django.urls import path

from vulndb.apps.core import views

urlpatterns = [
    path("", views.setup_wizard, name="setup"),
    path("validate-prefix/", views.setup_validate_prefix, name="setup_validate_prefix"),
    path("<str:step>/", views.setup_wizard, name="setup_step"),
]
