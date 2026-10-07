import io
import logging
from io import StringIO
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import FreelancerProfile, ProjectReference


User = get_user_model()


@override_settings(DEBUG=True, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FreelancerAuthenticationTests(TestCase):
    def csrf_headers(self, client=None):
        client = client or self.client
        response = client.get("/api/auth/csrf")
        self.assertEqual(response.status_code, 200)
        return {"HTTP_X_CSRFTOKEN": response.data["csrf_token"]}

    def signup(self, email="freelancer@example.test", password="Safe-Local-Password-908!", **extra):
        body = {"display_name": "Test Freelancer", "email": email, "password": password, **extra}
        response = self.client.post("/api/auth/signup", body, format="json", **self.csrf_headers())
        return response

    def test_signup_creates_freelancer_profile_and_starts_session(self):
        response = self.signup(github_login="octo-test")
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="freelancer@example.test")
        profile = user.freelancer_profile
        self.assertEqual(profile.role, FreelancerProfile.Role.FREELANCER)
        self.assertEqual(profile.github_login, "octo-test")
        self.assertNotEqual(user.password, "Safe-Local-Password-908!")
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertNotIn("password", response.data["user"])

    def test_signup_rejects_invalid_password_and_privilege_fields(self):
        weak = self.signup(password="123")
        self.assertEqual(weak.status_code, 400)
        privilege_escalation = self.signup(email="other@example.test", role="ADMIN")
        self.assertEqual(privilege_escalation.status_code, 400)
        self.assertFalse(User.objects.filter(email="other@example.test").exists())

    def test_signup_requires_csrf_token(self):
        strict_client = APIClient(enforce_csrf_checks=True)
        payload = {"display_name": "CSRF User", "email": "csrf@example.test", "password": "Safe-Local-Password-908!"}
        rejected = strict_client.post("/api/auth/signup", payload, format="json")
        self.assertEqual(rejected.status_code, 403)
        token_response = strict_client.get("/api/auth/csrf")
        accepted = strict_client.post(
            "/api/auth/signup", payload, format="json",
            HTTP_X_CSRFTOKEN=token_response.data["csrf_token"],
        )
        self.assertEqual(accepted.status_code, 201, accepted.data)

    def test_logout_requires_csrf_token_for_authenticated_session(self):
        user = User.objects.create_user(username="csrf-logout@example.test", email="csrf-logout@example.test", password="Safe-Local-Password-908!")
        FreelancerProfile.objects.create(user=user, display_name="CSRF Logout")
        strict_client = APIClient(enforce_csrf_checks=True)
        strict_client.force_login(user)
        rejected = strict_client.post("/api/auth/logout", {}, format="json")
        self.assertEqual(rejected.status_code, 403)
        token_response = strict_client.get("/api/auth/csrf")
        accepted = strict_client.post(
            "/api/auth/logout", {}, format="json",
            HTTP_X_CSRFTOKEN=token_response.data["csrf_token"],
        )
        self.assertEqual(accepted.status_code, 200)

    def test_duplicate_email_is_case_insensitive(self):
        self.assertEqual(self.signup().status_code, 201)
        duplicate = self.signup(email="FREELANCER@EXAMPLE.TEST")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(User.objects.filter(email__iexact="freelancer@example.test").count(), 1)

    def test_login_and_logout_use_session(self):
        self.signup()
        self.client.post("/api/auth/logout", {}, format="json", **self.csrf_headers())
        self.assertEqual(self.client.get("/api/auth/me").status_code, 403)
        response = self.client.post(
            "/api/auth/login",
            {"email": "FREELANCER@example.test", "password": "Safe-Local-Password-908!"},
            format="json",
            **self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        logout_response = self.client.post("/api/auth/logout", {}, format="json", **self.csrf_headers())
        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 403)

    def test_invalid_login_and_anonymous_private_endpoints_are_rejected(self):
        response = self.client.post(
            "/api/auth/login",
            {"email": "missing@example.test", "password": "not-the-password"},
            format="json",
            **self.csrf_headers(),
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("INVALID_CREDENTIALS", response.data["error"])
        projects = self.client.get("/api/freelancer/projects")
        self.assertIn(projects.status_code, {401, 403})
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        self.assertEqual(self.client.get("/api/settlements").status_code, 401)

    def test_expired_session_is_unauthenticated(self):
        user = User.objects.create_user(
            username="expired@example.test", email="expired@example.test", password="Safe-Local-Password-908!"
        )
        FreelancerProfile.objects.create(user=user, display_name="Expired Test")
        self.client.force_login(user)
        session = self.client.session
        session.set_expiry(-1)
        session.save()
        self.client.cookies["sessionid"] = session.session_key
        self.assertEqual(self.client.get("/api/auth/me").status_code, 403)

    def test_projects_are_isolated_between_freelancer_accounts(self):
        owner = User.objects.create_user(username="owner@example.test", email="owner@example.test", password="x")
        other = User.objects.create_user(username="other@example.test", email="other@example.test", password="x")
        FreelancerProfile.objects.create(user=owner, display_name="Owner")
        FreelancerProfile.objects.create(user=other, display_name="Other")
        project = ProjectReference.objects.create(
            external_id="OWNER-ONLY-001", title="Private project", created_by=owner.email,
            provenance=ProjectReference.Provenance.MANUAL, owner=owner,
        )
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/projects").status_code, 401)
        self.assertEqual(anonymous.get(f"/api/projects/{project.external_id}/dashboard").status_code, 404)
        client = APIClient()
        client.force_authenticate(owner)
        self.assertEqual(client.get("/api/freelancer/projects").data["count"], 1)
        self.assertEqual(client.get(f"/api/projects/{project.external_id}/activity").status_code, 200)
        client.force_authenticate(other)
        self.assertEqual(client.get("/api/freelancer/projects").data["count"], 0)
        self.assertEqual(client.get(f"/api/freelancer/projects/{project.external_id}").status_code, 404)
        self.assertEqual(client.get(f"/api/projects/{project.external_id}/dashboard").status_code, 404)
        self.assertEqual(client.get(f"/api/projects/{project.external_id}/activity").status_code, 404)

    def test_freelancer_can_create_owned_project_without_operator_secret(self):
        user = User.objects.create_user(username="creator@example.test", email="creator@example.test", password="x")
        FreelancerProfile.objects.create(user=user, display_name="Creator")
        client = APIClient()
        client.force_authenticate(user)
        response = client.post("/api/freelancer/projects", {
            "external_id": "CREATOR-001", "title": "My private project", "description": "Owned by this account",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        project = ProjectReference.objects.get(external_id="CREATOR-001")
        self.assertEqual(project.owner_id, user.pk)
        self.assertFalse(project.is_demo_only)

    def test_password_is_not_returned_or_written_to_application_logs(self):
        stream = io.StringIO()
        logger = logging.getLogger("command_center.auth_views")
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)
        try:
            response = self.signup()
        finally:
            logger.removeHandler(handler)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("Safe-Local-Password-908!", response.content.decode("utf-8"))
        self.assertNotIn("Safe-Local-Password-908!", stream.getvalue())


@override_settings(DEBUG=False)
class DemoFreelancerCommandSafetyTests(TestCase):
    def test_demo_account_command_refuses_non_debug_environment(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_demo_freelancers")
        self.assertEqual(User.objects.count(), 0)


@override_settings(DEBUG=True)
class DemoFreelancerCommandTests(TestCase):
    def test_command_creates_idempotent_demo_only_accounts_and_one_time_passwords(self):
        from django.core.management import call_command

        output = StringIO()
        call_command("seed_demo_freelancers", stdout=output)
        self.assertEqual(User.objects.count(), 4)
        self.assertEqual(FreelancerProfile.objects.filter(is_demo_only=True, role=FreelancerProfile.Role.FREELANCER).count(), 3)
        self.assertEqual(FreelancerProfile.objects.filter(is_demo_only=True, role=FreelancerProfile.Role.CLIENT).count(), 1)
        self.assertIn("Mot de passe initial (affiché une seule fois)", output.getvalue())
        for user in User.objects.all():
            self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
            self.assertTrue(user.freelancer_profile.is_demo_only)
        call_command("seed_demo_freelancers", stdout=StringIO())
        self.assertEqual(User.objects.count(), 4)
