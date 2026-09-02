import base64
import binascii
import io
import re
import uuid
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
except ImportError:
    register_heif_opener = None
else:
    register_heif_opener(thumbnails=False)

from .models import (
    CollaborationInvite,
    Follow,
    GoalImage,
    GoalLink,
    GoalSetting,
    IdeaMemo,
    ListComment,
    MonthlyGoal,
    Profile,
    TodayTask,
    WeeklyGoal,
    YearlyGoal,
    YearPlan,
)


NAME_MAX_LENGTH = 15
USERNAME_MAX_LENGTH = 15
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
USERNAME_LETTER_PATTERN = re.compile(r"[A-Za-z]")
PROFILE_IMAGE_MAX_BYTES = 15 * 1024 * 1024
GOAL_IMAGE_MAX_BYTES = 20 * 1024 * 1024
PROFILE_IMAGE_MAX_EDGE = 1200
GOAL_IMAGE_MAX_EDGE = 2000
BLOCKED_IMAGE_FORMATS = {"BMP", "DIB", "GIF", "TIFF"}
IMAGE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
PRESERVED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
IMAGE_ACCEPT_ATTR = "image/*"
UNREADABLE_IMAGE_ERROR = "この画像を読み込めませんでした。別の画像を選択してください。"


def safe_image_name(prefix, image_format):
    return f"{prefix}-{uuid.uuid4().hex}.{IMAGE_EXTENSIONS[image_format]}"


def output_format_for_image(image_format):
    if image_format in PRESERVED_IMAGE_FORMATS:
        return image_format
    return "JPEG"


def validate_and_prepare_image(
    source,
    *,
    max_bytes,
    max_edge,
    size_error,
    output_prefix,
):
    if hasattr(source, "size") and source.size and source.size > max_bytes:
        raise forms.ValidationError(size_error)

    try:
        raw = source.read() if hasattr(source, "read") else bytes(source)
    except (OSError, TypeError, ValueError) as exc:
        raise forms.ValidationError(UNREADABLE_IMAGE_ERROR) from exc

    if hasattr(source, "seek"):
        source.seek(0)

    if len(raw) > max_bytes:
        raise forms.ValidationError(size_error)
    if not raw:
        raise forms.ValidationError(UNREADABLE_IMAGE_ERROR)

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            image_format = (opened.format or "").upper()
            if image_format in BLOCKED_IMAGE_FORMATS:
                raise forms.ValidationError(UNREADABLE_IMAGE_ERROR)
            image = ImageOps.exif_transpose(opened)
            image.load()
    except forms.ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise forms.ValidationError(UNREADABLE_IMAGE_ERROR) from exc

    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    output = io.BytesIO()
    save_kwargs = {}
    output_format = output_format_for_image(image_format)
    if output_format == "JPEG":
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        save_kwargs = {"quality": 85, "optimize": True}
    elif output_format == "PNG":
        save_kwargs = {"optimize": True}
    elif output_format == "WEBP":
        save_kwargs = {"quality": 85, "method": 6}

    image.save(output, format=output_format, **save_kwargs)
    return ContentFile(output.getvalue(), name=safe_image_name(output_prefix, output_format))


def normalize_username(value):
    return (value or "").strip().lower()


def validate_display_name(value):
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError("表示名を入力してください。")
    if len(value) > NAME_MAX_LENGTH:
        raise forms.ValidationError("表示名は15文字以内で入力してください。")
    return value


def validate_username_value(value, *, user=None):
    username = normalize_username(value)
    if not username:
        raise forms.ValidationError("ユーザーネームを入力してください。")
    if len(username) > USERNAME_MAX_LENGTH:
        raise forms.ValidationError("ユーザーネームは15文字以内で入力してください。")
    if not USERNAME_PATTERN.fullmatch(username):
        raise forms.ValidationError("ユーザーネームは英数字とアンダースコアのみ使用できます。")
    if not USERNAME_LETTER_PATTERN.search(username):
        raise forms.ValidationError("ユーザーネームにはアルファベットを1文字以上含めてください。")
    queryset = get_user_model().objects.filter(username__iexact=username)
    if user is not None:
        queryset = queryset.exclude(pk=user.pk)
    if queryset.exists():
        raise forms.ValidationError("このユーザーネームはすでに使用されています。")
    return username


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format=None):
        attrs = attrs or {}
        css_class = attrs.get("class", "")
        attrs["class"] = f"{css_class} complete-date-input".strip()
        super().__init__(attrs=attrs, format=format)


class GoalSettingForm(forms.ModelForm):
    class Meta:
        model = GoalSetting
        fields = ["year", "target_count"]
        widgets = {
            "year": forms.NumberInput(attrs={"min": 2000, "max": 2100}),
        }


class CollaboratorSelectMultiple(forms.SelectMultiple):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value:
            user = getattr(value, "instance", None)
            if user is None:
                user = self.choices.queryset.filter(pk=value).first()
            if user:
                # Guard against users that do not have a Profile instance.
                try:
                    profile = user.profile
                except Exception:
                    profile = None

                display_name = (getattr(profile, "display_name", None) or user.username)
                option["attrs"]["data-display-name"] = display_name
                option["attrs"]["data-username"] = user.username
                avatar = ""
                if profile is not None and getattr(profile, "icon", None):
                    try:
                        avatar = profile.icon.url or ""
                    except Exception:
                        avatar = ""
                option["attrs"]["data-avatar"] = avatar
                option["attrs"]["data-initial"] = (display_name or user.username or "?").strip()[:1]
        return option


class YearPlanForm(forms.ModelForm):
    TITLE_MAX_LENGTH = 30
    DESCRIPTION_MAX_LENGTH = 50
    list_title = forms.CharField(
        label="リスト名",
        required=True,
        max_length=TITLE_MAX_LENGTH,
        error_messages={"max_length": "リスト名は30文字以内で入力してください。"},
    )

    class Meta:
        model = YearPlan
        fields = ["list_title", "description", "target_count", "is_public", "is_collaborative", "collaborators"]
        labels = {
            "list_title": "リスト名",
            "description": "説明",
            "target_count": "目標数",
            "is_public": "このリストを公開する",
            "is_collaborative": "共同リストにする",
            "collaborators": "共同編集メンバー",
        }
        widgets = {
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "どんなリストか、ひとことメモを書けます。",
                "data-character-counter": "year-plan-description-counter",
            }),
            "collaborators": CollaboratorSelectMultiple(attrs={
                "class": "collaborator-select",
                "data-collaborator-select": "true",
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collaborators"].required = False
        self.fields["description"].max_length = self.DESCRIPTION_MAX_LENGTH
        self.fields["description"].error_messages["max_length"] = "説明は50文字以内で入力してください。"
        self.fields["list_title"].widget.attrs.pop("maxlength", None)
        self.fields["description"].widget.attrs.pop("maxlength", None)
        self.fields["list_title"].widget.attrs["data-character-counter"] = "year-plan-title-counter"
        self.fields["collaborators"].help_text = "承認済みフォロー関係のあるユーザーから検索して招待できます。"
        if user is None or not user.is_authenticated:
            self.fields["collaborators"].queryset = get_user_model().objects.none()
            return

        # Initial candidate list (what the server renders into the <select>)
        # should be only users that the current user is following (excluding self).
        # This keeps the initial UI focused and small. The full user list for
        # search is provided separately to the template as JSON by the view.
        from .models import Follow

        following_ids = Follow.objects.filter(follower=user).values_list("following_id", flat=True)
        allowed_ids = set(following_ids)
        instance = getattr(self, "instance", None)
        if instance and instance.pk:
            allowed_ids.update(instance.collaborators.values_list("pk", flat=True))
            pending_ids = CollaborationInvite.objects.filter(
                list=instance,
                status=CollaborationInvite.STATUS_PENDING,
            ).values_list("invitee_id", flat=True)
            allowed_ids.update(pending_ids)

        self.fields["collaborators"].queryset = (
            get_user_model().objects.filter(Q(pk__in=following_ids) | Q(pk__in=allowed_ids)).exclude(pk=user.pk)
            .distinct()
            .order_by("username")
        )

        if instance and instance.pk and not self.is_bound:
            preselected_ids = list(instance.collaborators.values_list("pk", flat=True))
            preselected_ids.extend(
                CollaborationInvite.objects.filter(
                    list=instance,
                    status=CollaborationInvite.STATUS_PENDING,
                ).values_list("invitee_id", flat=True)
            )
            self.initial["collaborators"] = list(dict.fromkeys(preselected_ids))



class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="ユーザーネーム",
        widget=forms.TextInput(attrs={
            "autofocus": True,
            "autocomplete": "username",
            "placeholder": "ユーザーネームを入力",
        }),
    )

    def clean(self):
        username = normalize_username(self.cleaned_data.get("username"))
        password = self.cleaned_data.get("password")
        if username and password:
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password,
            )
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class SignUpForm(UserCreationForm):
    display_name = forms.CharField(
        label="表示名",
        max_length=NAME_MAX_LENGTH,
        help_text="15文字以内。絵文字も使用できます。",
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "autocapitalize": "off",
            "spellcheck": "false",
            "maxlength": NAME_MAX_LENGTH,
            "placeholder": "",
        }),
    )
    username = forms.CharField(
        label="ユーザーネーム",
        max_length=USERNAME_MAX_LENGTH,
        help_text="15文字以内の半角英数字と _ が使用できます。アルファベットを1文字以上含めてください。",
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "autocapitalize": "off",
            "spellcheck": "false",
            "maxlength": USERNAME_MAX_LENGTH,
            "placeholder": "",
        }),
    )
    email = forms.EmailField(
        label="メールアドレス",
        required=True,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    class Meta:
        model = get_user_model()
        fields = ["display_name", "username", "email", "password1", "password2"]

    def clean_display_name(self):
        return validate_display_name(self.cleaned_data.get("display_name"))

    def clean_username(self):
        return validate_username_value(self.cleaned_data.get("username"))

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("このメールアドレスはすでに登録されています。")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["username"]
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = self.cleaned_data["display_name"]
            profile.save(update_fields=["display_name"])
        return user


class AccountEmailChangeForm(forms.Form):
    email = forms.EmailField(
        label="メールアドレス",
        required=True,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["email"].initial = user.email

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        queryset = get_user_model().objects.filter(email__iexact=email)
        if self.user is not None:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
            raise forms.ValidationError("このメールアドレスはすでに登録されています。")
        return email


class ProfilePrivacyToggleForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["is_private"]


class ProfileForm(forms.ModelForm):
    avatar_crop_data = forms.CharField(required=False, widget=forms.HiddenInput)
    icon = forms.FileField(
        label="プロフィール画像",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT_ATTR}),
    )
    username = forms.CharField(
        label="ユーザーネーム",
        max_length=USERNAME_MAX_LENGTH,
        help_text="15文字以内の半角英数字と _ が使用できます。アルファベットを1文字以上含めてください。",
        widget=forms.TextInput(attrs={
            "autocomplete": "username",
            "maxlength": USERNAME_MAX_LENGTH,
            "placeholder": "yuuka_25",
        }),
    )
    BIO_MAX_LENGTH = 150

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        self.processed_avatar_file = None
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["username"].initial = user.username

    class Meta:
        model = Profile
        fields = ["display_name", "username", "bio", "icon"]
        labels = {
            "display_name": "表示名",
            "bio": "自己紹介",
            "icon": "プロフィール画像",
        }
        widgets = {
            "display_name": forms.TextInput(attrs={
                "maxlength": NAME_MAX_LENGTH,
                "placeholder": "ゆうか🎀",
            }),
            "bio": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "自己紹介を書いてください",
                "maxlength": 150,
                "data-character-counter": "profile-bio-counter",
            }),
        }

    def clean_display_name(self):
        return validate_display_name(self.cleaned_data.get("display_name"))

    def clean_username(self):
        return validate_username_value(self.cleaned_data.get("username"), user=self.user)

    def clean_icon(self):
        icon = self.cleaned_data.get("icon")
        if not icon:
            return icon
        return validate_and_prepare_image(
            icon,
            max_bytes=PROFILE_IMAGE_MAX_BYTES,
            max_edge=PROFILE_IMAGE_MAX_EDGE,
            size_error="プロフィール画像は15MB以下の画像を選択してください。",
            output_prefix="profile",
        )

    def clean_avatar_crop_data(self):
        crop_data = self.cleaned_data.get("avatar_crop_data") or ""
        if not crop_data:
            return crop_data
        if not crop_data.startswith("data:image"):
            raise forms.ValidationError("プロフィール画像として読み込めないデータです。")
        try:
            _header, encoded = crop_data.split(",", 1)
            decoded = base64.b64decode(encoded)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise forms.ValidationError("プロフィール画像として読み込めないデータです。") from exc
        self.processed_avatar_file = validate_and_prepare_image(
            decoded,
            max_bytes=PROFILE_IMAGE_MAX_BYTES,
            max_edge=PROFILE_IMAGE_MAX_EDGE,
            size_error="プロフィール画像は15MB以下の画像を選択してください。",
            output_prefix="profile",
        )
        return crop_data

    def save(self, commit=True):
        profile = super().save(commit=commit)
        username = self.cleaned_data.get("username")
        if self.user is not None and username and self.user.username != username:
            if commit:
                self.user.username = username
                self.user.save(update_fields=["username"])
        return profile


class ProfilePrivacyForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["is_private"]
        labels = {
            "is_private": "鍵アカウントにする",
        }


class ListCommentForm(forms.ModelForm):
    class Meta:
        model = ListComment
        fields = ["body"]
        labels = {"body": "コメント"}
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "コメントを書く"})}


class YearlyGoalCreateForm(forms.ModelForm):
    class Meta:
        model = YearlyGoal
        fields = ["title", "description", "category", "item_is_public"]
        labels = {
            "title": "やりたいこと",
            "description": "メモ",
            "category": "カテゴリ",
            "item_is_public": "この項目を公開する",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class YearlyGoalInlineCreateForm(forms.ModelForm):
    class Meta:
        model = YearlyGoal
        fields = ["title", "category", "item_is_public", "description"]
        labels = {
            "title": "やりたいこと",
            "category": "カテゴリ",
            "item_is_public": "この項目を公開する",
            "description": "メモ",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "やりたいことを入力してください",
                "autocomplete": "off",
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "メモがあればここに書いてください",
            }),
        }


class YearlyGoalInlineUpdateForm(forms.ModelForm):
    class Meta:
        model = YearlyGoal
        fields = ["title", "category", "item_is_public", "description"]
        labels = {
            "title": "やりたいこと",
            "category": "カテゴリ",
            "item_is_public": "この項目を公開する",
            "description": "メモ",
        }


class YearlyGoalForm(forms.ModelForm):
    is_done = forms.ChoiceField(
        choices=[("0", "未完了"), ("1", "完了済み")],
        label="完了状態",
    )

    class Meta:
        model = YearlyGoal
        fields = ["title", "description", "completed_note", "category", "item_is_public", "is_done", "completed_date"]
        labels = {
            "title": "やりたいこと",
            "description": "下調べ・記録",
            "completed_note": "達成後の記録",
            "category": "カテゴリ",
            "item_is_public": "この項目を公開する",
            "is_done": "完了状態",
            "completed_date": "完了日",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "completed_note": forms.Textarea(attrs={"rows": 4, "placeholder": "行った感想や達成後の記録を書けます"}),
            "completed_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial_done = "1" if self.instance and self.instance.pk and self.instance.is_done else "0"
        self.fields["is_done"].initial = initial_done
        self.initial["is_done"] = initial_done

    def clean(self):
        cleaned_data = super().clean()
        is_done = cleaned_data.get("is_done") == "1"
        cleaned_data["is_done"] = is_done
        completed_date = cleaned_data.get("completed_date")
        if is_done and not completed_date:
            self.add_error("completed_date", "完了済みにする場合は完了日を選択してください。")
        if not is_done:
            cleaned_data["completed_date"] = None
        return cleaned_data


class GoalLinkForm(forms.ModelForm):
    class Meta:
        model = GoalLink
        fields = ["title", "url"]
        labels = {
            "title": "タイトル",
            "url": "URL",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "Googleマップ、公式サイトなど",
                "autocomplete": "off",
            }),
            "url": forms.URLInput(attrs={
                "placeholder": "https://example.com",
                "autocomplete": "url",
            }),
        }


class GoalImageForm(forms.ModelForm):
    image = forms.FileField(
        label="画像",
        required=True,
        widget=forms.ClearableFileInput(attrs={"accept": IMAGE_ACCEPT_ATTR}),
    )

    class Meta:
        model = GoalImage
        fields = ["image", "caption"]
        labels = {
            "image": "画像",
            "caption": "キャプション",
        }
        widgets = {
            "caption": forms.TextInput(attrs={
                "placeholder": "任意でメモを書けます",
                "autocomplete": "off",
            }),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image:
            return image
        return validate_and_prepare_image(
            image,
            max_bytes=GOAL_IMAGE_MAX_BYTES,
            max_edge=GOAL_IMAGE_MAX_EDGE,
            size_error="画像は20MB以下の画像を選択してください。",
            output_prefix="goal",
        )


class MonthlyGoalForm(forms.ModelForm):
    class Meta:
        model = MonthlyGoal
        fields = ["target_month", "title", "is_done"]
        labels = {
            "target_month": "対象月",
            "title": "今月やること",
            "is_done": "完了",
        }
        widgets = {"target_month": DateInput()}

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            today = timezone.localdate()
            self.fields["target_month"].initial = today.replace(day=1)


class WeeklyGoalForm(forms.ModelForm):
    class Meta:
        model = WeeklyGoal
        fields = ["week_start_date", "title", "is_done"]
        labels = {
            "week_start_date": "週の開始日",
            "title": "今週やること",
            "is_done": "完了",
        }
        widgets = {"week_start_date": DateInput()}

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            today = timezone.localdate()
            self.fields["week_start_date"].initial = today - timedelta(days=today.weekday())


class TodayTaskForm(forms.ModelForm):
    class Meta:
        model = TodayTask
        fields = ["scheduled_date", "title", "is_done"]
        labels = {
            "scheduled_date": "予定日",
            "title": "今日やること",
            "is_done": "完了",
        }
        widgets = {"scheduled_date": DateInput()}

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["scheduled_date"].initial = timezone.localdate()


class IdeaMemoForm(forms.ModelForm):
    class Meta:
        model = IdeaMemo
        fields = ["title", "note"]
        labels = {
            "title": "タイトル",
            "note": "メモ",
        }
        widgets = {
            "note": forms.Textarea(attrs={"rows": 4}),
        }
