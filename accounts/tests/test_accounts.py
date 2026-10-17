from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.roles import ALL_ROLES, ROLE_OFFICER, get_role, user_district
from locations.models import District


class RoleTests(TestCase):
    def test_groups_exist_after_migrate(self):
        self.assertEqual(set(Group.objects.filter(name__in=ALL_ROLES).values_list("name", flat=True)), set(ALL_ROLES))

    def test_profile_created_automatically(self):
        user = User.objects.create_user("newbie", password="x12345678!")
        self.assertTrue(hasattr(user, "profile"))
        self.assertIsNone(get_role(user))

    def test_role_from_group_and_superuser(self):
        user = User.objects.create_user("o", password="x12345678!")
        user.groups.add(Group.objects.get(name=ROLE_OFFICER))
        self.assertEqual(get_role(user), "officer")
        root = User.objects.create_superuser("root", password="x12345678!")
        self.assertEqual(get_role(root), "admin")

    def test_user_district(self):
        user = User.objects.create_user("d", password="x12345678!")
        user.profile.district = District.objects.get(name="Huye")
        user.profile.save()
        self.assertEqual(user_district(user).name, "Huye")


class ProfileTests(TestCase):
    def test_phone_validation(self):
        self.assertTrue(ProfileForm(data={"job_title": "", "phone": "0788123456"}).is_valid())
        self.assertFalse(ProfileForm(data={"job_title": "", "phone": "123"}).is_valid())

    def test_profile_page_requires_login_and_saves(self):
        self.assertEqual(self.client.get(reverse("profile")).status_code, 302)
        User.objects.create_user("p", password="Test@12345")
        self.client.login(username="p", password="Test@12345")
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)
        response = self.client.post(reverse("profile"), {"job_title": "Analyst", "phone": "0788123456"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(username="p").profile.job_title, "Analyst")
