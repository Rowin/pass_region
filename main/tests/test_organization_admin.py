from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from main.forms import OrganizationAdminForm
from main.models import APICredentialRecord, Organization, StaffUser


class OrganizationAdminTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            organization_name="Test organization",
            hello_asso_client_id="stored-client-marker",
            hello_asso_client_secret="stored-secret-marker",
            hello_asso_organization_slug="test-organization",
            copay_amount_per_candidate="10.00",
            copay_message="Payment",
            email="organization@example.test",
        )
        self.user = get_user_model().objects.create_superuser(
            username="organization-admin", password="test-password"
        )
        self.client.force_login(self.user)
        self.url = reverse(
            "admin:main_organization_change", args=[self.organization.pk]
        )
        self.data = {
            "organization_name": "Test organization",
            "hello_asso_organization_slug": "test-organization",
            "copay_amount_per_candidate": "10.00",
            "copay_message": "Payment",
            "email": "organization@example.test",
        }

    def test_existing_credentials_are_absent_from_admin_html(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "stored-client-marker")
        self.assertNotContains(response, "stored-secret-marker")
        self.assertNotIn(
            "hello_asso_client_id", response.context["adminform"].form.fields
        )
        self.assertNotIn(
            "hello_asso_client_secret", response.context["adminform"].form.fields
        )

    def test_blank_replacements_preserve_credentials(self):
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 302)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.hello_asso_client_id, "stored-client-marker")
        self.assertEqual(
            self.organization.hello_asso_client_secret, "stored-secret-marker"
        )

    def test_replacement_invalidates_tokens_and_audits_without_values(self):
        APICredentialRecord.objects.create(
            organization=self.organization,
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            access_token_expires_at=timezone.now(),
        )
        response = self.client.post(
            self.url,
            {
                **self.data,
                "new_client_id": "new-client",
                "new_client_secret": "new-secret",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.hello_asso_client_id, "new-client")
        self.assertEqual(self.organization.hello_asso_client_secret, "new-secret")
        self.assertFalse(
            APICredentialRecord.objects.filter(organization=self.organization).exists()
        )
        entry = admin.models.LogEntry.objects.get(object_id=str(self.organization.pk))
        self.assertEqual(entry.user_id, self.user.pk)
        self.assertNotIn("new-client", entry.change_message)
        self.assertNotIn("new-secret", entry.change_message)

    def test_invalid_submission_does_not_echo_replacement_values(self):
        response = self.client.post(
            self.url,
            {
                **self.data,
                "organization_name": "",
                "new_client_id": "submitted-client-marker",
                "new_client_secret": "submitted-secret-marker",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "submitted-client-marker")
        self.assertNotContains(response, "submitted-secret-marker")

    def test_credentials_must_be_replaced_together(self):
        form = OrganizationAdminForm(
            data={**self.data, "new_client_id": "only-client"},
            instance=self.organization,
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_creation_requires_credentials(self):
        form = OrganizationAdminForm(data=self.data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_staff_cannot_access_another_organization(self):
        self.user.is_superuser = False
        self.user.save()
        StaffUser.objects.create(user=self.user)
        with patch.object(get_user_model(), "has_perm", return_value=True):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 302)
            response = self.client.post(self.url, self.data)
            self.assertEqual(response.status_code, 302)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.hello_asso_client_id, "stored-client-marker")
