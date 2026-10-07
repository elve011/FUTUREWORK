"""Session-based freelancer authentication for the standalone Dev 4 app."""

from types import SimpleNamespace

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authentication import SessionAuthentication

from .models import FreelancerProfile


User = get_user_model()


class SignupSerializer(serializers.Serializer):
    display_name = serializers.CharField(min_length=2, max_length=120, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(min_length=12, max_length=128, trim_whitespace=False, write_only=True)
    github_login = serializers.CharField(max_length=39, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({str(key): "Champ non autorisé." for key in sorted(unknown)})
        attrs["email"] = attrs["email"].strip().casefold()
        attrs["github_login"] = attrs.get("github_login", "").strip().lstrip("@")
        if User.objects.filter(email__iexact=attrs["email"]).exists() or User.objects.filter(username__iexact=attrs["email"]).exists():
            raise serializers.ValidationError({"email": "Cette adresse e-mail est déjà utilisée."})
        candidate = SimpleNamespace(username=attrs["email"], email=attrs["email"], first_name=attrs["display_name"])
        try:
            validate_password(attrs["password"], user=candidate)
        except ValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from None
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({str(key): "Champ non autorisé." for key in sorted(unknown)})
        attrs["email"] = attrs["email"].strip().casefold()
        return attrs


def public_user(user):
    profile = getattr(user, "freelancer_profile", None)
    return {
        "id": user.pk,
        "email": user.email,
        "display_name": profile.display_name if profile else user.get_full_name() or user.email,
        "role": profile.role if profile else FreelancerProfile.Role.ADMIN if user.is_staff else FreelancerProfile.Role.FREELANCER,
        "status": profile.status if profile else FreelancerProfile.Status.ACTIVE,
        "github_login": profile.github_login if profile else "",
        "demo_only": profile.is_demo_only if profile else False,
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
    return Response({"csrf_token": get_token(request)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@csrf_protect
def signup(request):
    serializer = SignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=values["email"], email=values["email"],
                password=values["password"], first_name=values["display_name"],
            )
            FreelancerProfile.objects.create(
                user=user,
                display_name=values["display_name"],
                role=FreelancerProfile.Role.FREELANCER,
                github_login=values.get("github_login", ""),
            )
    except IntegrityError:
        return Response({"error": "EMAIL_ALREADY_REGISTERED", "detail": "Cette adresse e-mail est déjà utilisée."}, status=status.HTTP_409_CONFLICT)
    login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response({"user": public_user(user)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
@csrf_protect
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(request._request, username=serializer.validated_data["email"], password=serializer.validated_data["password"])
    profile = getattr(user, "freelancer_profile", None) if user else None
    if not user or not user.is_active or (profile and profile.status != FreelancerProfile.Status.ACTIVE):
        return Response({"error": "INVALID_CREDENTIALS", "detail": "E-mail ou mot de passe invalide."}, status=status.HTTP_401_UNAUTHORIZED)
    login(request._request, user)
    return Response({"user": public_user(user)})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request._request)
    return Response({"status": "logged_out"})


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def me(request):
    profile = getattr(request.user, "freelancer_profile", None)
    if profile and profile.status != FreelancerProfile.Status.ACTIVE:
        return Response({"error": "ACCOUNT_SUSPENDED"}, status=status.HTTP_403_FORBIDDEN)
    return Response({"user": public_user(request.user), "server_time": timezone.now()})
