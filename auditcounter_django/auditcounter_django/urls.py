"""
URL configuration for auditcounter_django project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another Urlconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from .onboarding import guided_setup, setup, save_modules, setup_preview
from document_extraction.help_views import ask_help
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("configuration-lab/", include("accounts_receivable.prototype_urls")),
    path("guided-setup/", guided_setup, name="guided_setup"),
    path("setup-preview/", setup_preview, name="setup_preview"),
    path("setup/", setup, name="setup"),
    path("setup/modules/", save_modules, name="setup_modules"),
    path("help/ask/", ask_help, name="ask_help"),
    path("admin/", admin.site.urls),
    path("accounts-receivable/", include("accounts_receivable.urls")),
    path("accounts-payable/", include("accounts_payable.urls")),
    path("databases/", include("db_extraction.urls")),
    path("router/", include("router.urls")),
    path("encoder/", include("encoder.urls")),
    path("", include("document_extraction.urls")),
]
