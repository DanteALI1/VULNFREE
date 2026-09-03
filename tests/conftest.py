import pytest


@pytest.fixture(autouse=True)
def _celery_eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def user_factory(django_user_model):
    def _make(username, role, **kwargs):
        password = kwargs.pop("password", "Passw0rd!")
        user = django_user_model.objects.create_user(
            username=username, password=password, role=role, **kwargs
        )
        return user

    return _make
