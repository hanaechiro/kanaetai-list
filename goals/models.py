from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class GoalSetting(models.Model):
    TARGET_CHOICES = [
        (10, "10個"),
        (20, "20個"),
        (30, "30個"),
        (50, "50個"),
        (70, "70個"),
        (100, "100個"),
    ]

    year = models.PositiveIntegerField(unique=True)
    target_count = models.PositiveIntegerField(choices=TARGET_CHOICES, default=100)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return f"{self.year}年: {self.target_count}個"


class YearPlan(models.Model):
    TARGET_CHOICES = GoalSetting.TARGET_CHOICES

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        related_name="year_plans",
    )
    year = models.PositiveIntegerField("Year")
    list_title = models.CharField("リスト名", max_length=30, blank=True)
    description = models.TextField("説明", max_length=50, blank=True)
    icon = models.CharField("アイコン", max_length=20, blank=True, default="checklist")
    target_count = models.PositiveIntegerField("Target count", choices=TARGET_CHOICES, default=100)
    is_public = models.BooleanField("この年のリストを公開する", default=False)
    is_collaborative = models.BooleanField("共同リスト", default=False)
    template_slug = models.SlugField("Template slug", max_length=80, blank=True, db_index=True)
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="collaborating_year_plans",
    )
    share_count = models.PositiveIntegerField("Share count", default=0)
    created_at = models.DateTimeField("Created at", auto_now_add=True, blank=True, null=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return self.list_title or f"{self.user}: {self.year}年"


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField("表示名", max_length=15)
    bio = models.TextField("自己紹介", max_length=150, blank=True)
    icon = models.ImageField("プロフィールアイコン", upload_to="profile_icons/", blank=True, null=True)

    email_verified = models.BooleanField("Email verified", default=False)
    is_private = models.BooleanField("鍵アカウント", default=True)
    last_notification_seen = models.DateTimeField("最後に通知を確認した日時", null=True, blank=True)

    def __str__(self):
        return self.display_name or self.user.username


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance, display_name=instance.username, is_private=True)
    else:
        Profile.objects.get_or_create(user=instance)


class YearlyGoal(models.Model):
    CATEGORY_CHOICES = [
        ("travel", "旅行"),
        ("beauty", "美容"),
        ("study", "勉強"),
        ("work", "仕事"),
        ("hobby", "趣味"),
        ("health", "健康"),
        ("money", "お金"),
        ("other", "その他"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="yearly_goals",
    )
    year_plan = models.ForeignKey(
        YearPlan,
        verbose_name="マイリスト",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="goals",
    )
    title = models.CharField("やりたいこと", max_length=200)
    description = models.TextField("メモ", blank=True)
    completed_note = models.TextField("達成後の記録", blank=True)
    category = models.CharField("カテゴリ", max_length=20, choices=CATEGORY_CHOICES, default="other")
    planned_date = models.DateField("予定日", blank=True, null=True)
    completed_date = models.DateField("完了日", blank=True, null=True)
    is_done = models.BooleanField("達成済み", default=False)
    is_public = models.BooleanField("公開する", default=False)
    item_is_public = models.BooleanField("この項目を公開する", default=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="added_yearly_goals",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="completed_yearly_goals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["is_done", "-created_at"]

    def __str__(self):
        return self.title


class GoalLink(models.Model):
    goal = models.ForeignKey(
        YearlyGoal,
        verbose_name="やりたいこと",
        on_delete=models.CASCADE,
        related_name="links",
    )
    title = models.CharField("リンクタイトル", max_length=120, blank=True)
    url = models.URLField("URL")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.url


class GoalImage(models.Model):
    goal = models.ForeignKey(
        YearlyGoal,
        verbose_name="やりたいこと",
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField("画像", upload_to="goal_images/")
    caption = models.CharField("キャプション", max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.caption or f"{self.goal}の画像"


class MonthlyGoal(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="monthly_todos",
    )
    month = models.DateField("対象月")
    target_month = models.DateField("対象月", blank=True, null=True)
    title = models.CharField("月の目標", max_length=200)
    yearly_goal = models.ForeignKey(
        YearlyGoal,
        verbose_name="紐づく年間目標",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="monthly_goals",
    )
    is_done = models.BooleanField("達成済み", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-target_month", "is_done", "-created_at"]

    def __str__(self):
        return self.title


class WeeklyGoal(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="weekly_todos",
    )
    week_start = models.DateField("週の開始日")
    week_start_date = models.DateField("週の開始日", blank=True, null=True)
    title = models.CharField("週の目標", max_length=200)
    monthly_goal = models.ForeignKey(
        MonthlyGoal,
        verbose_name="紐づく月目標",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="weekly_goals",
    )
    is_done = models.BooleanField("達成済み", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-week_start_date", "is_done", "-created_at"]

    def __str__(self):
        return self.title


class TodayTask(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="daily_todos",
    )
    date = models.DateField("日付")
    scheduled_date = models.DateField("予定日", blank=True, null=True)
    title = models.CharField("今日やること", max_length=200)
    weekly_goal = models.ForeignKey(
        WeeklyGoal,
        verbose_name="紐づく週目標",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="today_tasks",
    )
    is_done = models.BooleanField("完了", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_date", "is_done", "-created_at"]

    def __str__(self):
        return self.title


class IdeaMemo(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ユーザー",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="idea_memos",
    )
    title = models.CharField("思いつきメモ", max_length=200)
    note = models.TextField("補足", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class SavedList(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_lists",
    )
    my_list = models.ForeignKey(
        YearPlan,
        on_delete=models.CASCADE,
        related_name="saved_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "my_list"], name="unique_saved_list_per_user"),
        ]

    def __str__(self):
        return f"{self.user} saved {self.my_list}"


class SavedItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_items",
    )
    item = models.ForeignKey(
        YearlyGoal,
        on_delete=models.CASCADE,
        related_name="saved_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "item"], name="unique_saved_item_per_user"),
        ]

    def __str__(self):
        return f"{self.user} saved {self.item}"


class LikeList(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liked_lists",
    )
    my_list = models.ForeignKey(
        YearPlan,
        on_delete=models.CASCADE,
        related_name="liked_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "my_list"], name="unique_like_list_per_user"),
        ]

    def __str__(self):
        return f"{self.user} liked {self.my_list}"


class WantToTry(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wanted_items",
    )
    source_item = models.ForeignKey(
        YearlyGoal,
        on_delete=models.CASCADE,
        related_name="wanted_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "source_item"], name="unique_want_to_try_per_user"),
        ]

    def __str__(self):
        return f"{self.user} wants {self.source_item}"


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="following_relations",
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="follower_relations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["follower", "following"], name="unique_follow_per_user"),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("following")),
                name="prevent_self_follow",
            ),
        ]

    def __str__(self):
        return f"{self.follower} follows {self.following}"


class FollowRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "申請中"),
        (STATUS_ACCEPTED, "承認済み"),
        (STATUS_REJECTED, "却下"),
    ]

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_follow_requests",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_follow_requests",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["requester", "target"], name="unique_follow_request_per_user"),
            models.CheckConstraint(
                condition=~models.Q(requester=models.F("target")),
                name="prevent_self_follow_request",
            ),
        ]

    def __str__(self):
        return f"{self.requester} -> {self.target} ({self.status})"


class CollaborationInvite(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_PENDING, "申請中"),
        (STATUS_ACCEPTED, "参加済み"),
        (STATUS_DECLINED, "拒否"),
    ]

    list = models.ForeignKey(
        YearPlan,
        on_delete=models.CASCADE,
        related_name="collaboration_invites",
    )
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_collaboration_invites",
    )
    invitee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_collaboration_invites",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["list", "invitee"], name="unique_collaboration_invite_per_list"),
            models.CheckConstraint(
                condition=~models.Q(inviter=models.F("invitee")),
                name="prevent_self_collaboration_invite",
            ),
        ]

    def __str__(self):
        return f"{self.inviter} -> {self.invitee} ({self.list})"


class TogetherRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "承認待ち"),
        (STATUS_ACCEPTED, "承認済み"),
        (STATUS_REJECTED, "拒否"),
    ]

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_together_requests",
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_together_requests",
    )
    list_item = models.ForeignKey(
        YearlyGoal,
        on_delete=models.CASCADE,
        related_name="together_requests",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    message = models.TextField("メッセージ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["requester", "list_item"], name="unique_together_request_per_item"),
            models.CheckConstraint(
                condition=~models.Q(requester=models.F("receiver")),
                name="prevent_self_together_request",
            ),
        ]

    def __str__(self):
        return f"{self.requester} -> {self.list_item} ({self.status})"


class ListComment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="list_comments",
    )
    my_list = models.ForeignKey(
        YearPlan,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    body = models.TextField("コメント")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user}: {self.body[:20]}"


class Inquiry(models.Model):
    STATUS_PENDING = "pending"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_PENDING, "未対応"),
        (STATUS_DONE, "対応済み"),
    ]

    name = models.CharField("名前", max_length=80)
    email = models.EmailField("返信先メールアドレス")
    message = models.TextField("問い合わせ内容", max_length=2000)
    status = models.CharField("対応状態", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField("作成日時", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class UserActivity(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wishly_activity",
    )
    date = models.DateField(db_index=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    request_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date", "-last_seen_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_user_activity_per_day"),
        ]

    def __str__(self):
        return f"{self.user} on {self.date}"
