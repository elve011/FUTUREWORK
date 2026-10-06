import json
import logging
import os
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils.timezone import localdate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .contracts import build_project_contract
from .hedera_service import create_fungible_token, normalize_transaction_id
from .models import (
    Milestone,
    Project,
    ProjectPlanVersion,
    Tokenization,
    WorkAgreement,
    WorkUnit,
)
from .planner import checkDeadlines, updateProjectPlan
from .serializers import (
    MilestoneSerializer,
    ProjectSerializer,
    WorkAgreementSerializer,
)


logger = logging.getLogger(__name__)


class ProjectListCreateView(generics.ListCreateAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer


class ProjectDetailView(generics.RetrieveAPIView):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    lookup_field = "project_id"
    lookup_url_kwarg = "project_id"


class WorkAgreementView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        agreement = project.agreements.order_by("-version").first()

        if agreement is None:
            return Response(
                {
                    "code": "AGREEMENT_NOT_FOUND",
                    "detail": "No Work Agreement exists for this project yet.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(WorkAgreementSerializer(agreement).data)

    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        serializer = WorkAgreementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        latest_version = (
            project.agreements.aggregate(max_version=Max("version"))[
                "max_version"
            ]
            or 0
        )

        with transaction.atomic():
            WorkAgreement.objects.filter(
                project=project,
                status=WorkAgreement.Status.ACTIVE,
            ).update(status=WorkAgreement.Status.SUPERSEDED)

            agreement = serializer.save(
                project=project,
                version=latest_version + 1,
                status=WorkAgreement.Status.ACTIVE,
            )

            project.status = Project.Status.ACTIVE
            project.save(update_fields=["status", "updated_at"])

        return Response(
            WorkAgreementSerializer(agreement).data,
            status=status.HTTP_201_CREATED,
        )


class WorkAgreementHistoryView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        return Response(
            WorkAgreementSerializer(
                project.agreements.order_by("-version"), many=True
            ).data
        )


class ProjectMilestonesView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        milestones = project.milestones.all()
        return Response(MilestoneSerializer(milestones, many=True).data)

    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        return self._save_milestones(
            request,
            project,
            replace_existing=False,
        )

    def put(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        return self._save_milestones(
            request,
            project,
            replace_existing=True,
        )

    def _save_milestones(self, request, project, replace_existing):
        if not isinstance(request.data, list):
            return Response(
                {
                    "code": "INVALID_MILESTONES_FORMAT",
                    "detail": "Send all milestones together as a JSON array.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if project.milestones.exists() and not replace_existing:
            return Response(
                {
                    "code": "MILESTONES_ALREADY_DEFINED",
                    "detail": "Use PUT to replace the existing project plan.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = MilestoneSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        received_units = sum(
            item["units"] for item in serializer.validated_data
        )

        if received_units != project.total_units:
            return Response(
                {
                    "code": "MILESTONE_UNITS_MISMATCH",
                    "detail": (
                        "The sum of milestone units must equal totalUnits."
                    ),
                    "expectedTotalUnits": project.total_units,
                    "receivedUnits": received_units,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        active_agreement = (
            project.agreements.filter(status=WorkAgreement.Status.ACTIVE)
            .order_by("-version")
            .first()
        )
        if active_agreement is None:
            return Response(
                {"code": "ACTIVE_AGREEMENT_REQUIRED", "detail": "Crée un Work Agreement actif avant le plan."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            next_version = (project.plan_versions.aggregate(max_version=Max("version"))["max_version"] or 0) + 1
            prior_status_units = {
                value: sum(
                    WorkUnit.objects.filter(milestone__project=project, status=value)
                    .values_list("units", flat=True)
                )
                for value in WorkUnit.Status.values
            }
            prior_milestone_statuses = {
                milestone.title: milestone.status
                for milestone in project.milestones.all()
            }
            if replace_existing:
                project.milestones.all().delete()

            milestones = serializer.save(project=project)
            for item in milestones:
                if item.title in prior_milestone_statuses:
                    item.status = prior_milestone_statuses[item.title]
                    item.save(update_fields=["status", "updated_at"])

            # Keep assignment and release totals intact while moving them to
            # the newly proposed Work Unit groups.
            remaining_by_status = dict(prior_status_units)
            new_work_units = WorkUnit.objects.filter(
                milestone__project=project
            ).order_by("milestone__deadline", "milestone_id", "id")
            for unit in new_work_units:
                remaining = unit.units
                portions = []
                for unit_status in (
                    WorkUnit.Status.RELEASED,
                    WorkUnit.Status.ALLOCATED,
                    WorkUnit.Status.PLANNED,
                ):
                    portion = min(remaining, remaining_by_status[unit_status])
                    if portion:
                        portions.append((unit_status, portion))
                        remaining_by_status[unit_status] -= portion
                        remaining -= portion
                    if not remaining:
                        break
                if remaining:
                    portions.append((WorkUnit.Status.PLANNED, remaining))

                unit.units = portions[0][1]
                unit.status = portions[0][0]
                unit.save(update_fields=["units", "status"])
                for unit_status, portion in portions[1:]:
                    WorkUnit.objects.create(
                        milestone=unit.milestone,
                        title=f"{unit.title} — {unit_status.lower()}",
                        description=unit.description,
                        units=portion,
                        status=unit_status,
                    )

            snapshot = [
                {
                    "title": item.title,
                    "description": item.description,
                    "units": item.units,
                    "deadline": item.deadline.isoformat(),
                    "status": item.status,
                    "workUnits": [
                        {"title": unit.title, "description": unit.description, "units": unit.units, "status": unit.status}
                        for unit in item.work_units.all()
                    ],
                }
                for item in milestones
            ]
            ProjectPlanVersion.objects.create(
                project=project,
                version=next_version,
                agreement_version=active_agreement.version,
                snapshot=snapshot,
            )

        response_status = (
            status.HTTP_200_OK if replace_existing else status.HTTP_201_CREATED
        )

        return Response(
            MilestoneSerializer(milestones, many=True).data,
            status=response_status,
        )


class ProjectPlanHistoryView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        return Response([
            {
                "version": item.version,
                "agreementVersion": item.agreement_version,
                "createdAt": item.created_at,
                "milestones": item.snapshot,
            }
            for item in project.plan_versions.all()
        ])


class MilestoneStatusView(APIView):
    def patch(self, request, project_id, milestone_id):
        milestone = get_object_or_404(
            Milestone, project__project_id=project_id, pk=milestone_id
        )
        value = str(request.data.get("status") or "").upper()
        if value not in Milestone.Status.values:
            return Response(
                {"code": "INVALID_MILESTONE_STATUS", "detail": "Statut attendu : PLANNED, IN_PROGRESS ou COMPLETED."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        milestone.status = value
        milestone.save(update_fields=["status", "updated_at"])
        return Response(MilestoneSerializer(milestone).data)


class PlannerPlanView(APIView):
    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)

        agreement = (
            project.agreements.filter(status=WorkAgreement.Status.ACTIVE)
            .order_by("-version")
            .first()
        )

        if agreement is None:
            return Response(
                {
                    "code": "ACTIVE_AGREEMENT_REQUIRED",
                    "detail": "Create an active Work Agreement before planning.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            proposal = updateProjectPlan(agreement)
        except ValueError as error:
            return Response(
                {
                    "code": "PLANNER_INPUT_INVALID",
                    "detail": str(error),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(proposal, status=status.HTTP_200_OK)


class PlannerDeadlinesView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)

        return Response(
            {
                "projectId": project.project_id,
                "checkedAt": localdate().isoformat(),
                "overdueMilestones": checkDeadlines(project),
            },
            status=status.HTTP_200_OK,
        )


class ProjectContractView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)

        try:
            contract = build_project_contract(project)
        except ValueError as error:
            return Response(
                {
                    "code": "ACTIVE_AGREEMENT_REQUIRED",
                    "detail": str(error),
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(contract, status=status.HTTP_200_OK)


class ProjectTokenizeView(APIView):
    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)

        name = str(request.data.get("name") or project.title).strip()
        symbol = str(
            request.data.get("symbol")
            or project.project_id.replace("-", "")
        ).strip().upper()

        if not name or len(name) > 100:
            return Response(
                {
                    "name": [
                        "Le nom est obligatoire et limité à 100 caractères."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not symbol or len(symbol) > 20:
            return Response(
                {
                    "symbol": [
                        "Le symbole est obligatoire et limité à 20 caractères."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        tokenization = Tokenization.objects.filter(project=project).first()

        if tokenization and tokenization.status == Tokenization.Status.CREATED:
            return Response(
                self._serialize(tokenization),
                status=status.HTTP_200_OK,
            )

        if tokenization and tokenization.status == Tokenization.Status.PENDING:
            return Response(
                {
                    "code": "TOKEN_CREATION_PENDING",
                    "detail": "Une création de token est déjà en cours.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if tokenization is None:
            tokenization = Tokenization.objects.create(
                project=project,
                name=name,
                symbol=symbol,
                total_supply=project.total_units,
                decimals=0,
                status=Tokenization.Status.PENDING,
            )
        else:
            tokenization.name = name
            tokenization.symbol = symbol
            tokenization.total_supply = project.total_units
            tokenization.decimals = 0
            tokenization.status = Tokenization.Status.PENDING
            tokenization.save()

        try:
            result = create_fungible_token(
                name=name,
                symbol=symbol,
                total_units=project.total_units,
            )
        except Exception:
            # L’état reste PENDING : après un timeout, on ne sait pas toujours
            # si Hedera a accepté la transaction. Cela évite une création double.
            logger.exception(
                "Token creation failed or its result could not be confirmed "
                "for project %s",
                project.project_id,
            )
            return Response(
                {
                    "code": "TOKEN_CREATION_UNCONFIRMED",
                    "detail": (
                        "Le résultat de la transaction Hedera est incertain. "
                        "Vérifie Hedera avant toute nouvelle tentative."
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        tokenization.token_id = result["token_id"]
        tokenization.transaction_id = result["transaction_id"]
        tokenization.total_supply = result["total_supply"]
        tokenization.decimals = result["decimals"]
        tokenization.hashscan_url = (
            f"https://hashscan.io/testnet/token/{result['token_id']}"
        )
        tokenization.status = Tokenization.Status.CREATED
        tokenization.save(
            update_fields=[
                "token_id",
                "transaction_id",
                "total_supply",
                "decimals",
                "hashscan_url",
                "status",
            ]
        )

        return Response(
            self._serialize(tokenization),
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _serialize(tokenization):
        return {
            "projectId": tokenization.project.project_id,
            "name": tokenization.name,
            "symbol": tokenization.symbol,
            "tokenId": tokenization.token_id,
            "totalSupply": tokenization.total_supply,
            "decimals": tokenization.decimals,
            "transactionId": normalize_transaction_id(
                tokenization.transaction_id
            ),
            "hashscanUrl": tokenization.hashscan_url,
            "status": tokenization.status,
        }


class ProjectTokenView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        tokenization = Tokenization.objects.filter(project=project).first()

        if tokenization is None:
            return Response(
                {
                    "code": "TOKEN_NOT_FOUND",
                    "detail": "Ce projet n’a pas encore de token.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        result = ProjectTokenizeView._serialize(tokenization)
        treasury_account = os.getenv("HEDERA_ACCOUNT_ID", "").strip()
        result["treasuryAccountId"] = treasury_account
        if tokenization.status == Tokenization.Status.CREATED:
            worker_balance = self._read_token_balance(
                tokenization.token_id, project.worker
            )
            if worker_balance is None:
                return Response(
                    {"code": "MIRROR_NODE_UNAVAILABLE", "detail": "Impossible de lire le solde HTS du worker sur Mirror Node."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            allocated = sum(
                WorkUnit.objects.filter(
                    milestone__project=project,
                    status=WorkUnit.Status.ALLOCATED,
                ).values_list("units", flat=True)
            )
            released_status = sum(
                WorkUnit.objects.filter(
                    milestone__project=project,
                    status=WorkUnit.Status.RELEASED,
                ).values_list("units", flat=True)
            )
            treasury_balance = (
                self._read_token_balance(tokenization.token_id, treasury_account)
                if treasury_account
                else None
            )
            result["unitBalances"] = {
                "total": tokenization.total_supply,
                "allocated": allocated,
                "released": worker_balance,
                "remaining": max(0, tokenization.total_supply - allocated - worker_balance),
                "workerHtsBalance": worker_balance,
                "treasuryHtsBalance": treasury_balance,
                "localReleasedUnits": released_status,
                "releasedMatchesHtsBalance": released_status == worker_balance,
            }

        return Response(result, status=status.HTTP_200_OK)

    @staticmethod
    def _read_token_balance(token_id, account_id):
        query = urlencode({"token.id": token_id, "limit": 100})
        url = (
            "https://testnet.mirrornode.hedera.com/api/v1/accounts/"
            f"{account_id}/tokens?{query}"
        )
        try:
            with urlopen(url, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
            return next(
                (int(item.get("balance", 0)) for item in data.get("tokens", [])
                 if item.get("token_id") == token_id),
                0,
            )
        except Exception:
            logger.exception("Could not read HTS balance for %s / %s", account_id, token_id)
            return None


class ProjectTokenAssociationView(APIView):
    """Read the token-association state from Hedera's Testnet Mirror Node."""

    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        tokenization = Tokenization.objects.filter(project=project).first()
        account_id = str(request.query_params.get("accountId") or "").strip()

        if tokenization is None or tokenization.status != Tokenization.Status.CREATED:
            return Response(
                {
                    "code": "TOKEN_NOT_CREATED",
                    "detail": "Crée d’abord le token de ce projet.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9]{5})?", account_id):
            return Response(
                {
                    "code": "INVALID_HEDERA_ACCOUNT_ID",
                    "detail": "L’identifiant du compte Hedera est invalide.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = urlencode({"token.id": tokenization.token_id, "limit": 1})
        url = (
            "https://testnet.mirrornode.hedera.com/api/v1/accounts/"
            f"{account_id}/tokens?{query}"
        )

        try:
            with urlopen(url, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception(
                "Could not verify token association for project %s and account %s",
                project.project_id,
                account_id,
            )
            return Response(
                {
                    "code": "MIRROR_NODE_UNAVAILABLE",
                    "detail": (
                        "Impossible de vérifier l’association sur Hedera "
                        "pour le moment."
                    ),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        associated = any(
            item.get("token_id") == tokenization.token_id
            for item in data.get("tokens", [])
        )
        return Response(
            {
                "projectId": project.project_id,
                "accountId": account_id,
                "tokenId": tokenization.token_id,
                "associated": associated,
            },
            status=status.HTTP_200_OK,
        )


class ProjectTokenReleaseConfirmationView(APIView):
    """Mark allocated Work Units released after Mirror Node confirms their HTS transfer."""

    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        tokenization = Tokenization.objects.filter(project=project).first()
        account_id = str(request.data.get("accountId") or "").strip()
        transaction_id = normalize_transaction_id(request.data.get("transactionId"))

        if tokenization is None or tokenization.status != Tokenization.Status.CREATED:
            return Response(
                {"code": "TOKEN_NOT_CREATED", "detail": "Crée d’abord le token de ce projet."},
                status=status.HTTP_409_CONFLICT,
            )
        if account_id != project.worker:
            return Response(
                {"code": "WORKER_ACCOUNT_MISMATCH", "detail": "Le compte destinataire ne correspond pas au worker du projet."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not re.fullmatch(r"\d+\.\d+\.\d+-\d+-\d+", transaction_id):
            return Response(
                {"code": "INVALID_TRANSACTION_ID", "detail": "L’identifiant de transaction Hedera est invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_units = WorkUnit.objects.filter(milestone__project=project)
        allocated_units = sum(
            work_units.filter(status=WorkUnit.Status.ALLOCATED).values_list("units", flat=True)
        )
        if allocated_units == 0:
            return Response(
                {"code": "NO_ALLOCATED_UNITS", "detail": "Aucune Work Unit allouée n’attend de transfert."},
                status=status.HTTP_409_CONFLICT,
            )

        transaction_url = (
            "https://testnet.mirrornode.hedera.com/api/v1/transactions/"
            f"{transaction_id}"
        )
        try:
            with urlopen(transaction_url, timeout=15) as response:
                transaction_data = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception("Could not verify transfer transaction %s", transaction_id)
            transaction_data = None

        transaction_record = next(
            iter((transaction_data or {}).get("transactions", [])), None
        )
        transfers = (transaction_record or {}).get("token_transfers", [])
        worker_received = sum(
            int(item.get("amount", 0))
            for item in transfers
            if item.get("token_id") == tokenization.token_id
            and item.get("account") == project.worker
        )
        treasury_sent = sum(
            int(item.get("amount", 0))
            for item in transfers
            if item.get("token_id") == tokenization.token_id
            and item.get("account") == os.getenv("HEDERA_ACCOUNT_ID", "").strip()
        )
        transaction_succeeded = bool(
            transaction_record
            and transaction_record.get("result") == "SUCCESS"
            and worker_received == allocated_units
            and treasury_sent == -allocated_units
        )
        if not transaction_succeeded:
            return Response(
                {
                    "code": "TRANSFER_NOT_CONFIRMED",
                    "detail": "Le transfert signé n’est pas encore confirmé sur Hedera Testnet.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        worker_balance = ProjectTokenView._read_token_balance(
            tokenization.token_id, project.worker
        )
        released_units = sum(
            work_units.filter(status=WorkUnit.Status.RELEASED).values_list("units", flat=True)
        )
        if worker_balance is None:
            return Response(
                {"code": "MIRROR_NODE_UNAVAILABLE", "detail": "Impossible de vérifier le transfert sur Mirror Node."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if worker_balance < released_units + allocated_units:
            return Response(
                {
                    "code": "TRANSFER_NOT_CONFIRMED",
                    "detail": "Le transfert HTS n’est pas encore visible sur Mirror Node.",
                    "expectedWorkerBalance": released_units + allocated_units,
                    "workerBalance": worker_balance,
                },
                status=status.HTTP_409_CONFLICT,
            )

        work_units.filter(status=WorkUnit.Status.ALLOCATED).update(
            status=WorkUnit.Status.RELEASED
        )
        return Response(
            {
                "projectId": project.project_id,
                "accountId": project.worker,
                "tokenId": tokenization.token_id,
                "releasedUnits": allocated_units,
                "workerHtsBalance": worker_balance,
                "workUnits": MilestoneSerializer(project.milestones.all(), many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class ProjectWorkUnitAllocationView(APIView):
    """Record the project's planned allocation before its HTS transfer is signed."""

    def post(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        tokenization = Tokenization.objects.filter(project=project).first()
        account_id = str(request.data.get("accountId") or "").strip()

        if tokenization is None or tokenization.status != Tokenization.Status.CREATED:
            return Response(
                {
                    "code": "TOKEN_NOT_CREATED",
                    "detail": "Crée d’abord le token de ce projet.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9]{5})?", account_id):
            return Response(
                {
                    "code": "INVALID_HEDERA_ACCOUNT_ID",
                    "detail": "L’identifiant du compte Hedera est invalide.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if account_id != project.worker:
            return Response(
                {
                    "code": "WORKER_ACCOUNT_MISMATCH",
                    "detail": "Connecte le compte worker enregistré sur le projet.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        query = urlencode({"token.id": tokenization.token_id, "limit": 1})
        url = (
            "https://testnet.mirrornode.hedera.com/api/v1/accounts/"
            f"{account_id}/tokens?{query}"
        )
        try:
            with urlopen(url, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception(
                "Could not verify token association before allocating project %s",
                project.project_id,
            )
            return Response(
                {
                    "code": "MIRROR_NODE_UNAVAILABLE",
                    "detail": "Impossible de vérifier l’association sur Hedera pour le moment.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not any(
            item.get("token_id") == tokenization.token_id
            for item in data.get("tokens", [])
        ):
            return Response(
                {
                    "code": "TOKEN_NOT_ASSOCIATED",
                    "detail": "Associe d’abord le compte worker au token.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        work_units = WorkUnit.objects.filter(milestone__project=project)
        if not work_units.exists():
            return Response(
                {
                    "code": "WORK_UNITS_NOT_DEFINED",
                    "detail": "Définis les milestones et Work Units avant l’allocation.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        total_work_units = sum(work_units.values_list("units", flat=True))
        if total_work_units != project.total_units:
            return Response(
                {
                    "code": "WORK_UNIT_UNITS_MISMATCH",
                    "detail": "Le total des Work Units doit correspondre à totalUnits.",
                    "expectedTotalUnits": project.total_units,
                    "receivedUnits": total_work_units,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        work_units.filter(status=WorkUnit.Status.PLANNED).update(
            status=WorkUnit.Status.ALLOCATED
        )
        allocated_units = sum(
            work_units.filter(status=WorkUnit.Status.ALLOCATED).values_list(
                "units", flat=True
            )
        )
        return Response(
            {
                "projectId": project.project_id,
                "accountId": account_id,
                "tokenId": tokenization.token_id,
                "allocatedUnits": allocated_units,
                "workUnits": MilestoneSerializer(
                    project.milestones.all(), many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class HederaTransactionsView(APIView):
    def get(self, request, project_id):
        project = get_object_or_404(Project, project_id=project_id)
        tokenization = Tokenization.objects.filter(project=project).first()

        if tokenization is None or not tokenization.transaction_id:
            return Response(
                {
                    "projectId": project.project_id,
                    "transactions": [],
                },
                status=status.HTTP_200_OK,
            )

        account_id = os.getenv("HEDERA_ACCOUNT_ID")
        if not account_id:
            return Response(
                {
                    "code": "HEDERA_ACCOUNT_ID_MISSING",
                    "detail": (
                        "HEDERA_ACCOUNT_ID est absent de la configuration."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        transaction_id = normalize_transaction_id(
            tokenization.transaction_id
        )
        seen = {}
        accounts = {account_id, project.worker, project.client}
        try:
            for account in accounts:
                if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9]{5})?", account):
                    continue
                query = urlencode({"account.id": account, "limit": 100, "order": "desc"})
                url = f"https://testnet.mirrornode.hedera.com/api/v1/transactions?{query}"
                with urlopen(url, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8"))
                for item in data.get("transactions", []):
                    tx_id = item.get("transaction_id")
                    token_matches = any(
                        transfer.get("token_id") == tokenization.token_id
                        for transfer in item.get("token_transfers", [])
                    )
                    worker_association = (
                        account == project.worker
                        and item.get("name") == "TOKENASSOCIATE"
                    )
                    if tx_id and (
                        tx_id == transaction_id
                        or token_matches
                        or worker_association
                    ):
                        seen[tx_id] = item
        except Exception:
            logger.exception("Could not retrieve Hedera transactions for %s", project.project_id)
            return Response(
                {"code": "MIRROR_NODE_UNAVAILABLE", "detail": "Impossible de lire l’historique Hedera pour le moment."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if transaction_id not in seen:
            seen[transaction_id] = {
                "transaction_id": transaction_id,
                "name": "TOKENCREATE",
                "result": "UNKNOWN",
                "consensus_timestamp": None,
            }
        transactions = [
            {
                "transactionId": tx_id,
                "type": item.get("name"),
                "status": item.get("result"),
                "timestamp": item.get("consensus_timestamp"),
                "hashscanUrl": f"https://hashscan.io/testnet/transaction/{tx_id}",
            }
            for tx_id, item in sorted(
                seen.items(),
                key=lambda entry: entry[1].get("consensus_timestamp") or "",
                reverse=True,
            )
        ]

        return Response(
            {
                "projectId": project.project_id,
                "transactions": transactions,
            },
            status=status.HTTP_200_OK,
        )
