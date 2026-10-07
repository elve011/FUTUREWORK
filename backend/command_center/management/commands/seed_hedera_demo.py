"""Create a local Hedera testnet payment demo account and completed project."""

import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.crypto import get_random_string

from command_center.models import (
    EvidenceSubmission,
    FreelancerProfile,
    ProjectAgreement,
    ProjectApproval,
    ProjectAuditLog,
    ProjectMilestone,
    ProjectReference,
)


DEMO_EMAIL = "hedera.demo@example.test"
DEMO_GITHUB_LOGIN = "elve011"
DEMO_REPOSITORY = "elve011/repo-test"
PROJECT_ID = "HEDERA-DEMO-001"
MILESTONES = (
    ("HEDERA-DEMO-001-MS-01", "Interface livrée", 40, 20),
    ("HEDERA-DEMO-001-MS-02", "API et intégration terminées", 30, 15),
    ("HEDERA-DEMO-001-MS-03", "Tests et mise en production achevés", 30, 15),
)


class Command(BaseCommand):
    help = "Create a DEMO_ONLY account and completed HBAR payment scenario (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_hedera_demo est désactivé lorsque DEBUG=False.")

        User = get_user_model()

        created_password = None
        with transaction.atomic():
            user = User.objects.filter(email__iexact=DEMO_EMAIL).first()
            if user:
                profile = FreelancerProfile.objects.filter(user=user).first()
                if profile is None or not profile.is_demo_only:
                    raise CommandError(f"Le compte {DEMO_EMAIL} existe déjà et n'est pas DEMO_ONLY.")
                profile.github_login = DEMO_GITHUB_LOGIN
                profile.save(update_fields=("github_login", "updated_at"))
            else:
                created_password = get_random_string(32)
                user = User.objects.create_user(
                    username=DEMO_EMAIL,
                    email=DEMO_EMAIL,
                    first_name="Hedera Demo",
                    password=created_password,
                )
                profile = FreelancerProfile.objects.create(
                    user=user,
                    display_name="Hedera Demo",
                    role=FreelancerProfile.Role.FREELANCER,
                    github_login=DEMO_GITHUB_LOGIN,
                    is_demo_only=True,
                )

            project, created = ProjectReference.objects.get_or_create(
                external_id=PROJECT_ID,
                defaults={
                    "title": "Projet de démonstration Hedera",
                    "status": "COMPLETED",
                    "description": "Dépôt GitHub de test ; les preuves préchargées sont synthétiques et marquées TEST_ONLY.",
                    "provenance": ProjectReference.Provenance.TEST_ONLY,
                    "created_by": DEMO_EMAIL,
                    "owner": user,
                    "is_demo_only": True,
                },
            )
            if not created and (not project.is_demo_only or project.owner_id != user.pk):
                raise CommandError(f"Le projet {PROJECT_ID} existe déjà hors du compte de démonstration.")

            ProjectAgreement.objects.update_or_create(
                project=project,
                defaults={
                    "budget_amount": "50.00",
                    "currency": "HBAR",
                    "total_hours": 100,
                    "total_work_units": 100,
                    "conditions": ["Jalon achevé", "Preuve vérifiée", "Approbation client"],
                    "approval_status": ProjectAgreement.ApprovalStatus.APPROVED,
                    "github_repository": DEMO_REPOSITORY,
                    "provenance": ProjectReference.Provenance.TEST_ONLY,
                    "plan_status": "COMPLETED",
                },
            )
            ProjectApproval.objects.get_or_create(
                kind=ProjectApproval.Kind.AGREEMENT,
                project=project,
                milestone=None,
                defaults={
                    "decision": "APPROVED",
                    "actor": user,
                    "reason": "Approbation synthétique pour le scénario local Hedera.",
                    "provenance": ProjectReference.Provenance.TEST_ONLY,
                },
            )

            for index, (milestone_id, title, units, hours) in enumerate(MILESTONES, start=1):
                milestone, _ = ProjectMilestone.objects.update_or_create(
                    project=project,
                    milestone_id=milestone_id,
                    defaults={
                        "title": title,
                        "description": "Jalon synthétique achevé pour le scénario de paiement local.",
                        "order": index,
                        "planned_work_units": units,
                        "completed_work_units": units,
                        "estimated_hours": hours,
                        "status": ProjectMilestone.Status.COMPLETED,
                        "provenance": ProjectReference.Provenance.TEST_ONLY,
                        "is_demo_only": True,
                    },
                )
                ProjectApproval.objects.get_or_create(
                    kind=ProjectApproval.Kind.MILESTONE,
                    project=project,
                    milestone=milestone,
                    defaults={
                        "decision": "APPROVED",
                        "actor": user,
                        "reason": "Approbation synthétique pour le scénario local Hedera.",
                        "provenance": ProjectReference.Provenance.TEST_ONLY,
                    },
                )
                evidence_id = f"{milestone_id}-EVIDENCE"
                EvidenceSubmission.objects.update_or_create(
                    project=project,
                    evidence_id=evidence_id,
                    defaults={
                        "milestone": milestone,
                        "source": "TEST_ONLY",
                        "status": EvidenceSubmission.Status.VERIFIED,
                        "score": 100,
                        "proof_hash": hashlib.sha256(evidence_id.encode("utf-8")).hexdigest(),
                        "reasons": ["Preuve synthétique vérifiée pour la démonstration locale."],
                        "source_refs": [{"type": "DEMO_FIXTURE", "id": evidence_id}],
                        "submitted_by": user,
                        "source_event_id": f"DEMO-{milestone_id}",
                        "is_demo_only": True,
                    },
                )

            ProjectAuditLog.objects.get_or_create(
                project=project,
                actor_id=DEMO_EMAIL,
                action="HEDERA_DEMO_SEEDED",
                defaults={"details": {"source": "TEST_ONLY", "transfers": "LOCAL_SIMULATION_ONLY"}},
            )

        self.stdout.write(self.style.SUCCESS(f"Compte DEMO_ONLY prêt : {DEMO_EMAIL}"))
        self.stdout.write(f"Projet : {PROJECT_ID} · {len(MILESTONES)}/{len(MILESTONES)} jalons · 100/100 unités terminés")
        if created_password:
            self.stdout.write("Mot de passe initial (affiché une seule fois) :")
            self.stdout.write(created_password)
        else:
            self.stdout.write("Compte existant conservé ; aucun mot de passe n'a été modifié.")
        self.stdout.write("Un transfert réel de 0,1 HBAR/testnet par milestone est activable avec un signer local renouvelé.")
        self.stdout.write("Aucune transaction n'est envoyée pendant cette commande.")
