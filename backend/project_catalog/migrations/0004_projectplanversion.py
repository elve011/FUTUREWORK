from django.db import migrations, models
import django.db.models.deletion


def backfill_current_plan(apps, schema_editor):
    Project = apps.get_model("project_catalog", "Project")
    Agreement = apps.get_model("project_catalog", "WorkAgreement")
    PlanVersion = apps.get_model("project_catalog", "ProjectPlanVersion")
    for project in Project.objects.all().iterator():
        milestones = []
        for milestone in project.milestones.all():
            milestones.append({
                "title": milestone.title,
                "description": milestone.description,
                "units": milestone.units,
                "deadline": milestone.deadline.isoformat(),
                "status": milestone.status,
                "workUnits": [
                    {
                        "title": unit.title,
                        "description": unit.description,
                        "units": unit.units,
                        "status": unit.status,
                    }
                    for unit in milestone.work_units.all()
                ],
            })
        if milestones:
            agreement = Agreement.objects.filter(
                project_id=project.pk, status="ACTIVE"
            ).order_by("-version").first()
            PlanVersion.objects.create(
                project_id=project.pk,
                version=1,
                agreement_version=agreement.version if agreement else 1,
                snapshot=milestones,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("project_catalog", "0003_alter_project_currency"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectPlanVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.PositiveIntegerField()),
                ("agreement_version", models.PositiveIntegerField()),
                ("snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plan_versions", to="project_catalog.project")),
            ],
            options={"ordering": ["-version"]},
        ),
        migrations.AddConstraint(
            model_name="projectplanversion",
            constraint=models.UniqueConstraint(fields=("project", "version"), name="unique_plan_version_per_project"),
        ),
        migrations.RunPython(backfill_current_plan, migrations.RunPython.noop),
    ]
