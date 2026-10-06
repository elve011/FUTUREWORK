"""Validate and restore a backup to a new local SQLite path (never live DB)."""

import os
import sqlite3
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Integrity-check a SQLite backup and restore it to a new file path."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Verified or untrusted SQLite backup to validate.")
        parser.add_argument("destination", help="New local .sqlite3 path; existing files are refused.")

    def handle(self, source, destination, **options):
        if connection.vendor != "sqlite":
            raise CommandError("This standalone service requires SQLite.")
        source_path = Path(source).expanduser().resolve()
        destination_path = Path(destination).expanduser().resolve()
        live_path = Path(settings.DATABASES["default"]["NAME"]).expanduser().resolve()
        if not source_path.is_file():
            raise CommandError("Backup source does not exist.")
        if destination_path == source_path or destination_path == live_path:
            raise CommandError("Restore requires a new destination and refuses to overwrite the live database.")
        if destination_path.exists():
            raise CommandError("Restore destination already exists; choose a new path.")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(prefix=f".{destination_path.name}.", suffix=".tmp", dir=destination_path.parent)
        os.close(fd)
        source_db = None
        target_db = None
        try:
            source_db = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
            check = source_db.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise CommandError(f"Source backup integrity check failed: {check}")
            target_db = sqlite3.connect(temporary_path)
            source_db.backup(target_db)
            restored_check = target_db.execute("PRAGMA integrity_check").fetchone()[0]
            if restored_check != "ok":
                raise CommandError(f"Restored database integrity check failed: {restored_check}")
            target_db.close()
            target_db = None
            source_db.close()
            source_db = None
            if destination_path.exists():
                raise CommandError("Restore destination appeared during restore; refusing to replace it.")
            os.rename(temporary_path, destination_path)
        finally:
            if target_db is not None:
                target_db.close()
            if source_db is not None:
                source_db.close()
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
        self.stdout.write(self.style.SUCCESS(f"SQLite restore verified at new path: {destination_path}"))
