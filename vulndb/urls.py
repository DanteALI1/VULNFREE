"""Root URL configuration for VULNDB."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from vulndb.apps.core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("readyz", core_views.readyz, name="readyz"),
    path("", core_views.dashboard, name="dashboard"),
    path("setup/", include("vulndb.apps.core.urls_setup")),
    path("accounts/", include("vulndb.apps.accounts.urls")),
    path("vulns/", include("vulndb.apps.vulns.urls")),
    path("tickets/", include("vulndb.apps.tickets.urls")),
    path("settings/sync/<str:source>/", core_views.trigger_sync, name="trigger_sync"),
    path("settings/sync-status/", core_views.sync_status_partial, name="sync_status"),
    path("settings/metrics/", core_views.system_metrics, name="system_metrics"),
    path("settings/", core_views.settings_view, name="settings"),
    path("settings/<str:tab>/", core_views.settings_view, name="settings_tab"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
