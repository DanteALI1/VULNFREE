"""Forms for VULNDB."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from vulndb.apps.core.models import SystemSettings
from vulndb.apps.tickets.models import Ticket
from vulndb.apps.vulns.models import Vulnerability

User = get_user_model()


class OrganizationForm(forms.Form):
    organization_name = forms.CharField(label="Название организации", max_length=255)
    local_id_prefix = forms.CharField(label="Префикс локальных ID", max_length=16)

    def clean_local_id_prefix(self):
        try:
            return SystemSettings.validate_prefix(self.cleaned_data["local_id_prefix"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)


class BrandingForm(forms.Form):
    product_name = forms.CharField(label="Название продукта", max_length=64)
    login_title = forms.CharField(label="Заголовок страницы входа", max_length=255, required=False)
    login_text = forms.CharField(
        label="Текст на странице входа", widget=forms.Textarea, required=False
    )
    logo = forms.ImageField(label="Логотип", required=False)

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo:
            from vulndb.apps.core.models import validate_logo_file

            validate_logo_file(logo)
        return logo


class MailSetupForm(forms.Form):
    mail_enabled = forms.BooleanField(label="Включить почту", required=False)
    mail_provider = forms.ChoiceField(
        label="Провайдер",
        choices=[
            ("smtp", "SMTP"),
            ("exchange", "Exchange"),
            ("office365", "Office 365"),
            ("gmail", "Gmail"),
        ],
        required=False,
    )
    mail_smtp_host = forms.CharField(label="SMTP хост", required=False)
    mail_smtp_port = forms.IntegerField(label="SMTP порт", required=False, initial=587)
    mail_smtp_user = forms.CharField(label="SMTP пользователь", required=False)
    mail_smtp_password = forms.CharField(
        label="SMTP пароль", required=False, widget=forms.PasswordInput
    )
    mail_use_tls = forms.BooleanField(label="TLS", required=False, initial=True)
    mail_from_address = forms.EmailField(label="From", required=False)
    mail_exchange_server = forms.CharField(label="Exchange server", required=False)
    mail_office365_tenant = forms.CharField(label="Office365 tenant", required=False)
    mail_gmail_app_password = forms.CharField(
        label="Gmail app password", required=False, widget=forms.PasswordInput
    )
    test_to = forms.EmailField(label="Адрес для проверки", required=False)
    skip = forms.BooleanField(label="Пропустить", required=False)


class DatabaseForm(forms.Form):
    db_host = forms.CharField(label="Хост", required=False)
    db_port = forms.IntegerField(label="Порт", required=False, initial=5432)
    db_name = forms.CharField(label="Имя БД", required=False)
    db_user = forms.CharField(label="Пользователь", required=False)
    db_sslmode = forms.CharField(label="SSL mode", required=False, initial="prefer")
    skip = forms.BooleanField(label="Пропустить (использовать текущую БД)", required=False)
    action = forms.ChoiceField(
        label="Действие",
        choices=[
            ("save", "Сохранить метаданные"),
            ("test", "Проверить подключение"),
            ("skip", "Пропустить"),
        ],
        required=False,
        initial="save",
    )


class SourcesForm(forms.Form):
    nvd_enabled = forms.BooleanField(label="NVD", required=False)
    nvd_api_key = forms.CharField(label="NVD API Key", required=False)
    nvd_sync_interval_minutes = forms.IntegerField(
        label="Интервал NVD (мин)", min_value=5, initial=60
    )
    kev_enabled = forms.BooleanField(label="CISA KEV", required=False)
    kev_sync_interval_minutes = forms.IntegerField(
        label="Интервал KEV (мин)", min_value=5, initial=360
    )
    bdu_enabled = forms.BooleanField(label="БДУ ФСТЭК", required=False)
    bdu_xlsx_url = forms.URLField(label="URL XLSX БДУ", required=False, assume_scheme="https")
    bdu_sync_interval_minutes = forms.IntegerField(
        label="Интервал БДУ (мин)", min_value=60, initial=1440
    )
    bdu_verify_ssl = forms.BooleanField(label="Проверять SSL БДУ", required=False)


class AdminSetupForm(forms.Form):
    username = forms.CharField(label="Логин", max_length=150)
    email = forms.EmailField(label="Email", required=False)
    full_name = forms.CharField(label="ФИО", max_length=255, required=False)
    password1 = forms.CharField(label="Пароль", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Повтор пароля", widget=forms.PasswordInput)

    def clean(self):
        from django.contrib.auth.password_validation import validate_password

        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            raise forms.ValidationError("Пароли не совпадают.")
        if User.objects.filter(username=cleaned.get("username")).exists():
            raise forms.ValidationError("Пользователь уже существует.")
        password = cleaned.get("password1")
        if password:
            validate_password(password)
        return cleaned


class LocalVulnerabilityForm(forms.ModelForm):
    class Meta:
        model = Vulnerability
        fields = [
            "title",
            "description_nvd",
            "severity",
            "cvss_score",
            "vendor",
            "product_name",
            "product_version",
            "remediation",
            "cwe",
        ]
        widgets = {
            "description_nvd": forms.Textarea(attrs={"rows": 4}),
            "remediation": forms.Textarea(attrs={"rows": 3}),
            "cwe": forms.TextInput(attrs={"placeholder": '["CWE-79"]'}),
        }

    def clean_cwe(self):
        value = self.cleaned_data.get("cwe")
        if isinstance(value, str):
            import json

            try:
                value = json.loads(value) if value.strip() else []
            except json.JSONDecodeError:
                value = [v.strip() for v in value.split(",") if v.strip()]
        return value or []


class TicketCreateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["vulnerability", "priority", "reason", "assignee"]
        widgets = {"reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = User.objects.filter(is_active=True)
        self.fields["assignee"].required = False
