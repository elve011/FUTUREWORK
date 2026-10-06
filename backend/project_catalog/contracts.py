from .models import Project, Tokenization, WorkAgreement


def build_project_contract(project):
    agreement = (
        project.agreements.filter(status=WorkAgreement.Status.ACTIVE)
        .order_by("-version")
        .first()
    )

    if agreement is None:
        raise ValueError("The project must have an active Work Agreement.")

    tokenization = Tokenization.objects.filter(project=project).first()

    milestones = [
        {
            "milestoneId": f"M-{milestone.pk:03d}",
            "title": milestone.title,
            "units": milestone.units,
            "deadline": milestone.deadline.isoformat(),
        }
        for milestone in project.milestones.all()
    ]

    return {
        "contractVersion": "1.0",
        "projectId": project.project_id,
        "agreementId": f"AGR-{agreement.pk:03d}",
        "client": project.client,
        "worker": project.worker,
        "totalUnits": project.total_units,
        "currency": project.currency,
        "status": project.status,
        "milestones": milestones,
        "tokenId": (
            tokenization.token_id
            if tokenization and tokenization.token_id
            else None
        ),
    }
