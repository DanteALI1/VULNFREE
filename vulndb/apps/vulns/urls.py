from django.urls import path

from vulndb.apps.vulns import views

urlpatterns = [
    path("", views.vuln_list, name="vuln_list"),
    path("local/new/", views.vuln_local_create, name="vuln_local_create"),
    path("<str:vuln_id>/", views.vuln_detail, name="vuln_detail"),
]
