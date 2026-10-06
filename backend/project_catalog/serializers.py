from rest_framework import serializers

from .models import Milestone, Project, WorkAgreement, WorkUnit


class ProjectSerializer(serializers.ModelSerializer):
    projectId = serializers.CharField(source="project_id", read_only=True)
    totalUnits = serializers.IntegerField(source="total_units", min_value=1)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Project
        fields = [
            "projectId",
            "title",
            "description",
            "client",
            "worker",
            "currency",
            "totalUnits",
            "status",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = [
            "projectId",
            "status",
            "createdAt",
            "updatedAt",
        ]


class WorkAgreementSerializer(serializers.ModelSerializer):
    version = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WorkAgreement
        fields = [
            "version",
            "value",
            "conditions",
            "deadline",
            "status",
            "createdAt",
        ]
        read_only_fields = ["version", "status", "createdAt"]


class WorkUnitSerializer(serializers.ModelSerializer):
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = WorkUnit
        fields = [
            "title",
            "description",
            "units",
            "status",
            "createdAt",
        ]
        read_only_fields = ["status", "createdAt"]


class MilestoneSerializer(serializers.ModelSerializer):
    milestoneId = serializers.SerializerMethodField()
    projectId = serializers.CharField(
        source="project.project_id",
        read_only=True,
    )
    workUnits = WorkUnitSerializer(
        source="work_units",
        many=True,
        required=False,
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Milestone
        fields = [
            "milestoneId",
            "projectId",
            "title",
            "description",
            "units",
            "deadline",
            "status",
            "workUnits",
            "createdAt",
            "updatedAt",
        ]
        read_only_fields = [
            "milestoneId",
            "projectId",
            "status",
            "createdAt",
            "updatedAt",
        ]

    def get_milestoneId(self, obj):
        return f"M-{obj.pk:03d}"

    def validate(self, attrs):
        work_units = attrs.get("work_units")

        if work_units is not None:
            work_unit_total = sum(item["units"] for item in work_units)
            if work_unit_total != attrs["units"]:
                raise serializers.ValidationError(
                    {
                        "workUnits": (
                            "The sum of Work Unit units must equal "
                            "the milestone units."
                        )
                    }
                )

        return attrs

    def create(self, validated_data):
        work_units_data = validated_data.pop("work_units", None)
        milestone = Milestone.objects.create(**validated_data)

        if work_units_data is None:
            work_units_data = [
                {
                    "title": milestone.title,
                    "description": milestone.description,
                    "units": milestone.units,
                }
            ]

        for work_unit_data in work_units_data:
            WorkUnit.objects.create(
                milestone=milestone,
                **work_unit_data,
            )

        return milestone
