import base64
import importlib
import os
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)

from .models import (
    Follow,
    FollowRequest,
    GoalImage,
    IdeaMemo,
    LikeList,
    ListComment,
    Profile,
    SavedItem,
    SavedList,
    TogetherRequest,
    YearPlan,
    YearlyGoal,
)


TEST_STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


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
