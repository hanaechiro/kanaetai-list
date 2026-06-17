from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import GoalSetting, IdeaMemo, ListComment, MonthlyGoal, Profile, TodayTask, WeeklyGoal, YearlyGoal, YearPlan


class DateInput(forms.DateInput):
    input_type = "date"


class GoalSettingForm(forms.ModelForm):
    class Meta:
        model = GoalSetting
        fields = ["year", "target_count"]
        widgets = {
            "year": forms.NumberInput(attrs={"min": 2000, "max": 2100}),
        }


class YearPlanForm(forms.ModelForm):
    class Meta:
        model = YearPlan
        fields = ["list_title", "target_count", "is_public"]
        labels = {
            "list_title": "リスト名",
            "target_count": "目標数",
            "is_public": "このリストを公開する",
        }


class SignUpForm(UserCreationForm):
    class Meta:
        model = get_user_model()
        fields = ["username", "password1", "password2"]


class ProfileForm(forms.ModelForm):
    avatar_crop_data = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Profile
        fields = ["display_name", "bio", "icon"]
        widgets = {
            "display_name": forms.TextInput(attrs={
                "class": "app-input",
                "placeholder": "表示名",
            }),
            "bio": forms.Textarea(attrs={
                "class": "app-textarea",
                "rows": 4,
                "placeholder": "自己紹介を書いてください",
            }),
            "icon": forms.ClearableFileInput(attrs={
                "class": "app-file-input",
                "accept": "image/*",
            }),
        }


class ListCommentForm(forms.ModelForm):
    class Meta:
        model = ListComment
        fields = ["body"]
        labels = {
            "body": "コメント",
        }


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
                "placeholder": "メモがあればここに書く",
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
        fields = ["title", "description", "category", "item_is_public", "is_done", "completed_date"]
        labels = {
            "title": "やりたいこと",
            "description": "メモ",
            "category": "カテゴリ",
            "item_is_public": "この項目を公開する",
            "is_done": "完了状態",
            "completed_date": "完了日",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "completed_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_done"].initial = "1" if self.instance and self.instance.is_done else "0"

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


class MonthlyGoalForm(forms.ModelForm):
    class Meta:
        model = MonthlyGoal
        fields = ["target_month", "title", "is_done"]
        labels = {
            "target_month": "対象月",
            "title": "今月やること",
            "is_done": "完了",
        }
        widgets = {
            "target_month": DateInput(),
        }

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
            "week_start_date": "対象週の開始日",
            "title": "今週やること",
            "is_done": "完了",
        }
        widgets = {
            "week_start_date": DateInput(),
        }

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
            "title": "やること",
            "is_done": "完了",
        }
        widgets = {
            "scheduled_date": DateInput(),
        }

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["scheduled_date"].initial = timezone.localdate()


class IdeaMemoForm(forms.ModelForm):
    class Meta:
        model = IdeaMemo
        fields = ["title", "note"]
