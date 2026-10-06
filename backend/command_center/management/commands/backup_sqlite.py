"""Create a consistent SQLite backup using the SQLite online backup API."""

import os
import sqlite3
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create and integrity-check a consistent SQLite database backup."

    def add_arguments(self, parser):
        parser.add_argument("destination", help="Destination .sqlite3 file (must be on local durable storage).")

    def handle(self, destination, **options):
        if connection.vendor != "sqlite":
            raise CommandError("This standalone service requires SQLite.")
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if connection.settings_dict["NAME"] == ":memory:":
            source = connection.connection
        else:
            source = connection.connection
        if source is None:
            connection.ensure_connection()
            source = connection.connection
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(fd)
        try:
            target = sqlite3.connect(temp_name)
            try:
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise CommandError(f"Backup integrity check failed: {result}")
            finally:
                target.close()
            os.replace(temp_name, destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.stdout.write(self.style.SUCCESS(f"SQLite backup verified: {destination}"))
