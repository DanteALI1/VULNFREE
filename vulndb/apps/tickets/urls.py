from django.urls import path

from vulndb.apps.tickets import views

urlpatterns = [
    path("", views.ticket_list, name="ticket_list"),
    path("new/", views.ticket_create, name="ticket_create"),
    path("<int:number>/", views.ticket_detail, name="ticket_detail"),
    path("<int:number>/action/", views.ticket_action, name="ticket_action"),
]
