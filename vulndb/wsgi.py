"""WSGI config for VULNDB."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vulndb.settings")

application = get_wsgi_application()
