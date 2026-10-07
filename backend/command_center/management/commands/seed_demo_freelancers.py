"""Create clearly marked development-only sample accounts with one-time passwords."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.crypto import get_random_string

from command_center.models import FreelancerProfile


class Command(BaseCommand):
    help = "Create DEMO_ONLY freelancer accounts (DEBUG mode only)."

    ACCOUNTS = (
        ("Emna Abdelli", "emna.freelancer@example.test", FreelancerProfile.Role.FREELANCER),
        ("Sami Ben Ali", "sami.freelancer@example.test", FreelancerProfile.Role.FREELANCER),
        ("Nour Trabelsi", "nour.freelancer@example.test", FreelancerProfile.Role.FREELANCER),
        ("Client Démonstration", "client.demo@example.test", FreelancerProfile.Role.CLIENT),
    )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_freelancers est désactivé lorsque DEBUG=False.")
        User = get_user_model()
        created_count = 0
        for display_name, email, role in self.ACCOUNTS:
            normalized_email = email.casefold()
            user = User.objects.filter(email__iexact=normalized_email).first()
            if user:
                profile = FreelancerProfile.objects.filter(user=user).first()
                if profile is None or not profile.is_demo_only:
                    raise CommandError(f"Le compte {email} existe déjà et n'est pas DEMO_ONLY.")
                self.stdout.write(f"Compte DEMO_ONLY déjà présent : {email}")
                continue

            password = get_random_string(24)
            user = User.objects.create_user(
                username=normalized_email,
                email=normalized_email,
                first_name=display_name,
                password=password,
            )
            FreelancerProfile.objects.create(
                user=user,
                display_name=display_name,
                role=role,
                is_demo_only=True,
            )
            created_count += 1
            self.stdout.write(f"Compte DEMO_ONLY créé : {email}")
            self.stdout.write(f"Mot de passe initial (affiché une seule fois) : {password}")
        self.stdout.write(self.style.SUCCESS(f"{created_count} compte(s) de démonstration créé(s)."))
