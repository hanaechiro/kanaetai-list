from django.contrib import admin

from .models import (
    CollaborationInvite,
    FollowRequest,
    GoalSetting,
    IdeaMemo,
    MonthlyGoal,
    Profile,
    TodayTask,
    UserActivity,
    WeeklyGoal,
    YearlyGoal,
    YearPlan,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "is_private")
    list_filter = ("is_private",)
    search_fields = ("user__username", "display_name", "bio")


@admin.register(FollowRequest)
class FollowRequestAdmin(admin.ModelAdmin):
    list_display = ("requester", "target", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("requester__username", "target__username")


@admin.register(CollaborationInvite)
class CollaborationInviteAdmin(admin.ModelAdmin):
    list_display = ("list", "inviter", "invitee", "status", "created_at", "responded_at")
    list_filter = ("status", "created_at")
    search_fields = ("list__list_title", "inviter__username", "invitee__username")


@admin.register(GoalSetting)
class GoalSettingAdmin(admin.ModelAdmin):
    list_display = ("year", "target_count")


@admin.register(YearPlan)
class YearPlanAdmin(admin.ModelAdmin):
    list_display = ("user", "list_title", "year", "target_count", "is_public", "is_collaborative", "created_at")
    list_filter = ("year", "is_public", "is_collaborative", "created_at")
    search_fields = ("user__username",)
    filter_horizontal = ("collaborators",)


@admin.register(YearlyGoal)
class YearlyGoalAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "added_by", "completed_by", "category", "completed_date", "is_done", "is_public", "item_is_public", "created_at")
    list_filter = ("category", "is_done", "is_public", "item_is_public")
    search_fields = ("title", "description")


@admin.register(MonthlyGoal)
class MonthlyGoalAdmin(admin.ModelAdmin):
    list_display = ("title", "month", "yearly_goal", "is_done")
    list_filter = ("month", "is_done")
    search_fields = ("title",)


@admin.register(WeeklyGoal)
class WeeklyGoalAdmin(admin.ModelAdmin):
    list_display = ("title", "week_start", "monthly_goal", "is_done")
    list_filter = ("week_start", "is_done")
    search_fields = ("title",)


@admin.register(TodayTask)
class TodayTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "weekly_goal", "is_done")
    list_filter = ("date", "is_done")
    search_fields = ("title",)


@admin.register(IdeaMemo)
class IdeaMemoAdmin(admin.ModelAdmin):
    list_display = ("title", "created_at")
    search_fields = ("title", "note")


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "last_seen_at", "request_count")
    list_filter = ("date",)
    search_fields = ("user__username", "user__email")

# Register your models here.
