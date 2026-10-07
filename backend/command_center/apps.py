from django.apps import AppConfig


class CommandCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "command_center"
    verbose_name = "FUTUREWORK AI Command Center"

    def ready(self):
        from django.db.backends.signals import connection_created

        connection_created.connect(_configure_sqlite, dispatch_uid="dev4-sqlite-pragmas")


def _configure_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    database_name = str(connection.settings_dict["NAME"])
    if database_name == ":memory:" or database_name.startswith("file:"):
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
