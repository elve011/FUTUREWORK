from datetime import date, timedelta

from django.utils.timezone import localdate


PHASE_TITLES = [
    "Planning",
    "Execution",
    "Review and delivery",
]


def _get_today(today=None):
    """Return an injectable date for predictable deadline calculations."""
    return today or localdate()


def analyzeAgreement(agreement, today=None):
    """Extract and validate the agreement data required by the planner."""
    project = agreement.project
    current_date = _get_today(today)

    if not agreement.conditions or not agreement.conditions.strip():
        raise ValueError("Agreement conditions are required.")

    if agreement.deadline is None:
        raise ValueError("Agreement deadline is required.")

    if agreement.deadline < current_date:
        raise ValueError("The agreement deadline has already passed.")

    if project.total_units <= 0:
        raise ValueError("totalUnits must be greater than zero.")

    return {
        "projectId": project.project_id,
        "agreementVersion": agreement.version,
        "conditions": agreement.conditions,
        "agreementValue": str(agreement.value),
        "deadline": agreement.deadline.isoformat(),
        "totalUnits": project.total_units,
    }


def _split_units(total_units, part_count):
    """Split units evenly and preserve the exact total."""
    if total_units <= 0:
        return []

    if part_count <= 0:
        raise ValueError("part_count must be greater than zero.")

    base_units, remainder = divmod(total_units, part_count)
    return [
        base_units + (1 if index < remainder else 0)
        for index in range(part_count)
    ]


def calculateWorkUnits(milestone_title, milestone_units):
    """Propose up to three work-unit groups for a milestone."""
    if milestone_units <= 0:
        return []

    part_count = min(3, milestone_units)
    unit_counts = _split_units(milestone_units, part_count)

    return [
        {
            "title": f"{milestone_title} — Work package {index + 1}",
            "units": units,
        }
        for index, units in enumerate(unit_counts)
    ]


def createMilestones(agreement, today=None):
    """Create an editable milestone proposal with an exact unit total."""
    agreement_data = analyzeAgreement(agreement, today=today)
    project = agreement.project
    total_units = project.total_units
    current_date = _get_today(today)
    days_until_deadline = (agreement.deadline - current_date).days

    phase_count = min(len(PHASE_TITLES), total_units)
    unit_counts = _split_units(total_units, phase_count)
    milestones = []

    for index, title in enumerate(PHASE_TITLES[:phase_count]):
        if index == phase_count - 1:
            milestone_deadline = agreement.deadline
        else:
            day_offset = round(
                days_until_deadline * (index + 1) / phase_count
            )
            milestone_deadline = current_date + timedelta(days=day_offset)

        units = unit_counts[index]

        milestones.append(
            {
                "title": title,
                "description": (
                    f"Planner Agent proposal for the {title.lower()} phase."
                ),
                "units": units,
                "deadline": milestone_deadline.isoformat(),
                "workUnits": calculateWorkUnits(title, units),
            }
        )

    return {
        **agreement_data,
        "milestones": milestones,
    }


def checkDeadlines(project, today=None):
    """Return unfinished milestones whose deadlines have passed."""
    current_date = _get_today(today)

    overdue_milestones = (
        project.milestones.filter(deadline__lt=current_date)
        .exclude(status="COMPLETED")
        .order_by("deadline", "pk")
    )

    return [
        {
            "title": milestone.title,
            "deadline": milestone.deadline.isoformat(),
            "status": milestone.status,
        }
        for milestone in overdue_milestones
    ]


def updateProjectPlan(agreement, today=None):
    """Regenerate the editable proposal after an agreement or plan change."""
    return createMilestones(agreement, today=today)