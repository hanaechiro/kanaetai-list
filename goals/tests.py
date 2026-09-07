import base64
import inspect
import importlib
import json
import os
import re
import tempfile
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.db import connection
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)

from .models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    GoalImage,
    GoalLink,
    IdeaMemo,
    Inquiry,
    LikeList,
    ListComment,
    MonthlyGoal,
    Profile,
    SavedItem,
    SavedList,
    TodayTask,
    UserActivity,
    TogetherRequest,
    WantToTry,
    WeeklyGoal,
    YearPlan,
    YearlyGoal,
)
from .context_processors import notification_counts
from .middleware import UserActivityMiddleware
from . import forms as goals_forms
from . import views


TEST_STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


@override_settings(STORAGES=TEST_STORAGES)
class ErrorPageTests(TestCase):
    @override_settings(DEBUG=False)
    def test_missing_page_uses_custom_404_template(self):
        response = self.client.get("/missing-page/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "ページが見つかりません", status_code=404)
        self.assertNotContains(response, "Traceback", status_code=404)
        self.assertNotContains(response, "DEBUG", status_code=404)
        self.assertNotContains(response, "Local vars", status_code=404)

    @override_settings(DEBUG=False)
    def test_permission_denied_uses_custom_403_template(self):
        User = get_user_model()
        owner = User.objects.create_user(username="owner", email="owner@example.com", password="password12345")
        viewer = User.objects.create_user(username="viewer", email="viewer@example.com", password="password12345")
        private_list = YearPlan.objects.create(user=owner, year=2026, list_title="Private list", is_public=False)

        self.client.force_login(viewer)
        response = self.client.get(reverse("goals:my_list_detail", args=[private_list.pk]))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, "このページを表示する権限がありません", status_code=403)
        self.assertNotContains(response, "forbidden", status_code=403)

    @override_settings(DEBUG=False)
    def test_server_error_uses_custom_500_template(self):
        rendered = render_to_string("500.html")

        self.assertIn("一時的なエラーが発生しました", rendered)
        self.assertNotIn("Traceback", rendered)
        self.assertNotIn("DATABASE_URL", rendered)
        self.assertNotIn("SECRET_KEY", rendered)
        self.assertNotIn("API_KEY", rendered)


@override_settings(STORAGES=TEST_STORAGES)
class VisibilityPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password12345",
        )
        self.follower = User.objects.create_user(
            username="follower",
            email="follower@example.com",
            password="password12345",
        )
        self.stranger = User.objects.create_user(
            username="stranger",
            email="stranger@example.com",
            password="password12345",
        )
        self.owner.profile.display_name = "Private Owner"
        self.owner.profile.is_private = True
        self.owner.profile.save(update_fields=["display_name", "is_private"])

        self.public_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="Private account public list",
            target_count=10,
            is_public=True,
        )
        self.public_goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.public_plan,
            title="Visible only to approved followers",
            item_is_public=True,
        )
        self.private_goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.public_plan,
            title="Private item title",
            item_is_public=False,
        )

    def login(self, user):
        self.client.force_login(user)

    def test_private_profile_hides_details_from_non_follower(self):
        self.login(self.stranger)

        response = self.client.get(reverse("goals:profile_detail", args=[self.owner.username]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_view_profile_details"])
        self.assertIsNone(response.context["profile_stats"])
        self.assertNotContains(response, self.public_plan.list_title)
        self.assertNotContains(response, self.public_goal.title)

    def test_pending_follow_request_does_not_grant_private_profile_access(self):
        FollowRequest.objects.create(requester=self.stranger, target=self.owner)
        self.login(self.stranger)

        response = self.client.get(reverse("goals:public_list_detail", args=[self.public_plan.pk]))

        self.assertEqual(response.status_code, 404)

    def test_approved_follower_can_view_private_account_public_list(self):
        Follow.objects.create(follower=self.follower, following=self.owner)
        self.login(self.follower)

        response = self.client.get(reverse("goals:public_list_detail", args=[self.public_plan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.public_plan.list_title)
        self.assertContains(response, self.public_goal.title)
        self.assertNotContains(response, self.private_goal.title)

    def test_saved_list_is_hidden_after_follow_access_is_lost(self):
        SavedList.objects.create(user=self.stranger, my_list=self.public_plan)
        Follow.objects.create(follower=self.stranger, following=self.owner).delete()
        self.login(self.stranger)

        response = self.client.get(reverse("goals:saved_list_page"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.public_plan.list_title)

    def test_saved_item_is_hidden_after_follow_access_is_lost(self):
        SavedItem.objects.create(user=self.stranger, item=self.public_goal)
        self.login(self.stranger)

        response = self.client.get(reverse("goals:saved_item_page"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.public_goal.title)

    def test_stranger_cannot_save_like_comment_request_or_copy_private_account_content(self):
        self.login(self.stranger)

        blocked_posts = [
            reverse("goals:toggle_saved_list", args=[self.public_plan.pk]),
            reverse("goals:toggle_like_list", args=[self.public_plan.pk]),
            reverse("goals:add_list_comment", args=[self.public_plan.pk]),
            reverse("goals:request_together", args=[self.public_goal.pk]),
            reverse("goals:add_public_goal_to_idea", args=[self.public_goal.pk]),
        ]
        for url in blocked_posts:
            with self.subTest(url=url):
                response = self.client.post(url, {"body": "hello"})
                self.assertEqual(response.status_code, 403)

        self.assertFalse(SavedList.objects.filter(user=self.stranger, my_list=self.public_plan).exists())
        self.assertFalse(LikeList.objects.filter(user=self.stranger, my_list=self.public_plan).exists())
        self.assertFalse(ListComment.objects.filter(user=self.stranger, my_list=self.public_plan).exists())
        self.assertFalse(TogetherRequest.objects.filter(requester=self.stranger, list_item=self.public_goal).exists())
        self.assertFalse(IdeaMemo.objects.filter(user=self.stranger, title=self.public_goal.title).exists())

    def test_private_item_cannot_be_accessed_or_saved_directly(self):
        self.login(self.stranger)

        detail_response = self.client.get(reverse("goals:public_goal_detail", args=[self.private_goal.pk]))
        save_response = self.client.post(reverse("goals:toggle_saved_item", args=[self.private_goal.pk]))

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(save_response.status_code, 404)
        self.assertFalse(SavedItem.objects.filter(user=self.stranger, item=self.private_goal).exists())


@override_settings(STORAGES=TEST_STORAGES)
class NotificationBehaviorTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="password12345")
        self.follower = User.objects.create_user(username="follower", email="follower@example.com", password="password12345")
        self.owner.profile.is_private = False
        self.owner.profile.save(update_fields=["is_private"])

    def test_public_follow_is_shown_as_notification_and_marks_read_after_view(self):
        self.client.force_login(self.follower)
        response = self.client.post(reverse("goals:toggle_follow", args=[self.owner.username]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Follow.objects.filter(follower=self.follower, following=self.owner).exists())

        self.client.force_login(self.owner)
        self.owner.profile.last_notification_seen = timezone.now() - timedelta(days=1)
        self.owner.profile.save(update_fields=["last_notification_seen"])

        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.context["unread_notification_count"], 1)

        notifications_response = self.client.get(reverse("goals:notifications"))
        self.assertContains(notifications_response, "さんがあなたをフォローしました")
        # Tabs represent unread counts at page-open timing (pre-read).
        tab_counts = {tab.get("key"): tab.get("count", 0) for tab in notifications_response.context.get("notification_tabs", [])}
        self.assertEqual(tab_counts.get("follow"), 1)
        self.assertEqual(tab_counts.get("all"), 1)
        self.assertEqual(tab_counts.get("collaboration"), 0)
        self.assertEqual(tab_counts.get("like"), 0)
        self.assertEqual(tab_counts.get("save"), 0)

        # Context-processor unread badge is post-read on this response.
        self.assertEqual(notifications_response.context.get("unread_notification_count"), 0)
        self.owner.profile.refresh_from_db()
        self.assertIsNotNone(self.owner.profile.last_notification_seen)

        refreshed_profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(refreshed_profile_response.context["unread_notification_count"], 0)

    def test_notification_counts_uses_one_sql_roundtrip_for_counts(self):
        self.owner.profile.last_notification_seen = timezone.now() - timedelta(days=1)
        self.owner.profile.save(update_fields=["last_notification_seen"])

        other = get_user_model().objects.create_user(username="other", email="other@example.com", password="password12345")
        plan = YearPlan.objects.create(user=self.owner, year=2026, list_title="Owner plan", is_public=True)
        other_plan = YearPlan.objects.create(user=other, year=2026, list_title="Other plan", is_public=True)
        FollowRequest.objects.create(requester=self.follower, target=self.owner)
        CollaborationInvite.objects.create(list=other_plan, inviter=other, invitee=self.owner)
        Follow.objects.create(follower=self.follower, following=self.owner)
        LikeList.objects.create(user=self.follower, my_list=plan)
        SavedList.objects.create(user=self.follower, my_list=plan)

        request = RequestFactory().get("/")
        request.user = self.owner

        with CaptureQueriesContext(connection) as context:
            result = notification_counts(request)

        self.assertEqual(result["unread_notification_count"], 5)
        self.assertLessEqual(len(context), 2)


@override_settings(STORAGES=TEST_STORAGES)
class UserActivityMiddlewareTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="active", email="active@example.com", password="password12345")
        self.factory = RequestFactory()
        self.middleware = UserActivityMiddleware(lambda request: HttpResponse("ok"))

    def test_recent_activity_does_not_write_every_request(self):
        original_seen_at = timezone.now() - timedelta(seconds=10)
        activity = UserActivity.objects.create(
            user=self.user,
            date=timezone.localdate(),
            first_seen_at=original_seen_at,
            last_seen_at=original_seen_at,
            request_count=3,
        )
        request = self.factory.get("/profile/")
        request.user = self.user

        with CaptureQueriesContext(connection) as context:
            response = self.middleware(request)

        activity.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(context), 1)
        self.assertEqual(activity.request_count, 3)
        self.assertEqual(activity.last_seen_at, original_seen_at)

    def test_stale_activity_updates_after_interval(self):
        original_seen_at = timezone.now() - timedelta(minutes=5)
        activity = UserActivity.objects.create(
            user=self.user,
            date=timezone.localdate(),
            first_seen_at=original_seen_at,
            last_seen_at=original_seen_at,
            request_count=3,
        )
        request = self.factory.post("/follow/")
        request.user = self.user

        with CaptureQueriesContext(connection) as context:
            response = self.middleware(request)

        activity.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(context), 2)
        self.assertEqual(activity.request_count, 4)
        self.assertGreater(activity.last_seen_at, original_seen_at)


@override_settings(STORAGES=TEST_STORAGES)
class UsernameUniquenessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def signup_payload(self, username, email="new@example.com"):
        return {
            "display_name": "New User",
            "username": username,
            "email": email,
            "password1": "strong-password-123",
            "password2": "strong-password-123",
        }

    def profile_payload(self, username):
        return {
            "display_name": "Profile User",
            "username": username,
            "bio": "",
            "avatar_crop_data": "",
        }

    def test_signup_rejects_uppercase_variant_when_lowercase_exists(self):
        self.User.objects.create_user(username="hana", email="hana@example.com", password="password12345")

        response = self.client.post(reverse("goals:signup"), self.signup_payload("Hana", "hana2@example.com"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])
        self.assertFalse(self.User.objects.filter(username="Hana").exists())

    def test_signup_rejects_lowercase_variant_when_uppercase_exists(self):
        self.User.objects.create_user(username="Hana", email="hana@example.com", password="password12345")

        response = self.client.post(reverse("goals:signup"), self.signup_payload("hana", "hana2@example.com"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])
        self.assertFalse(self.User.objects.filter(username="hana").exists())

    def test_signup_allows_different_username(self):
        self.User.objects.create_user(username="hana", email="hana@example.com", password="password12345")

        response = self.client.post(reverse("goals:signup"), self.signup_payload("mika", "mika@example.com"))

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.assertTrue(self.User.objects.filter(username="mika").exists())

    def test_signup_integrity_error_returns_form_error(self):
        with patch("goals.views.SignUpForm.save", side_effect=IntegrityError):
            response = self.client.post(reverse("goals:signup"), self.signup_payload("mika", "mika@example.com"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])

    def test_profile_edit_rejects_case_insensitive_duplicate(self):
        self.User.objects.create_user(username="hana", email="hana@example.com", password="password12345")
        user = self.User.objects.create_user(username="mika", email="mika@example.com", password="password12345")
        self.client.force_login(user)

        response = self.client.post(reverse("goals:edit_profile"), self.profile_payload("Hana"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])
        user.refresh_from_db()
        self.assertEqual(user.username, "mika")

    def test_profile_edit_allows_own_existing_username(self):
        user = self.User.objects.create_user(username="hana", email="hana@example.com", password="password12345")
        self.client.force_login(user)

        response = self.client.post(reverse("goals:edit_profile"), self.profile_payload("hana"))

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.username, "hana")

    def test_profile_edit_allows_unique_username_change(self):
        user = self.User.objects.create_user(username="mika", email="mika@example.com", password="password12345")
        self.client.force_login(user)

        response = self.client.post(reverse("goals:edit_profile"), self.profile_payload("mika2"))

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        user.refresh_from_db()
        self.assertEqual(user.username, "mika2")

    def test_profile_edit_integrity_error_returns_form_error(self):
        user = self.User.objects.create_user(username="mika", email="mika@example.com", password="password12345")
        self.client.force_login(user)

        with patch.object(self.User, "save", side_effect=IntegrityError):
            response = self.client.post(reverse("goals:edit_profile"), self.profile_payload("mika2"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["username"])
        user.refresh_from_db()
        self.assertEqual(user.username, "mika")

    def test_database_constraint_rejects_case_insensitive_duplicate(self):
        self.User.objects.create_user(username="hana", email="hana@example.com", password="password12345")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.User.objects.create_user(username="Hana", email="hana2@example.com", password="password12345")


class DatabaseSslRequireSettingTests(TestCase):
    def database_ssl_require(self, env, *, debug):
        with patch.dict(os.environ, env, clear=False):
            if "DATABASE_SSL_REQUIRE" not in env:
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("DATABASE_SSL_REQUIRE", None)
                    settings_module = importlib.import_module("goals_app.settings")
                    return settings_module.env_database_ssl_require(debug)
            settings_module = importlib.import_module("goals_app.settings")
            return settings_module.env_database_ssl_require(debug)

    def test_database_ssl_require_defaults_to_false_when_debug_true(self):
        self.assertFalse(self.database_ssl_require({}, debug=True))

    def test_database_ssl_require_defaults_to_true_when_debug_false(self):
        self.assertTrue(self.database_ssl_require({}, debug=False))

    def test_database_ssl_require_accepts_explicit_true(self):
        self.assertTrue(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "true"}, debug=True))
        self.assertTrue(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "1"}, debug=True))
        self.assertTrue(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "yes"}, debug=True))
        self.assertTrue(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "on"}, debug=True))

    def test_database_ssl_require_accepts_explicit_false(self):
        self.assertFalse(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "false"}, debug=False))
        self.assertFalse(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "0"}, debug=False))
        self.assertFalse(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "no"}, debug=False))
        self.assertFalse(self.database_ssl_require({"DATABASE_SSL_REQUIRE": "off"}, debug=False))


class ImageUploadSafetyTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory(dir=os.getcwd(), ignore_cleanup_errors=True)
        self.override = override_settings(
            MEDIA_ROOT=self.media_root.name,
            STORAGES=TEST_STORAGES,
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_root.cleanup)

        User = get_user_model()
        self.user = User.objects.create_user(
            username="imageuser",
            email="imageuser@example.com",
            password="password12345",
        )
        self.client.force_login(self.user)
        self.year_plan = YearPlan.objects.create(
            user=self.user,
            year=2026,
            list_title="Image list",
            target_count=10,
            is_public=False,
        )
        self.goal = YearlyGoal.objects.create(
            user=self.user,
            year_plan=self.year_plan,
            title="Image item",
            item_is_public=True,
        )

    def make_image_upload(
        self,
        name="upload.jpg",
        *,
        image_format="JPEG",
        size=(640, 480),
        color=(180, 80, 120),
        include_exif=False,
        content_type=None,
    ):
        buffer = BytesIO()
        mode = "RGBA" if image_format == "PNG" else "RGB"
        image = Image.new(mode, size, color)
        save_kwargs = {}
        if include_exif and image_format == "JPEG":
            exif = Image.Exif()
            exif[0x0132] = "2026:08:29 12:00:00"
            save_kwargs["exif"] = exif
        save_format = "HEIF" if image_format in {"HEIC", "HEIF"} else image_format
        image.save(buffer, format=save_format, **save_kwargs)
        content_type = content_type or {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "HEIC": "image/heic",
            "HEIF": "image/heif",
        }[image_format]
        return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)

    def oversized_upload(self, name, size):
        small_image = self.make_image_upload(name=name).read()
        return SimpleUploadedFile(name, small_image + (b"x" * (size - len(small_image))), content_type="image/jpeg")

    def assert_saved_image_is_openable(self, field_file, *, max_edge):
        self.assertTrue(field_file.name)
        self.assertTrue(os.path.exists(field_file.path))
        with Image.open(field_file.path) as image:
            image.verify()
        with Image.open(field_file.path) as image:
            self.assertLessEqual(max(image.size), max_edge)

    def assert_saved_image_has_no_exif(self, field_file):
        with Image.open(field_file.path) as image:
            self.assertFalse(image.getexif())

    def assert_saved_image_format(self, field_file, expected_format):
        with Image.open(field_file.path) as image:
            self.assertEqual(image.format, expected_format)

    def profile_post_data(self, **overrides):
        data = {
            "display_name": "Image User",
            "username": self.user.username,
            "bio": "",
            "avatar_crop_data": "",
        }
        data.update(overrides)
        return data

    def test_profile_jpeg_over_2mb_under_15mb_can_be_saved(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(
                icon=self.oversized_upload("large-profile.jpg", 2 * 1024 * 1024 + 1),
            ),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)

    def test_profile_image_over_15mb_is_rejected(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(icon=self.oversized_upload("huge.jpg", 15 * 1024 * 1024 + 1)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "icon",
            "プロフィール画像は15MB以下の画像を選択してください。",
        )
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.icon)

    def test_goal_image_over_5mb_under_20mb_can_be_saved(self):
        response = self.client.post(
            reverse("goals:add_goal_image", args=[self.goal.pk]),
            {"caption": "ok", "image": self.oversized_upload("large-goal.jpg", 5 * 1024 * 1024 + 1)},
        )

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        goal_image = GoalImage.objects.get(goal=self.goal)
        self.assert_saved_image_is_openable(goal_image.image, max_edge=2000)

    def test_goal_image_over_20mb_is_rejected(self):
        response = self.client.post(
            reverse("goals:add_goal_image", args=[self.goal.pk]),
            {"caption": "huge", "image": self.oversized_upload("huge.jpg", 20 * 1024 * 1024 + 1)},
        )

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(GoalImage.objects.filter(goal=self.goal).exists())

    def test_profile_image_is_resized_and_exif_is_removed(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(
                icon=self.make_image_upload(size=(2400, 1800), include_exif=True),
            ),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)
        self.assert_saved_image_has_no_exif(self.user.profile.icon)

    def test_goal_image_is_resized_and_exif_is_removed(self):
        response = self.client.post(
            reverse("goals:add_goal_image", args=[self.goal.pk]),
            {
                "caption": "exif",
                "image": self.make_image_upload(name="goal.jpg", size=(3200, 2400), include_exif=True),
            },
        )

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        goal_image = GoalImage.objects.get(goal=self.goal)
        self.assert_saved_image_is_openable(goal_image.image, max_edge=2000)
        self.assert_saved_image_has_no_exif(goal_image.image)

    def test_heic_profile_image_is_converted_to_jpeg(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(
                icon=self.make_image_upload(
                    name="iphone.heic",
                    image_format="HEIC",
                    size=(1600, 2400),
                    include_exif=True,
                ),
            ),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.icon.name.endswith(".jpg"))
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)
        self.assert_saved_image_format(self.user.profile.icon, "JPEG")
        self.assert_saved_image_has_no_exif(self.user.profile.icon)
        with Image.open(self.user.profile.icon.path) as image:
            self.assertLess(image.width, image.height)

    def test_heic_profile_image_without_extension_or_image_content_type_is_accepted(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(
                icon=self.make_image_upload(
                    name="iphone-photo",
                    image_format="HEIC",
                    size=(1600, 2400),
                    content_type="application/octet-stream",
                ),
            ),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.icon.name.endswith(".jpg"))
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)
        self.assert_saved_image_format(self.user.profile.icon, "JPEG")

    def test_heic_goal_image_is_converted_to_jpeg(self):
        response = self.client.post(
            reverse("goals:add_goal_image", args=[self.goal.pk]),
            {
                "caption": "heic",
                "image": self.make_image_upload(
                    name="iphone.heic",
                    image_format="HEIC",
                    size=(1800, 2600),
                    include_exif=True,
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        goal_image = GoalImage.objects.get(goal=self.goal)
        self.assertTrue(goal_image.image.name.endswith(".jpg"))
        self.assert_saved_image_is_openable(goal_image.image, max_edge=2000)
        self.assert_saved_image_format(goal_image.image, "JPEG")
        self.assert_saved_image_has_no_exif(goal_image.image)
        with Image.open(goal_image.image.path) as image:
            self.assertLess(image.width, image.height)

    def test_svg_is_rejected(self):
        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(
                icon=SimpleUploadedFile(
                    "icon.svg",
                    b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                    content_type="image/svg+xml",
                )
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["icon"])
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.icon)

    def test_non_image_file_is_rejected(self):
        response = self.client.post(
            reverse("goals:add_goal_image", args=[self.goal.pk]),
            {
                "caption": "not image",
                "image": SimpleUploadedFile("note.jpg", b"not an image", content_type="image/jpeg"),
            },
        )

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(GoalImage.objects.filter(goal=self.goal).exists())

    def test_profile_crop_data_is_processed_and_saved(self):
        upload = self.make_image_upload(size=(1800, 1200))
        encoded = base64.b64encode(upload.read()).decode("ascii")

        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(avatar_crop_data=f"data:image/jpeg;base64,{encoded}"),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)

    def test_goal_image_delete_removes_database_record_and_file(self):
        upload = self.make_image_upload(name="delete-me.png", image_format="PNG")
        goal_image = GoalImage.objects.create(goal=self.goal, image=upload)
        image_path = goal_image.image.path

        response = self.client.post(reverse("goals:delete_goal_image", args=[goal_image.pk]))

        self.assertRedirects(
            response,
            reverse("goals:yearly_goal_edit", args=[self.goal.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(GoalImage.objects.filter(pk=goal_image.pk).exists())
        self.assertFalse(os.path.exists(image_path))

    def test_profile_image_replacement_removes_old_file(self):
        profile = Profile.objects.get(user=self.user)
        profile.icon = self.make_image_upload(name="old.jpg")
        profile.save(update_fields=["icon"])
        old_path = profile.icon.path

        response = self.client.post(
            reverse("goals:edit_profile"),
            self.profile_post_data(icon=self.make_image_upload(name="new.jpg", color=(40, 120, 220))),
        )

        self.assertRedirects(response, reverse("goals:my_profile"), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.assert_saved_image_is_openable(self.user.profile.icon, max_edge=1200)
        self.assertFalse(os.path.exists(old_path))


@override_settings(STORAGES=TEST_STORAGES)
class DiscoverUserSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        # public user with display name and username
        self.user_yuki = User.objects.create_user(username="yuki_25", email="yuki@example.com", password="password12345")
        self.user_yuki.profile.display_name = "Yuki"
        self.user_yuki.profile.is_private = False
        self.user_yuki.profile.save(update_fields=["display_name", "is_private"])

        # another public user
        self.user_test = User.objects.create_user(username="testuser2", email="test2@example.com", password="password12345")
        self.user_test.profile.display_name = "testuser2"
        self.user_test.profile.is_private = False
        self.user_test.profile.save(update_fields=["display_name", "is_private"])

        # private user should not appear
        self.user_private = User.objects.create_user(username="private1", email="priv@example.com", password="password12345")
        self.user_private.profile.display_name = "PrivateUser"
        self.user_private.profile.is_private = True
        self.user_private.profile.save(update_fields=["display_name", "is_private"])

    def get_usernames_from_response(self, resp):
        return [row['user'].username for row in resp.context.get('user_results', [])]

    def test_search_by_display_name_full_and_partial_matches(self):
        resp = self.client.get(reverse('goals:public_goal_list'), {'q': 'Yuki'})
        self.assertEqual(resp.status_code, 200)
        names = self.get_usernames_from_response(resp)
        self.assertIn('yuki_25', names)

        resp2 = self.client.get(reverse('goals:public_goal_list'), {'q': 'yuk'})
        self.assertEqual(resp2.status_code, 200)
        names2 = self.get_usernames_from_response(resp2)
        self.assertIn('yuki_25', names2)

    def test_search_by_username_full_and_partial_matches(self):
        resp = self.client.get(reverse('goals:public_goal_list'), {'q': 'yuki_25'})
        self.assertEqual(resp.status_code, 200)
        names = self.get_usernames_from_response(resp)
        self.assertIn('yuki_25', names)

        resp2 = self.client.get(reverse('goals:public_goal_list'), {'q': 'yuki_2'})
        self.assertEqual(resp2.status_code, 200)
        names2 = self.get_usernames_from_response(resp2)
        self.assertIn('yuki_25', names2)

    def test_search_is_case_insensitive(self):
        resp = self.client.get(reverse('goals:public_goal_list'), {'q': 'YUKI'})
        self.assertEqual(resp.status_code, 200)
        names = self.get_usernames_from_response(resp)
        self.assertIn('yuki_25', names)

    def test_private_user_not_in_results(self):
        resp = self.client.get(reverse('goals:public_goal_list'), {'q': 'PrivateUser'})
        self.assertEqual(resp.status_code, 200)
        names = self.get_usernames_from_response(resp)
        # Non-public accounts should now appear in search results
        self.assertIn('private1', names)

    def test_private_profile_protected_and_follow_request(self):
        # Anonymous viewer should not be able to view private profile details
        resp = self.client.get(reverse('goals:profile_detail', args=[self.user_private.username]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context.get('can_view_profile_details'))
        self.assertIsNone(resp.context.get('profile_stats'))

        # Authenticated user can send follow request to private account
        follower = get_user_model().objects.create_user(username='follower1', email='f1@example.com', password='pw')
        self.client.force_login(follower)
        post_resp = self.client.post(reverse('goals:toggle_follow', args=[self.user_private.username]), follow=True)
        # After follow request, a FollowRequest should exist
        from .models import FollowRequest
        self.assertTrue(FollowRequest.objects.filter(requester=follower, target=self.user_private).exists())


@override_settings(STORAGES=TEST_STORAGES)
class YearlyGoalNoteTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(username="owner", email="o@example.com", password="pw")
        self.client.force_login(self.user)
        self.year_plan = YearPlan.objects.create(user=self.user, year=2026, list_title="My Plan", target_count=10, is_public=True)

    def test_create_goal_with_memo_and_display(self):
        url = reverse('goals:add_my_list_goal_inline', args=[self.year_plan.pk])
        data = {'title': '行きたい場所', 'description': '宮古島のきれいな海でシュノーケリングをしたい！', 'category': 'travel', 'item_is_public': 'on'}
        resp = self.client.post(url, data)
        # After creation, a goal with description should exist
        goal = YearlyGoal.objects.filter(title='行きたい場所').first()
        self.assertIsNotNone(goal)
        self.assertEqual(goal.description, '宮古島のきれいな海でシュノーケリングをしたい！')

        # Detail page should show the memo text
        detail_resp = self.client.get(reverse('goals:yearly_goal_detail', args=[goal.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, '宮古島のきれいな海でシュノーケリングをしたい！')

    def test_edit_goal_memo_and_display(self):
        goal = YearlyGoal.objects.create(user=self.user, year_plan=self.year_plan, title='編集対象', description='最初のメモ', category='travel')
        url = reverse('goals:edit_my_list_goal_inline', args=[goal.pk])
        data = {'title': '編集対象', 'description': '更新されたメモの内容', 'category': 'travel', 'item_is_public': 'on'}
        resp = self.client.post(url, data)
        goal.refresh_from_db()
        self.assertEqual(goal.description, '更新されたメモの内容')

        detail_resp = self.client.get(reverse('goals:yearly_goal_detail', args=[goal.pk]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, '更新されたメモの内容')

    def test_empty_memo_shows_no_memo_message(self):
        goal = YearlyGoal.objects.create(user=self.user, year_plan=self.year_plan, title='空メモ', description='', category='other')
        resp = self.client.get(reverse('goals:yearly_goal_detail', args=[goal.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'メモはありません。')


@override_settings(STORAGES=TEST_STORAGES)
class CollaboratorSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.current = User.objects.create_user(username="current", email="current@example.com", password="pw")
        self.chiroro = User.objects.create_user(username="chiroro", email="chiro@example.com", password="pw")
        self.chiroro.profile.display_name = "ちろろ"
        self.chiroro.profile.save(update_fields=["display_name"])
        self.private = User.objects.create_user(username="privateuser", email="p@example.com", password="pw")
        self.private.profile.is_private = True
        self.private.profile.save(update_fields=["is_private"])
        # current follows chiroro
        from .models import Follow
        Follow.objects.create(follower=self.current, following=self.chiroro)

    def test_collaborator_options_include_users_and_exclude_self(self):
        self.client.force_login(self.current)
        resp = self.client.get(reverse('goals:my_list_add'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        # chiroro is followed and should be present in the initial <select> (server-rendered)
        self.assertIn('data-username="chiroro"', content)
        # display name should be present
        self.assertIn('ちろろ', content)
        # private user is not followed; initial select should NOT contain their data-username
        self.assertNotIn('data-username="privateuser"', content)
        # current user should not be present
        self.assertNotIn('data-username="current"', content)

    def test_search_data_includes_all_users_and_is_case_insensitive(self):
        # Server-provided search data (JSON) should include non-followed and private users
        self.client.force_login(self.current)
        resp = self.client.get(reverse('goals:my_list_add'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        match = re.search(
            r'<script id="all-collaborators-data" type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(match)

        all_users = json.loads(match.group(1))
        usernames = [u.get("username", "") for u in all_users]
        self.assertIn("privateuser", usernames)
        self.assertIn("chiroro", usernames)

        # Client-side search normalizes input and candidate text to lowercase.
        def matches(query):
            q = query.lower()
            return [
                u for u in all_users
                if q in f'{u.get("display_name", "")} {u.get("username", "")}'.lower()
            ]

        self.assertIn("privateuser", [u.get("username") for u in matches("PRIVATE")])
        self.assertIn("chiroro", [u.get("username") for u in matches("CHIR")])

    def test_page_handles_users_without_profile(self):
        # Create a user and remove their Profile if it exists to simulate legacy/missing profile
        User = get_user_model()
        missing = User.objects.create_user(username="noprof", email="noprof@example.com", password="pw")
        # Ensure Profile (if auto-created) is removed
        from .models import Profile
        Profile.objects.filter(user=missing).delete()

        self.client.force_login(self.current)
        resp = self.client.get(reverse('goals:my_list_add'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        # Page should render without raising; the username may be present as fallback
        self.assertIn('noprof', content)

    def test_create_collaborative_yearplan_with_selected_user(self):
        # Create a collaborative YearPlan selecting chiroro as a collaborator
        self.client.force_login(self.current)
        url = reverse('goals:my_list_add')
        data = {
            'list_title': 'Team Plan',
            'target_count': 10,
            'is_collaborative': 'on',
            'collaborators': [str(self.chiroro.pk)],
        }
        resp = self.client.post(url, data, follow=True)
        self.assertEqual(resp.status_code, 200)
        # YearPlan should be created and a CollaborationInvite should be created for chiroro
        from .models import YearPlan, CollaborationInvite
        yp = YearPlan.objects.filter(user=self.current, list_title='Team Plan').first()
        self.assertIsNotNone(yp)
        # collaborator should NOT be auto-added until they accept
        self.assertNotIn(self.chiroro, list(yp.collaborators.all()))
        invite = CollaborationInvite.objects.filter(list=yp, invitee=self.chiroro, inviter=self.current).first()
        self.assertIsNotNone(invite)

    def test_invite_acceptance_allows_private_list_view(self):
        # Owner creates a private collaborative list and invites chiroro
        from .models import YearPlan, CollaborationInvite
        yp = YearPlan.objects.create(user=self.current, year=2026, list_title='Private Team', is_public=False)
        CollaborationInvite.objects.create(list=yp, inviter=self.current, invitee=self.chiroro, status=CollaborationInvite.STATUS_PENDING)

        # chiroro should have the invite and see it in notifications
        self.client.force_login(self.chiroro)
        resp = self.client.get(reverse('goals:notifications'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('共同リストに招待されています', content)

        # Accept the invite
        invite = CollaborationInvite.objects.filter(list=yp, invitee=self.chiroro).first()
        resp2 = self.client.post(reverse('goals:respond_collaboration_invite', args=[invite.pk, 'accepted']), follow=True)
        self.assertEqual(resp2.status_code, 200)

        # After acceptance, chiroro should be able to view the private list
        resp3 = self.client.get(reverse('goals:my_list_detail', args=[yp.pk]))
        self.assertEqual(resp3.status_code, 200)

    def test_non_collaborator_cannot_view_private_list(self):
        # Create private list and ensure a third user cannot access
        User = get_user_model()
        third = User.objects.create_user(username='third', email='t@example.com', password='pw')
        from .models import YearPlan
        yp = YearPlan.objects.create(user=self.current, year=2026, list_title='Private Team 2', is_public=False)
        self.client.force_login(third)
        resp = self.client.get(reverse('goals:my_list_detail', args=[yp.pk]))
        self.assertEqual(resp.status_code, 403)


@override_settings(STORAGES=TEST_STORAGES)
class PendingCollaborationInviteMembersTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="password12345")
        self.owner.profile.display_name = "オーナー"
        self.owner.profile.save(update_fields=["display_name"])
        self.invitee = User.objects.create_user(username="invitee", email="invitee@example.com", password="password12345")
        self.invitee.profile.display_name = "招待太郎"
        self.invitee.profile.save(update_fields=["display_name"])
        self.member = User.objects.create_user(username="member", email="member@example.com", password="password12345")
        self.member.profile.display_name = "正式メンバー"
        self.member.profile.save(update_fields=["display_name"])
        Follow.objects.create(follower=self.owner, following=self.invitee)
        self.year_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="共同リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.year_plan.collaborators.add(self.member)

    def test_create_invite_is_pending_and_not_added_as_collaborator(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("goals:my_list_add"),
            {
                "list_title": "新しい共同リスト",
                "target_count": 10,
                "is_collaborative": "on",
                "collaborators": [str(self.invitee.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        plan = YearPlan.objects.get(user=self.owner, list_title="新しい共同リスト")
        invite = CollaborationInvite.objects.get(list=plan, invitee=self.invitee)
        self.assertEqual(invite.status, CollaborationInvite.STATUS_PENDING)
        self.assertNotIn(self.invitee, list(plan.collaborators.all()))

    def test_owner_list_detail_shows_pending_invite_badge(self):
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=self.invitee,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "招待太郎")
        self.assertContains(response, "招待中")
        self.assertContains(response, "正式メンバー")
        self.assertContains(response, "オーナー")

    def test_accepted_member_is_not_shown_as_pending(self):
        self.year_plan.collaborators.add(self.invitee)
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=self.invitee,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("招待太郎", content)
        self.assertEqual(content.count("招待太郎"), 1)
        invitee_index = content.find("招待太郎")
        nearby = content[invitee_index:invitee_index + 400]
        self.assertIn("member", nearby)
        self.assertNotIn("招待中", nearby)

    def test_declined_invite_is_not_shown_in_members(self):
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=self.invitee,
            status=CollaborationInvite.STATUS_DECLINED,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "招待太郎")
        self.assertNotContains(response, "招待中")
        self.assertContains(response, "正式メンバー")

    def test_pending_invitee_cannot_view_or_edit_private_list(self):
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=self.invitee,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.client.force_login(self.invitee)
        detail = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(detail.status_code, 403)
        edit_page = self.client.get(reverse("goals:my_list_edit", args=[self.year_plan.pk]))
        self.assertEqual(edit_page.status_code, 404)
        add_item = self.client.post(
            reverse("goals:add_my_list_goal_inline", args=[self.year_plan.pk]),
            {"title": "無断追加", "category": "other"},
        )
        self.assertEqual(add_item.status_code, 403)
        self.assertFalse(YearlyGoal.objects.filter(year_plan=self.year_plan, title="無断追加").exists())

    def test_edit_list_creates_pending_invite_without_adding_collaborator(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("goals:my_list_edit", args=[self.year_plan.pk]),
            {
                "list_title": self.year_plan.list_title,
                "target_count": self.year_plan.target_count,
                "is_collaborative": "on",
                "collaborators": [str(self.invitee.pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.year_plan.refresh_from_db()
        self.assertNotIn(self.member, list(self.year_plan.collaborators.all()))
        self.assertNotIn(self.invitee, list(self.year_plan.collaborators.all()))
        invite = CollaborationInvite.objects.get(list=self.year_plan, invitee=self.invitee)
        self.assertEqual(invite.status, CollaborationInvite.STATUS_PENDING)
        detail = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertContains(detail, "招待太郎")
        self.assertContains(detail, "招待中")

    def test_owner_public_detail_shows_pending_invite_badge(self):
        self.year_plan.is_public = True
        self.year_plan.save(update_fields=["is_public"])
        YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.year_plan,
            title="公開項目",
            item_is_public=True,
        )
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=self.invitee,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:public_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "招待太郎")
        self.assertContains(response, "招待中")

    def test_pending_invitee_without_profile_uses_username_fallback(self):
        from .models import Profile
        no_profile = get_user_model().objects.create_user(username="noprof", email="noprof@example.com", password="password12345")
        Profile.objects.filter(user=no_profile).delete()
        CollaborationInvite.objects.create(
            list=self.year_plan,
            inviter=self.owner,
            invitee=no_profile,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:my_list_detail", args=[self.year_plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "noprof")


@override_settings(STORAGES=TEST_STORAGES)
class LikeSavedOwnListVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner2", email="owner2@example.com", password="password12345")
        self.other = User.objects.create_user(username="other2", email="other2@example.com", password="password12345")
        self.private_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="owner private",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.public_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="owner public",
            target_count=10,
            is_public=True,
        )
        self.collab_plan = YearPlan.objects.create(
            user=self.other,
            year=2026,
            list_title="collab private",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.collab_plan.collaborators.add(self.owner)
        self.client.force_login(self.owner)

    def test_like_own_list_appears_and_disappears_on_liked_page(self):
        self.client.post(reverse("goals:toggle_like_list", args=[self.private_plan.pk]))
        self.assertTrue(LikeList.objects.filter(user=self.owner, my_list=self.private_plan).exists())

        liked_page = self.client.get(reverse("goals:liked_list_page"))
        self.assertEqual(liked_page.status_code, 200)
        self.assertContains(liked_page, "owner private")

        self.client.post(reverse("goals:toggle_like_list", args=[self.private_plan.pk]))
        self.assertFalse(LikeList.objects.filter(user=self.owner, my_list=self.private_plan).exists())
        liked_page_after = self.client.get(reverse("goals:liked_list_page"))
        self.assertEqual(liked_page_after.status_code, 200)
        self.assertNotContains(liked_page_after, "owner private")

    def test_save_own_private_list_appears_and_disappears_on_saved_page(self):
        self.client.post(reverse("goals:toggle_saved_list", args=[self.private_plan.pk]))
        self.assertTrue(SavedList.objects.filter(user=self.owner, my_list=self.private_plan).exists())

        saved_page = self.client.get(reverse("goals:saved_list_page"))
        self.assertEqual(saved_page.status_code, 200)
        self.assertContains(saved_page, "owner private")

        self.client.post(reverse("goals:toggle_saved_list", args=[self.private_plan.pk]))
        self.assertFalse(SavedList.objects.filter(user=self.owner, my_list=self.private_plan).exists())
        saved_page_after = self.client.get(reverse("goals:saved_list_page"))
        self.assertEqual(saved_page_after.status_code, 200)
        self.assertNotContains(saved_page_after, "owner private")

    def test_collaborator_private_list_is_visible_in_reaction_pages(self):
        self.client.post(reverse("goals:toggle_like_list", args=[self.collab_plan.pk]))
        self.client.post(reverse("goals:toggle_saved_list", args=[self.collab_plan.pk]))

        liked_page = self.client.get(reverse("goals:liked_list_page"))
        saved_page = self.client.get(reverse("goals:saved_list_page"))
        self.assertContains(liked_page, "collab private")
        self.assertContains(saved_page, "collab private")


@override_settings(STORAGES=TEST_STORAGES)
class PublicListPrivatePlaceholderTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner3", email="owner3@example.com", password="password12345")
        self.viewer = User.objects.create_user(username="viewer3", email="viewer3@example.com", password="password12345")
        self.owner.profile.is_private = False
        self.owner.profile.save(update_fields=["is_private"])
        self.plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="公開混在リスト",
            target_count=10,
            is_public=True,
        )
        self.public_goal_1 = YearlyGoal.objects.create(user=self.owner, year_plan=self.plan, title="公開A", item_is_public=True)
        self.public_goal_2 = YearlyGoal.objects.create(user=self.owner, year_plan=self.plan, title="公開B", item_is_public=True)
        self.public_goal_3 = YearlyGoal.objects.create(user=self.owner, year_plan=self.plan, title="公開C", item_is_public=True)
        self.private_goal_1 = YearlyGoal.objects.create(user=self.owner, year_plan=self.plan, title="秘密X", item_is_public=False)
        self.private_goal_2 = YearlyGoal.objects.create(user=self.owner, year_plan=self.plan, title="秘密Y", item_is_public=False)

    def test_public_view_shows_private_placeholders_and_hides_private_content(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("goals:public_list_detail", args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公開A")
        self.assertContains(response, "公開B")
        self.assertContains(response, "公開C")
        self.assertContains(response, "🔒 非公開の項目", count=2)
        self.assertContains(response, "登録 5件")
        self.assertNotContains(response, "秘密X")
        self.assertNotContains(response, "秘密Y")
        self.assertNotContains(response, reverse("goals:public_goal_detail", args=[self.private_goal_1.pk]))
        self.assertNotContains(response, reverse("goals:public_goal_detail", args=[self.private_goal_2.pk]))

    def test_owner_detail_still_shows_private_goal_content(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("goals:my_list_detail", args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "秘密X")
        self.assertContains(response, "秘密Y")
        self.assertContains(response, "登録 5件")


@override_settings(STORAGES=TEST_STORAGES)
class AcceptedCollaboratorPermissionsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner4", email="owner4@example.com", password="password12345")
        self.collaborator = User.objects.create_user(username="collab4", email="collab4@example.com", password="password12345")
        self.pending_user = User.objects.create_user(username="pending4", email="pending4@example.com", password="password12345")

        self.owned_plan = YearPlan.objects.create(
            user=self.collaborator,
            year=2026,
            list_title="自分のリスト",
            target_count=10,
            is_public=False,
        )
        self.shared_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="参加中の共同リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.pending_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="承認待ちの共同リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.shared_plan,
            title="オーナーが作った項目",
            category="other",
            item_is_public=True,
            added_by=self.owner,
        )
        self.invite = CollaborationInvite.objects.create(
            list=self.shared_plan,
            inviter=self.owner,
            invitee=self.collaborator,
            status=CollaborationInvite.STATUS_PENDING,
        )
        self.pending_invite = CollaborationInvite.objects.create(
            list=self.pending_plan,
            inviter=self.owner,
            invitee=self.collaborator,
            status=CollaborationInvite.STATUS_PENDING,
        )
        CollaborationInvite.objects.create(
            list=self.pending_plan,
            inviter=self.owner,
            invitee=self.pending_user,
            status=CollaborationInvite.STATUS_PENDING,
        )

    def accept_shared_invite(self):
        self.client.force_login(self.collaborator)
        response = self.client.post(reverse("goals:respond_collaboration_invite", args=[self.invite.pk, "accepted"]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.shared_plan.refresh_from_db()
        self.assertIn(self.collaborator, list(self.shared_plan.collaborators.all()))

    def test_pending_user_cannot_edit_and_is_not_counted(self):
        self.client.force_login(self.pending_user)
        detail = self.client.get(reverse("goals:my_list_detail", args=[self.pending_plan.pk]))
        self.assertEqual(detail.status_code, 403)
        add_item = self.client.post(reverse("goals:add_my_list_goal_inline", args=[self.pending_plan.pk]), {"title": "追加不可", "category": "other"})
        self.assertEqual(add_item.status_code, 403)
        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.context["profile_stats"]["list_count"], 0)
        self.assertNotContains(profile_response, "承認待ちの共同リスト")

    def test_accepted_collaborator_can_view_add_edit_delete_goal(self):
        self.accept_shared_invite()

        detail = self.client.get(reverse("goals:my_list_detail", args=[self.shared_plan.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "オーナーが作った項目")

        add_response = self.client.post(
            reverse("goals:add_my_list_goal_inline", args=[self.shared_plan.pk]),
            {"title": "共同追加", "category": "other", "item_is_public": "on"},
            follow=True,
        )
        self.assertEqual(add_response.status_code, 200)
        added_goal = YearlyGoal.objects.get(year_plan=self.shared_plan, title="共同追加")
        self.assertEqual(added_goal.added_by, self.collaborator)

        edit_response = self.client.post(
            reverse("goals:edit_my_list_goal_inline", args=[self.goal.pk]),
            {"title": "共同編集後", "category": "other", "item_is_public": "on", "description": "更新"},
            follow=True,
        )
        self.assertEqual(edit_response.status_code, 200)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.title, "共同編集後")
        self.assertEqual(self.goal.description, "更新")

        goal_detail = self.client.get(reverse("goals:yearly_goal_detail", args=[self.goal.pk]))
        self.assertEqual(goal_detail.status_code, 200)
        self.assertContains(goal_detail, "削除")

        delete_response = self.client.post(reverse("goals:yearly_goal_delete", args=[self.goal.pk]), follow=True)
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(YearlyGoal.objects.filter(pk=self.goal.pk).exists())

    def test_accepted_collaborative_list_is_listed_and_counted_once(self):
        self.accept_shared_invite()
        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertContains(profile_response, "自分のリスト")
        self.assertContains(profile_response, "参加中の共同リスト")
        self.assertNotContains(profile_response, "承認待ちの共同リスト")
        self.assertEqual(profile_response.context["profile_stats"]["list_count"], 2)
        self.assertEqual(len(profile_response.context["my_plans"]), 2)


@override_settings(STORAGES=TEST_STORAGES)
class CollaborativeListMembershipManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner5", email="owner5@example.com", password="password12345")
        self.collaborator = User.objects.create_user(username="collab5", email="collab5@example.com", password="password12345")
        self.other_collaborator = User.objects.create_user(username="collab6", email="collab6@example.com", password="password12345")
        self.pending_user = User.objects.create_user(username="pending5", email="pending5@example.com", password="password12345")

        self.shared_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="管理対象の共同リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.shared_plan.collaborators.add(self.collaborator, self.other_collaborator)

        self.goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.shared_plan,
            title="共同項目",
            category="other",
            item_is_public=True,
            added_by=self.owner,
        )

        CollaborationInvite.objects.create(
            list=self.shared_plan,
            inviter=self.owner,
            invitee=self.collaborator,
            status=CollaborationInvite.STATUS_ACCEPTED,
        )
        CollaborationInvite.objects.create(
            list=self.shared_plan,
            inviter=self.owner,
            invitee=self.other_collaborator,
            status=CollaborationInvite.STATUS_ACCEPTED,
        )
        self.pending_invite = CollaborationInvite.objects.create(
            list=self.shared_plan,
            inviter=self.owner,
            invitee=self.pending_user,
            status=CollaborationInvite.STATUS_PENDING,
        )

    def test_owner_can_delete_collaborative_list_and_it_disappears_for_collaborator(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("goals:my_list_delete", args=[self.shared_plan.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(YearPlan.objects.filter(pk=self.shared_plan.pk).exists())

        self.client.force_login(self.collaborator)
        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.context["profile_stats"]["list_count"], 0)
        self.assertNotContains(profile_response, "管理対象の共同リスト")

    def test_collaborator_cannot_delete_list_or_remove_others_or_cancel_pending_invite(self):
        self.client.force_login(self.collaborator)

        delete_response = self.client.post(reverse("goals:my_list_delete", args=[self.shared_plan.pk]))
        self.assertEqual(delete_response.status_code, 404)
        self.assertTrue(YearPlan.objects.filter(pk=self.shared_plan.pk).exists())

        remove_response = self.client.post(
            reverse("goals:my_list_remove_collaborator", args=[self.shared_plan.pk, self.other_collaborator.pk])
        )
        self.assertEqual(remove_response.status_code, 403)
        self.assertTrue(self.shared_plan.collaborators.filter(pk=self.other_collaborator.pk).exists())

        cancel_response = self.client.post(
            reverse("goals:my_list_cancel_invite", args=[self.shared_plan.pk, self.pending_invite.pk])
        )
        self.assertEqual(cancel_response.status_code, 403)
        self.assertTrue(CollaborationInvite.objects.filter(pk=self.pending_invite.pk).exists())

    def test_accepted_collaborator_can_leave_and_loses_private_access_and_count(self):
        self.client.force_login(self.collaborator)
        leave_response = self.client.post(reverse("goals:my_list_leave", args=[self.shared_plan.pk]), follow=True)
        self.assertEqual(leave_response.status_code, 200)

        self.shared_plan.refresh_from_db()
        self.assertFalse(self.shared_plan.collaborators.filter(pk=self.collaborator.pk).exists())
        self.assertFalse(CollaborationInvite.objects.filter(list=self.shared_plan, invitee=self.collaborator).exists())

        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.context["profile_stats"]["list_count"], 0)
        self.assertNotContains(profile_response, "管理対象の共同リスト")

        detail_response = self.client.get(reverse("goals:my_list_detail", args=[self.shared_plan.pk]))
        self.assertEqual(detail_response.status_code, 403)
        edit_response = self.client.post(
            reverse("goals:add_my_list_goal_inline", args=[self.shared_plan.pk]),
            {"title": "退出後追加", "category": "other"},
        )
        self.assertEqual(edit_response.status_code, 403)

    def test_owner_can_remove_accepted_collaborator_and_member_loses_access(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("goals:my_list_remove_collaborator", args=[self.shared_plan.pk, self.collaborator.pk]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        self.shared_plan.refresh_from_db()
        self.assertFalse(self.shared_plan.collaborators.filter(pk=self.collaborator.pk).exists())
        self.assertFalse(CollaborationInvite.objects.filter(list=self.shared_plan, invitee=self.collaborator).exists())

        self.client.force_login(self.collaborator)
        detail_response = self.client.get(reverse("goals:my_list_detail", args=[self.shared_plan.pk]))
        self.assertEqual(detail_response.status_code, 403)
        edit_response = self.client.post(
            reverse("goals:edit_my_list_goal_inline", args=[self.goal.pk]),
            {"title": "解除後編集", "category": "other", "item_is_public": "on"},
        )
        self.assertEqual(edit_response.status_code, 403)
        profile_response = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile_response.context["profile_stats"]["list_count"], 0)
        self.assertNotContains(profile_response, "管理対象の共同リスト")

    def test_owner_can_cancel_pending_invite_and_pending_label_disappears(self):
        self.client.force_login(self.owner)

        before_response = self.client.get(reverse("goals:my_list_detail", args=[self.shared_plan.pk]))
        self.assertEqual(before_response.status_code, 200)
        self.assertContains(before_response, "pending5")
        self.assertContains(before_response, "招待中")

        cancel_response = self.client.post(
            reverse("goals:my_list_cancel_invite", args=[self.shared_plan.pk, self.pending_invite.pk]),
            follow=True,
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertFalse(CollaborationInvite.objects.filter(pk=self.pending_invite.pk).exists())
        self.assertFalse(self.shared_plan.collaborators.filter(pk=self.pending_user.pk).exists())

        after_response = self.client.get(reverse("goals:my_list_detail", args=[self.shared_plan.pk]))
        self.assertEqual(after_response.status_code, 200)
        self.assertNotContains(after_response, "pending5")


@override_settings(STORAGES=TEST_STORAGES)
class CollaborativeMemberUiAndLeaveFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner6", email="owner6@example.com", password="password12345")
        self.member = User.objects.create_user(username="member6", email="member6@example.com", password="password12345")
        self.other_member = User.objects.create_user(username="member7", email="member7@example.com", password="password12345")
        self.pending_user = User.objects.create_user(username="pending6", email="pending6@example.com", password="password12345")

        self.private_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="非公開共同リストA",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.private_plan.collaborators.add(self.member, self.other_member)
        self.private_goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.private_plan,
            title="共同項目A",
            category="other",
            item_is_public=True,
            added_by=self.owner,
        )

        self.public_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="公開共同リストB",
            target_count=10,
            is_public=True,
            is_collaborative=True,
        )
        self.public_plan.collaborators.add(self.member)

        CollaborationInvite.objects.create(
            list=self.private_plan,
            inviter=self.owner,
            invitee=self.member,
            status=CollaborationInvite.STATUS_ACCEPTED,
        )
        CollaborationInvite.objects.create(
            list=self.private_plan,
            inviter=self.owner,
            invitee=self.other_member,
            status=CollaborationInvite.STATUS_ACCEPTED,
        )
        self.pending_invite = CollaborationInvite.objects.create(
            list=self.private_plan,
            inviter=self.owner,
            invitee=self.pending_user,
            status=CollaborationInvite.STATUS_PENDING,
        )

    def owner_edit_payload(self, selected_users):
        return {
            "list_title": self.private_plan.list_title,
            "description": self.private_plan.description,
            "target_count": str(self.private_plan.target_count),
            "is_public": "",
            "is_collaborative": "on",
            "collaborators": [str(user.pk) for user in selected_users],
        }

    def test_accepted_member_sees_leave_button_and_leave_confirm_renders_with_cancel_url(self):
        self.client.force_login(self.member)
        detail = self.client.get(reverse("goals:my_list_detail", args=[self.private_plan.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "共同リストから抜ける")

        confirm = self.client.get(reverse("goals:my_list_leave", args=[self.private_plan.pk]))
        self.assertEqual(confirm.status_code, 200)
        self.assertContains(confirm, "共同リストから抜けますか？")
        cancel_url = reverse("goals:my_list_detail", args=[self.private_plan.pk])
        self.assertContains(confirm, f'href="{cancel_url}"')

        cancel_back = self.client.get(cancel_url)
        self.assertEqual(cancel_back.status_code, 200)

    def test_leave_confirmed_removes_only_self_and_revokes_private_access_and_counts(self):
        self.client.force_login(self.member)
        before_profile = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(before_profile.context["profile_stats"]["list_count"], 2)

        leave = self.client.post(reverse("goals:my_list_leave", args=[self.private_plan.pk]), follow=True)
        self.assertEqual(leave.status_code, 200)

        self.private_plan.refresh_from_db()
        self.assertFalse(self.private_plan.collaborators.filter(pk=self.member.pk).exists())
        self.assertTrue(self.private_plan.collaborators.filter(pk=self.other_member.pk).exists())
        self.assertEqual(self.private_plan.user_id, self.owner.pk)
        self.assertTrue(YearPlan.objects.filter(pk=self.private_plan.pk).exists())

        profile = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(profile.status_code, 200)
        self.assertNotContains(profile, "非公開共同リストA")
        self.assertContains(profile, "公開共同リストB")
        self.assertEqual(profile.context["profile_stats"]["list_count"], 1)

        detail = self.client.get(reverse("goals:my_list_detail", args=[self.private_plan.pk]))
        self.assertEqual(detail.status_code, 403)
        edit = self.client.post(
            reverse("goals:edit_my_list_goal_inline", args=[self.private_goal.pk]),
            {"title": "退出後編集", "category": "other", "item_is_public": "on"},
        )
        self.assertEqual(edit.status_code, 403)

    def test_members_section_shows_status_only_without_leave_or_remove_buttons(self):
        self.client.force_login(self.member)
        member_detail = self.client.get(reverse("goals:my_list_detail", args=[self.private_plan.pk]))
        self.assertEqual(member_detail.status_code, 200)
        self.assertNotContains(member_detail, ">退出<", html=True)
        self.assertNotContains(member_detail, ">外す<", html=True)
        self.assertContains(member_detail, "member")
        self.assertNotContains(member_detail, "招待中")

        self.client.force_login(self.owner)
        owner_detail = self.client.get(reverse("goals:my_list_detail", args=[self.private_plan.pk]))
        self.assertEqual(owner_detail.status_code, 200)
        self.assertNotContains(owner_detail, ">外す<", html=True)
        self.assertContains(owner_detail, "招待中")

    def test_owner_edit_form_can_unselect_member_and_save_applies_membership_changes(self):
        self.client.force_login(self.owner)
        edit_page = self.client.get(reverse("goals:my_list_edit", args=[self.private_plan.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "選択済みメンバー")

        payload = self.owner_edit_payload([self.other_member])
        response = self.client.post(reverse("goals:my_list_edit", args=[self.private_plan.pk]), payload, follow=True)
        self.assertEqual(response.status_code, 200)

        self.private_plan.refresh_from_db()
        self.assertFalse(self.private_plan.collaborators.filter(pk=self.member.pk).exists())
        self.assertTrue(self.private_plan.collaborators.filter(pk=self.other_member.pk).exists())

    def test_owner_edit_cancel_keeps_member_and_non_owner_cannot_change_composition(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("goals:my_list_edit", args=[self.private_plan.pk]))
        self.assertEqual(page.status_code, 200)
        self.private_plan.refresh_from_db()
        self.assertTrue(self.private_plan.collaborators.filter(pk=self.member.pk).exists())

        self.client.force_login(self.member)
        payload = self.owner_edit_payload([])
        denied = self.client.post(reverse("goals:my_list_edit", args=[self.private_plan.pk]), payload)
        self.assertEqual(denied.status_code, 404)
        self.private_plan.refresh_from_db()
        self.assertTrue(self.private_plan.collaborators.filter(pk=self.member.pk).exists())

    def test_owner_edit_unselect_pending_removes_stale_pending_invite(self):
        self.client.force_login(self.owner)
        payload = self.owner_edit_payload([self.member, self.other_member])
        response = self.client.post(reverse("goals:my_list_edit", args=[self.private_plan.pk]), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CollaborationInvite.objects.filter(
                list=self.private_plan,
                invitee=self.pending_user,
                status=CollaborationInvite.STATUS_PENDING,
            ).exists()
        )

    def test_my_profile_shows_collaborative_badges(self):
        self.client.force_login(self.owner)
        owner_profile = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(owner_profile.status_code, 200)
        self.assertContains(owner_profile, "profile-list-badges")
        self.assertContains(owner_profile, "非公開共同リストA")
        self.assertContains(owner_profile, "非公開")
        self.assertContains(owner_profile, "共同リスト")
        self.assertRegex(owner_profile.content.decode(), r"profile-list-badges[\s\S]*?非公開[\s\S]*?共同リスト")

        self.client.force_login(self.member)
        member_profile = self.client.get(reverse("goals:my_profile"))
        self.assertEqual(member_profile.status_code, 200)
        self.assertContains(member_profile, "公開共同リストB")
        self.assertContains(member_profile, "共同リスト")


@override_settings(STORAGES=TEST_STORAGES)
class PublicListGroupPerformanceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="perf_owner", email="owner@example.com", password="password12345")
        self.viewer = User.objects.create_user(username="perf_viewer", email="viewer@example.com", password="password12345")
        self.reactor = User.objects.create_user(username="perf_reactor", email="reactor@example.com", password="password12345")
        self.owner.profile.is_private = False
        self.owner.profile.save(update_fields=["is_private"])
        Follow.objects.create(follower=self.viewer, following=self.owner)

        self.plans = []
        for idx in range(1, 4):
            plan = YearPlan.objects.create(
                user=self.owner,
                year=2026,
                list_title=f"公開リスト{idx}",
                target_count=20,
                is_public=True,
            )
            plan.collaborators.add(self.reactor)
            ListComment.objects.create(user=self.reactor, my_list=plan, body=f"comment {idx}")
            LikeList.objects.create(user=self.reactor, my_list=plan)
            SavedList.objects.create(user=self.reactor, my_list=plan)
            for goal_idx in range(1, 8):
                YearlyGoal.objects.create(
                    user=self.owner,
                    year_plan=plan,
                    title=f"目標{idx}-{goal_idx}",
                    category="other",
                    is_done=(goal_idx % 3 == 0),
                    item_is_public=(goal_idx % 4 != 0),
                )
            self.plans.append(plan)

        self.request_factory = RequestFactory()

    def legacy_build_public_list_groups(self, plans, request_user=None, category="", request=None, include_private=False):
        plan_ids = [plan.pk for plan in plans]
        goals = YearlyGoal.objects.filter(
            year_plan_id__in=plan_ids,
        ).select_related("user", "user__profile", "year_plan").order_by("is_done", "-created_at")
        if category:
            goals = goals.filter(category=category)

        grouped_goals = []
        groups_by_plan = {}
        for plan in plans:
            profile = plan.user.profile if hasattr(plan.user, "profile") else None
            display_name = profile.display_name if profile and profile.display_name else plan.user.username
            detail_url_name = "goals:public_list_detail"
            if request_user and request_user.is_authenticated and views.can_view_year_plan(request_user, plan):
                if (plan.user_id == request_user.id) or plan.collaborators.filter(pk=request_user.pk).exists() or not plan.is_public:
                    detail_url_name = "goals:my_list_detail"
            collaborators_display = []
            try:
                collaborators_qs = plan.collaborators.all().select_related("profile")
            except Exception:
                collaborators_qs = []
            for c in collaborators_qs:
                try:
                    c_profile = c.profile
                except Exception:
                    c_profile = None
                collaborators_display.append(c_profile.display_name if c_profile and c_profile.display_name else c.username)
            groups_by_plan[plan.pk] = {
                "plan": plan,
                "user": plan.user,
                "display_name": display_name,
                "detail_url_name": detail_url_name,
                "collaborators_display": collaborators_display,
                "list_title": plan.list_title or f"{plan.year}年やりたいこと",
                "target_count": plan.target_count,
                "done_count": plan.goals.filter(is_done=True).count() if include_private else plan.goals.filter(item_is_public=True, is_done=True).count(),
                "registered_count": plan.goals.count(),
                "total_count": plan.goals.count(),
                "remaining_count": max(plan.target_count - plan.goals.count(), 0),
                "like_count": plan.liked_by.count(),
                "save_count": plan.saved_by.count(),
                "is_saved": False,
                "is_liked": False,
                "can_react": bool(request_user and request_user.is_authenticated and request_user != plan.user),
                "can_follow": bool(request_user and request_user.is_authenticated and request_user != plan.user),
                "is_private": bool(profile and profile.is_private),
                "follow_request_status": "",
                "show_item_privacy": include_private,
                "comment_form": views.ListCommentForm(),
                "comments": plan.comments.select_related("user", "user__profile").all(),
                "goals": [],
                "private_placeholder_count": 0,
            }
            grouped_goals.append(groups_by_plan[plan.pk])

        if request_user and request_user.is_authenticated:
            saved_plan_ids = set(SavedList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
            liked_plan_ids = set(LikeList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
            saved_item_ids = set(SavedItem.objects.filter(user=request_user, item__year_plan_id__in=plan_ids).values_list("item_id", flat=True))
            wanted_item_ids = set(TogetherRequest.objects.none().values_list("list_item_id", flat=True))
            together_statuses = {
                item.list_item_id: item.status
                for item in TogetherRequest.objects.filter(requester=request_user, list_item__year_plan_id__in=plan_ids)
            }
            memo_titles = set(IdeaMemo.objects.filter(user=request_user).values_list("title", flat=True))
            following_user_ids = set(Follow.objects.filter(follower=request_user).values_list("following_id", flat=True))
            for plan_id, group in groups_by_plan.items():
                group["is_saved"] = plan_id in saved_plan_ids
                group["is_liked"] = plan_id in liked_plan_ids
                group["is_following"] = group["user"].pk in following_user_ids
                group["follow_request_status"] = views.get_follow_request_status(request_user, group["user"])
        else:
            saved_item_ids = set()
            wanted_item_ids = set()
            together_statuses = {}
            memo_titles = set()

        for goal in goals:
            group = groups_by_plan.get(goal.year_plan_id)
            if group:
                can_show_goal = include_private
                if not include_private:
                    if request_user is None:
                        can_show_goal = goal.item_is_public
                    else:
                        can_show_goal = views.can_view_yearly_goal(request_user, goal)
                if can_show_goal:
                    goal.is_wanted_by_current_user = goal.pk in wanted_item_ids or goal.title in memo_titles
                    goal.is_saved_by_current_user = goal.pk in saved_item_ids
                    goal.together_status_for_current_user = together_statuses.get(goal.pk)
                    group["goals"].append(goal)
                else:
                    group["private_placeholder_count"] += 1

        if not include_private:
            for group in grouped_goals:
                for _ in range(group["private_placeholder_count"]):
                    group["goals"].append({
                        "is_private_placeholder": True,
                        "title": "🔒 非公開の項目",
                    })

        for group in grouped_goals:
            group["progress_percent"] = views.progress_percent(group["done_count"], group["total_count"])
            group["target_progress_percent"] = views.progress_percent(group["done_count"], group["target_count"])

        return grouped_goals

    def test_build_public_list_groups_reduces_query_count_without_behavior_change(self):
        request = self.request_factory.get(reverse("goals:public_goal_list"))
        request.user = self.viewer

        legacy_plans = list(YearPlan.objects.filter(pk__in=[plan.pk for plan in self.plans]).select_related("user", "user__profile"))
        optimized_plans = list(YearPlan.objects.filter(pk__in=[plan.pk for plan in self.plans]).select_related("user", "user__profile"))

        with CaptureQueriesContext(connection) as legacy_context:
            legacy_groups = self.legacy_build_public_list_groups(legacy_plans, self.viewer, request=request)
        with CaptureQueriesContext(connection) as optimized_context:
            optimized_groups = views.build_public_list_groups(optimized_plans, self.viewer, request=request)

        legacy_queries = len(legacy_context)
        optimized_queries = len(optimized_context)

        self.assertEqual(len(legacy_groups), len(optimized_groups))
        self.assertEqual(
            [group["list_title"] for group in legacy_groups],
            [group["list_title"] for group in optimized_groups],
        )
        self.assertEqual(
            [group["total_count"] for group in legacy_groups],
            [group["total_count"] for group in optimized_groups],
        )
        self.assertLess(
            optimized_queries,
            legacy_queries,
            msg=f"legacy={legacy_queries}, optimized={optimized_queries}",
        )


@override_settings(STORAGES=TEST_STORAGES)
class ProgressPercentConsistencyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="progress_owner",
            email="progress_owner@example.com",
            password="password12345",
        )
        self.client.force_login(self.user)

    def test_progress_percent_requested_examples(self):
        self.assertEqual(views.progress_percent(0, 0), 0)
        self.assertEqual(views.progress_percent(0, 10), 0)
        self.assertEqual(views.progress_percent(1, 10), 10)
        self.assertEqual(views.progress_percent(5, 10), 50)
        self.assertEqual(views.progress_percent(10, 10), 100)
        self.assertEqual(views.progress_percent(2, 2), 100)

    def test_my_profile_and_my_list_detail_use_same_progress_formula(self):
        plan = YearPlan.objects.create(
            user=self.user,
            year=2026,
            list_title="Progress check",
            target_count=100,
            is_public=True,
        )
        YearlyGoal.objects.create(user=self.user, year_plan=plan, title="done-1", is_done=True)
        YearlyGoal.objects.create(user=self.user, year_plan=plan, title="done-2", is_done=True)

        profile_response = self.client.get(reverse("goals:my_profile"))
        detail_response = self.client.get(reverse("goals:my_list_detail", args=[plan.pk]))

        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(profile_response.context["my_plans"][0].progress_percent, 100)
        self.assertEqual(detail_response.context["setting"].progress_percent, 100)


@override_settings(STORAGES=TEST_STORAGES)
class ManagementAdminFeatureTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="mgmt_staff",
            email="mgmt_staff@example.com",
            password="password12345",
            is_staff=True,
        )
        self.normal_user = User.objects.create_user(
            username="mgmt_user",
            email="mgmt_user@example.com",
            password="password12345",
        )
        self.target_user = User.objects.create_user(
            username="target_user",
            email="target_user@example.com",
            password="password12345",
        )
        self.old_user = User.objects.create_user(
            username="very_old_user",
            email="very_old_user@example.com",
            password="password12345",
        )
        self.old_user.date_joined = timezone.now() - timedelta(days=120)
        self.old_user.save(update_fields=["date_joined"])

        self.now = timezone.now()
        self.today = timezone.localdate()
        self.list_created_today = self.now
        self.list_created_7_days_ago = self.now - timedelta(days=6)
        self.list_created_32_days_ago = self.now - timedelta(days=32)
        self.item_created_today = self.now
        self.item_created_3_days_ago = self.now - timedelta(days=3)
        self.item_created_8_days_ago = self.now - timedelta(days=8)
        self.item_created_40_days_ago = self.now - timedelta(days=40)

        self.public_collab_plan = YearPlan.objects.create(
            user=self.target_user,
            year=2026,
            list_title="公開共同リスト",
            target_count=30,
            is_public=True,
            is_collaborative=True,
        )
        self.private_plan = YearPlan.objects.create(
            user=self.target_user,
            year=2025,
            list_title="非公開リスト",
            target_count=10,
            is_public=False,
            is_collaborative=False,
        )
        YearPlan.objects.filter(pk=self.public_collab_plan.pk).update(created_at=self.list_created_today)
        YearPlan.objects.filter(pk=self.private_plan.pk).update(created_at=self.list_created_7_days_ago)
        self.older_public_list = YearPlan.objects.create(
            user=self.normal_user,
            year=2024,
            list_title="古い公開リスト",
            target_count=20,
            is_public=True,
            is_collaborative=False,
        )
        YearPlan.objects.filter(pk=self.older_public_list.pk).update(created_at=self.list_created_32_days_ago)

        YearlyGoal.objects.create(user=self.target_user, year_plan=self.public_collab_plan, title="公開項目A", is_done=True)
        YearlyGoal.objects.create(user=self.target_user, year_plan=self.public_collab_plan, title="公開項目B", is_done=False)
        YearlyGoal.objects.create(user=self.target_user, year_plan=self.public_collab_plan, title="公開項目C", is_done=False)
        YearlyGoal.objects.create(user=self.target_user, year_plan=self.private_plan, title="非公開項目", is_done=False)
        YearlyGoal.objects.create(user=self.normal_user, year_plan=self.older_public_list, title="古い項目", is_done=False)
        YearlyGoal.objects.filter(title="公開項目A").update(created_at=self.item_created_today)
        YearlyGoal.objects.filter(title="公開項目B").update(created_at=self.item_created_8_days_ago)
        YearlyGoal.objects.filter(title="公開項目C").update(created_at=self.item_created_3_days_ago)
        YearlyGoal.objects.filter(title="非公開項目").update(created_at=self.item_created_40_days_ago)
        YearlyGoal.objects.filter(title="古い項目").update(created_at=self.item_created_40_days_ago)

    def _management_pages(self):
        return [
            reverse("goals:management_dashboard"),
            reverse("goals:management_users"),
            reverse("goals:management_user_detail", args=[self.target_user.pk]),
            reverse("goals:management_lists"),
            reverse("goals:management_list_detail", args=[self.public_collab_plan.pk]),
            reverse("goals:management_templates"),
        ]

    def test_staff_can_access_management_pages(self):
        self.client.force_login(self.staff)
        for url in self._management_pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_non_staff_cannot_access_management_pages(self):
        self.client.force_login(self.normal_user)
        for url in self._management_pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response["Location"])

        action_urls = [
            reverse("goals:management_user_deactivate", args=[self.target_user.pk]),
            reverse("goals:management_user_activate", args=[self.target_user.pk]),
            reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]),
        ]
        for url in action_urls:
            with self.subTest(action_url=url):
                response = self.client.post(url, {"confirm": "1"})
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response["Location"])

    def test_anonymous_cannot_access_management_pages(self):
        for url in self._management_pages():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response["Location"])

        action_urls = [
            reverse("goals:management_user_deactivate", args=[self.target_user.pk]),
            reverse("goals:management_user_activate", args=[self.target_user.pk]),
            reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]),
        ]
        for url in action_urls:
            with self.subTest(action_url=url):
                response = self.client.post(url, {"confirm": "1"})
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response["Location"])

    def test_dashboard_kpis_include_visibility_and_collaboration_counts(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("goals:management_dashboard"))

        self.assertEqual(response.status_code, 200)
        kpi_map = {item["label"]: item["value"] for item in response.context["kpis"]}
        self.assertEqual(kpi_map["総ユーザー数"], get_user_model().objects.count())
        self.assertEqual(kpi_map["今日の新規登録数"], get_user_model().objects.filter(date_joined__date=timezone.localdate()).count())
        self.assertEqual(kpi_map["過去7日の新規登録数"], get_user_model().objects.filter(date_joined__date__gte=timezone.localdate() - timedelta(days=6)).count())
        self.assertEqual(kpi_map["過去30日の新規登録数"], get_user_model().objects.filter(date_joined__date__gte=timezone.localdate() - timedelta(days=29)).count())
        self.assertEqual(kpi_map["総リスト数"], YearPlan.objects.count())
        self.assertEqual(kpi_map["総項目数"], YearlyGoal.objects.count())
        self.assertEqual(kpi_map["達成済み項目数"], YearlyGoal.objects.filter(is_done=True).count())
        self.assertEqual(kpi_map["公開リスト数"], YearPlan.objects.filter(is_public=True).count())
        self.assertEqual(kpi_map["非公開リスト数"], YearPlan.objects.filter(is_public=False).count())
        self.assertEqual(kpi_map["共同リスト数"], YearPlan.objects.filter(is_collaborative=True).count())

    def test_dashboard_period_switch_supports_7_30_90_and_all(self):
        self.client.force_login(self.staff)

        for period in ("7", "30", "90"):
            with self.subTest(period=period):
                response = self.client.get(reverse("goals:management_dashboard"), {"period": period})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["period"], period)
                self.assertEqual(len(response.context["user_chart"]["rows"]), int(period))
                self.assertEqual(len(response.context["list_chart"]["rows"]), int(period))
                self.assertEqual(len(response.context["item_chart"]["rows"]), int(period))
                self.assertContains(response, response.context["user_chart"]["points"])

        all_response = self.client.get(reverse("goals:management_dashboard"), {"period": "all"})
        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(all_response.context["period"], "all")
        earliest = get_user_model().objects.order_by("date_joined").first().date_joined.date()
        expected_days = (timezone.localdate() - earliest).days + 1
        self.assertEqual(len(all_response.context["user_chart"]["rows"]), expected_days)
        self.assertContains(all_response, all_response.context["user_chart"]["points"])
        self.assertEqual(all_response.context["list_chart"]["rows"][0]["date"], self.list_created_32_days_ago.date())
        self.assertEqual(all_response.context["item_chart"]["rows"][0]["date"], self.item_created_40_days_ago.date())

    def test_new_list_and_item_daily_counts_include_zero_days(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("goals:management_dashboard"), {"period": "7"})

        self.assertEqual(response.status_code, 200)
        list_rows = response.context["list_chart"]["rows"]
        item_rows = response.context["item_chart"]["rows"]

        self.assertEqual(len(list_rows), 7)
        self.assertEqual(len(item_rows), 7)
        self.assertTrue(any(row["count"] == 0 for row in list_rows))
        self.assertTrue(any(row["count"] == 0 for row in item_rows))
        self.assertEqual(sum(row["count"] for row in list_rows), 2)
        self.assertEqual(sum(row["count"] for row in item_rows), 2)

    def test_all_period_uses_each_dataset_oldest_created_at(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("goals:management_dashboard"), {"period": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user_chart"]["rows"][0]["date"], self.old_user.date_joined.date())
        self.assertEqual(response.context["list_chart"]["rows"][0]["date"], self.list_created_32_days_ago.date())
        self.assertEqual(response.context["item_chart"]["rows"][0]["date"], self.item_created_40_days_ago.date())

    def test_management_users_search_and_user_detail(self):
        self.client.force_login(self.staff)
        users_response = self.client.get(reverse("goals:management_users"), {"q": "target_user"})
        detail_response = self.client.get(reverse("goals:management_user_detail", args=[self.target_user.pk]))

        self.assertEqual(users_response.status_code, 200)
        self.assertContains(users_response, "target_user")
        self.assertNotContains(users_response, "mgmt_user")

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "target_user")
        self.assertContains(detail_response, "このユーザーが作成したリスト")
        self.assertContains(detail_response, "公開共同リスト")
        self.assertContains(detail_response, "非公開リスト")

    def test_management_lists_search_filter_and_detail(self):
        self.client.force_login(self.staff)

        search_response = self.client.get(reverse("goals:management_lists"), {"q": "公開共同"})
        self.assertEqual(search_response.status_code, 200)
        self.assertContains(search_response, "公開共同リスト")
        self.assertNotContains(search_response, "非公開リスト")

        public_response = self.client.get(reverse("goals:management_lists"), {"visibility": "public"})
        self.assertContains(public_response, "公開共同リスト")
        self.assertNotContains(public_response, "非公開リスト")

        private_response = self.client.get(reverse("goals:management_lists"), {"visibility": "private"})
        self.assertContains(private_response, "非公開リスト")
        self.assertNotContains(private_response, "公開共同リスト")

        detail_response = self.client.get(reverse("goals:management_list_detail", args=[self.public_collab_plan.pk]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "公開共同リスト")
        self.assertContains(detail_response, "公開項目A")
        self.assertContains(detail_response, "公開項目B")

    def test_user_deactivate_and_activate_flow(self):
        self.client.force_login(self.staff)

        deactivate_url = reverse("goals:management_user_deactivate", args=[self.target_user.pk])
        activate_url = reverse("goals:management_user_activate", args=[self.target_user.pk])

        response = self.client.post(deactivate_url, {"confirm": "1"})
        self.assertEqual(response.status_code, 302)
        self.target_user.refresh_from_db()
        self.assertFalse(self.target_user.is_active)

        response = self.client.post(activate_url, {"confirm": "1"})
        self.assertEqual(response.status_code, 302)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.is_active)

    def test_staff_cannot_deactivate_self(self):
        self.client.force_login(self.staff)

        response = self.client.post(reverse("goals:management_user_deactivate", args=[self.staff.pk]), {"confirm": "1"})
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_management_list_make_private(self):
        self.client.force_login(self.staff)
        self.assertTrue(self.public_collab_plan.is_public)

        response = self.client.post(
            reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]),
            {"confirm": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.public_collab_plan.refresh_from_db()
        self.assertFalse(self.public_collab_plan.is_public)

    def test_management_actions_require_confirmation_checkbox(self):
        self.client.force_login(self.staff)

        response = self.client.post(reverse("goals:management_user_deactivate", args=[self.target_user.pk]), {})
        self.assertEqual(response.status_code, 302)
        self.target_user.refresh_from_db()
        self.assertTrue(self.target_user.is_active)

        response = self.client.post(reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]), {})
        self.assertEqual(response.status_code, 302)
        self.public_collab_plan.refresh_from_db()
        self.assertTrue(self.public_collab_plan.is_public)

    def test_management_actions_require_post(self):
        self.client.force_login(self.staff)

        urls = [
            reverse("goals:management_user_deactivate", args=[self.target_user.pk]),
            reverse("goals:management_user_activate", args=[self.target_user.pk]),
            reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)

    def test_management_actions_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)

        response = csrf_client.post(
            reverse("goals:management_user_deactivate", args=[self.target_user.pk]),
            {"confirm": "1"},
        )
        self.assertEqual(response.status_code, 403)

        response = csrf_client.post(
            reverse("goals:management_list_make_private", args=[self.public_collab_plan.pk]),
            {"confirm": "1"},
        )
        self.assertEqual(response.status_code, 403)

    def test_django_admin_has_operational_models_registered(self):
        expected_models = {
            Profile,
            FollowRequest,
            CollaborationInvite,
            GoalImage,
            GoalLink,
            LikeList,
            SavedList,
            SavedItem,
            WantToTry,
            Follow,
            TogetherRequest,
            ListComment,
            YearPlan,
            YearlyGoal,
            UserActivity,
        }
        for model in expected_models:
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)


@override_settings(STORAGES=TEST_STORAGES)
class ToggleDoneMethodAndPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="toggle_owner", email="toggle_owner@example.com", password="password12345")
        self.collaborator = User.objects.create_user(username="toggle_collab", email="toggle_collab@example.com", password="password12345")
        self.stranger = User.objects.create_user(username="toggle_stranger", email="toggle_stranger@example.com", password="password12345")

        self.private_plan = YearPlan.objects.create(
            user=self.owner,
            year=2026,
            list_title="非公開リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        self.private_plan.collaborators.add(self.collaborator)

        self.yearly_goal = YearlyGoal.objects.create(
            user=self.owner,
            year_plan=self.private_plan,
            title="年間TODO",
            category="other",
            item_is_public=True,
            is_done=False,
            added_by=self.owner,
        )
        today = timezone.localdate()
        self.monthly_goal = MonthlyGoal.objects.create(
            user=self.owner,
            month=today.replace(day=1),
            target_month=today.replace(day=1),
            title="月TODO",
            is_done=False,
        )
        week_start = today - timedelta(days=today.weekday())
        self.weekly_goal = WeeklyGoal.objects.create(
            user=self.owner,
            week_start=week_start,
            week_start_date=week_start,
            title="週TODO",
            is_done=False,
        )
        self.today_task = TodayTask.objects.create(
            user=self.owner,
            date=today,
            scheduled_date=today,
            title="今日TODO",
            is_done=False,
        )

    def test_post_with_valid_permissions_toggles_state_for_all_models(self):
        self.client.force_login(self.owner)

        requests = [
            (reverse("goals:toggle_done", args=["yearly", self.yearly_goal.pk]), {"is_done": "1"}),
            (reverse("goals:toggle_done", args=["monthly", self.monthly_goal.pk]), {}),
            (reverse("goals:toggle_done", args=["weekly", self.weekly_goal.pk]), {}),
            (reverse("goals:toggle_done", args=["today", self.today_task.pk]), {}),
        ]
        for url, payload in requests:
            with self.subTest(url=url):
                response = self.client.post(url, payload)
                self.assertEqual(response.status_code, 302)

        self.yearly_goal.refresh_from_db()
        self.monthly_goal.refresh_from_db()
        self.weekly_goal.refresh_from_db()
        self.today_task.refresh_from_db()
        self.assertTrue(self.yearly_goal.is_done)
        self.assertTrue(self.monthly_goal.is_done)
        self.assertTrue(self.weekly_goal.is_done)
        self.assertTrue(self.today_task.is_done)

    def test_post_allows_collaborator_to_toggle_yearly_goal(self):
        self.client.force_login(self.collaborator)

        response = self.client.post(reverse("goals:toggle_done", args=["yearly", self.yearly_goal.pk]), {"is_done": "1"})

        self.assertEqual(response.status_code, 302)
        self.yearly_goal.refresh_from_db()
        self.assertTrue(self.yearly_goal.is_done)

    def test_get_returns_405_and_never_changes_state_for_all_models(self):
        self.client.force_login(self.owner)

        urls = [
            reverse("goals:toggle_done", args=["yearly", self.yearly_goal.pk]),
            reverse("goals:toggle_done", args=["monthly", self.monthly_goal.pk]),
            reverse("goals:toggle_done", args=["weekly", self.weekly_goal.pk]),
            reverse("goals:toggle_done", args=["today", self.today_task.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 405)

        self.yearly_goal.refresh_from_db()
        self.monthly_goal.refresh_from_db()
        self.weekly_goal.refresh_from_db()
        self.today_task.refresh_from_db()
        self.assertFalse(self.yearly_goal.is_done)
        self.assertFalse(self.monthly_goal.is_done)
        self.assertFalse(self.weekly_goal.is_done)
        self.assertFalse(self.today_task.is_done)

    def test_anonymous_post_cannot_change_state(self):
        response = self.client.post(reverse("goals:toggle_done", args=["monthly", self.monthly_goal.pk]))

        self.assertEqual(response.status_code, 302)
        self.monthly_goal.refresh_from_db()
        self.assertFalse(self.monthly_goal.is_done)

    def test_user_without_permission_cannot_toggle_yearly_goal(self):
        self.client.force_login(self.stranger)

        response = self.client.post(reverse("goals:toggle_done", args=["yearly", self.yearly_goal.pk]))

        self.assertEqual(response.status_code, 403)
        self.yearly_goal.refresh_from_db()
        self.assertFalse(self.yearly_goal.is_done)

    def test_user_without_permission_cannot_toggle_other_users_monthly_weekly_today(self):
        self.client.force_login(self.stranger)

        urls = [
            reverse("goals:toggle_done", args=["monthly", self.monthly_goal.pk]),
            reverse("goals:toggle_done", args=["weekly", self.weekly_goal.pk]),
            reverse("goals:toggle_done", args=["today", self.today_task.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 404)

        self.monthly_goal.refresh_from_db()
        self.weekly_goal.refresh_from_db()
        self.today_task.refresh_from_db()
        self.assertFalse(self.monthly_goal.is_done)
        self.assertFalse(self.weekly_goal.is_done)
        self.assertFalse(self.today_task.is_done)

    def test_csrf_missing_post_is_rejected_and_state_unchanged(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)

        urls = [
            reverse("goals:toggle_done", args=["yearly", self.yearly_goal.pk]),
            reverse("goals:toggle_done", args=["monthly", self.monthly_goal.pk]),
            reverse("goals:toggle_done", args=["weekly", self.weekly_goal.pk]),
            reverse("goals:toggle_done", args=["today", self.today_task.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = csrf_client.post(url)
                self.assertEqual(response.status_code, 403)

        self.yearly_goal.refresh_from_db()
        self.monthly_goal.refresh_from_db()
        self.weekly_goal.refresh_from_db()
        self.today_task.refresh_from_db()
        self.assertFalse(self.yearly_goal.is_done)
        self.assertFalse(self.monthly_goal.is_done)
        self.assertFalse(self.weekly_goal.is_done)
        self.assertFalse(self.today_task.is_done)


@override_settings(STORAGES=TEST_STORAGES)
class PasswordResetResendTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="resetuser",
            email="resetuser@example.com",
            password="password12345",
        )

    @override_settings(
        IS_PRODUCTION=False,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Wishly <noreply@example.com>",
    )
    def test_password_reset_local_uses_existing_backend_and_generates_uid_token_link(self):
        response = self.client.post(reverse("password_reset"), {"email": self.user.email})

        self.assertRedirects(response, reverse("password_reset_done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, [self.user.email])
        self.assertEqual(sent.from_email, "Wishly <noreply@example.com>")
        self.assertIn("Wishly パスワード再設定", sent.subject)
        self.assertRegex(sent.body, r"/accounts/reset/[0-9A-Za-z_\-]+/[0-9A-Za-z\-]+/")

    @override_settings(
        IS_PRODUCTION=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Wishly <noreply@example.com>",
    )
    def test_password_reset_in_production_calls_resend_for_existing_user(self):
        resend_send = Mock(return_value={"id": "email_test_id"})
        resend_module = SimpleNamespace(api_key="", Emails=SimpleNamespace(send=resend_send))

        with patch.dict(os.environ, {"RESEND_API_KEY": "test_resend_key"}, clear=False):
            with patch("goals.forms.settings.RESEND_API_KEY", "test_resend_key"):
                with patch("goals.forms.importlib.import_module", return_value=resend_module):
                    response = self.client.post(reverse("password_reset"), {"email": self.user.email})

        self.assertRedirects(response, reverse("password_reset_done"), fetch_redirect_response=False)
        resend_send.assert_called_once()
        payload = resend_send.call_args.args[0]
        self.assertEqual(payload["to"], [self.user.email])
        self.assertEqual(payload["from"], "Wishly <noreply@example.com>")
        self.assertIn("Wishly パスワード再設定", payload["subject"])
        self.assertRegex(payload["text"], r"/accounts/reset/[0-9A-Za-z_\-]+/[0-9A-Za-z\-]+/")

    @override_settings(
        IS_PRODUCTION=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Wishly <noreply@example.com>",
    )
    def test_password_reset_done_redirect_is_kept_when_resend_fails_and_secrets_not_exposed(self):
        resend_send = Mock(side_effect=RuntimeError("RESEND_API_KEY=leaked_value"))
        resend_module = SimpleNamespace(api_key="", Emails=SimpleNamespace(send=resend_send))

        with patch.dict(os.environ, {"RESEND_API_KEY": "test_resend_key"}, clear=False):
            with patch("goals.forms.settings.RESEND_API_KEY", "test_resend_key"):
                with patch("goals.forms.importlib.import_module", return_value=resend_module):
                    response = self.client.post(reverse("password_reset"), {"email": self.user.email}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/password_reset_done.html")
        self.assertNotContains(response, "test_resend_key")
        self.assertNotContains(response, "leaked_value")

    @override_settings(
        IS_PRODUCTION=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Wishly <noreply@example.com>",
    )
    def test_unknown_email_does_not_call_resend_and_still_redirects_done(self):
        resend_send = Mock(return_value={"id": "email_test_id"})
        resend_module = SimpleNamespace(api_key="", Emails=SimpleNamespace(send=resend_send))

        with patch.dict(os.environ, {"RESEND_API_KEY": "test_resend_key"}, clear=False):
            with patch("goals.forms.settings.RESEND_API_KEY", "test_resend_key"):
                with patch("goals.forms.importlib.import_module", return_value=resend_module):
                    response = self.client.post(reverse("password_reset"), {"email": "unknown@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"), fetch_redirect_response=False)
        resend_send.assert_not_called()

    def test_resend_api_key_is_not_hardcoded_in_password_reset_form_source(self):
        source = inspect.getsource(goals_forms.ResendPasswordResetForm)
        self.assertIn("RESEND_API_KEY", source)
        self.assertNotRegex(source, r"re_[A-Za-z0-9]{10,}")

    def test_account_settings_does_not_show_verification_resend_ui(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("goals:account_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "認証メールを再送する")
        self.assertNotContains(response, "メールアドレスがまだ確認されていません")

    def test_login_and_password_change_pages_still_work(self):
        login_response = self.client.get(reverse("login"))
        self.assertEqual(login_response.status_code, 200)
        self.assertContains(login_response, "パスワードをお忘れですか？")

        self.client.force_login(self.user)
        password_change_response = self.client.get(reverse("password_change"))
        self.assertEqual(password_change_response.status_code, 200)


@override_settings(STORAGES=TEST_STORAGES)
class ContactAndLegalPagesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="contactuser",
            email="contactuser@example.com",
            password="password12345",
        )

    def test_terms_and_privacy_pages_return_200(self):
        self.assertEqual(self.client.get(reverse("goals:terms")).status_code, 200)
        self.assertEqual(self.client.get(reverse("goals:privacy_policy")).status_code, 200)

    def test_contact_get_returns_200(self):
        response = self.client.get(reverse("goals:contact"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "お問い合わせ")

    def test_anonymous_user_can_submit_contact_form(self):
        response = self.client.post(
            reverse("goals:contact"),
            {
                "name": "匿名ユーザー",
                "email": "anon@example.com",
                "message": "公開前チェックについて質問です。",
            },
        )
        self.assertRedirects(response, reverse("goals:contact_done"), fetch_redirect_response=False)
        self.assertTrue(Inquiry.objects.filter(email="anon@example.com").exists())

    def test_logged_in_user_can_submit_contact_form(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("goals:contact"),
            {
                "name": "ログインユーザー",
                "email": "contactuser@example.com",
                "message": "ログイン状態で送信します。",
            },
        )
        self.assertRedirects(response, reverse("goals:contact_done"), fetch_redirect_response=False)
        self.assertTrue(Inquiry.objects.filter(name="ログインユーザー").exists())

    def test_authenticated_app_pages_hide_common_footer_links(self):
        self.client.force_login(self.user)

        for url_name in ["goals:my_profile", "goals:public_goal_list", "goals:yearly_goal_list"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, reverse("goals:contact"))
                self.assertNotContains(response, reverse("goals:terms"))
                self.assertNotContains(response, reverse("goals:privacy_policy"))

    def test_contact_post_without_csrf_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("goals:contact"),
            {
                "name": "NoCSRF",
                "email": "nocsrf@example.com",
                "message": "csrfなし",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Inquiry.objects.filter(email="nocsrf@example.com").exists())

    def test_contact_required_validation_and_email_validation(self):
        empty_response = self.client.post(reverse("goals:contact"), {"name": "", "email": "", "message": ""})
        self.assertEqual(empty_response.status_code, 200)
        form = empty_response.context["form"]
        self.assertIn("このフィールドは必須です。", form.errors["name"]) 
        self.assertIn("このフィールドは必須です。", form.errors["email"]) 
        self.assertIn("このフィールドは必須です。", form.errors["message"]) 

        invalid_email_response = self.client.post(
            reverse("goals:contact"),
            {"name": "テスト", "email": "not-an-email", "message": "本文"},
        )
        self.assertEqual(invalid_email_response.status_code, 200)
        form = invalid_email_response.context["form"]
        self.assertIn("有効なメールアドレスを入力してください。", form.errors["email"])

    def test_contact_rejects_too_many_urls(self):
        message = " ".join([f"https://example.com/{idx}" for idx in range(6)])
        response = self.client.post(
            reverse("goals:contact"),
            {"name": "spam", "email": "spam@example.com", "message": message},
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("URLの記載が多すぎます。内容を確認してください。", form.errors["message"])

    def test_contact_post_saves_inquiry_with_pending_status(self):
        self.client.post(
            reverse("goals:contact"),
            {
                "name": "保存確認",
                "email": "save@example.com",
                "message": "DBに保存されるか確認します。",
            },
        )
        inquiry = Inquiry.objects.get(email="save@example.com")
        self.assertEqual(inquiry.status, Inquiry.STATUS_PENDING)
        self.assertIsNotNone(inquiry.created_at)

    def test_inquiry_model_is_registered_in_admin(self):
        self.assertIn(Inquiry, admin.site._registry)

    def test_signup_page_shows_terms_and_privacy_links(self):
        response = self.client.get(reverse("goals:signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("goals:terms"))
        self.assertContains(response, reverse("goals:privacy_policy"))
        self.assertContains(response, "利用規約")
        self.assertContains(response, "プライバシーポリシー")

    def test_login_page_has_contact_link(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("goals:contact"))

    def test_existing_account_delete_flow_still_works(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("goals:account_delete"))
        self.assertRedirects(response, reverse("goals:home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
