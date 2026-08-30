from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from goals.models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    IdeaMemo,
    LikeList,
    ListComment,
    MonthlyGoal,
    SavedItem,
    SavedList,
    TodayTask,
    TogetherRequest,
    WantToTry,
    WeeklyGoal,
    YearPlan,
    YearlyGoal,
)


class Command(BaseCommand):
    help = "指定したユーザー以外の開発データを削除します。デフォルトは件数確認のみです。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            nargs="+",
            required=True,
            help="残すユーザー名をスペース区切りで指定します。例: --keep hana chiro mika",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="指定した場合のみ実際に削除します。未指定なら削除対象件数だけ表示します。",
        )
        parser.add_argument(
            "--include-superusers",
            action="store_true",
            help="superuserも削除対象に含めます。通常は安全のため除外します。",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        keep_usernames = set(options["keep"])
        existing_keep = set(User.objects.filter(username__in=keep_usernames).values_list("username", flat=True))
        missing = sorted(keep_usernames - existing_keep)
        if missing:
            raise CommandError(f"残すユーザーが見つかりません: {', '.join(missing)}")

        target_users = User.objects.exclude(username__in=keep_usernames)
        if not options["include_superusers"]:
            target_users = target_users.exclude(is_superuser=True)
        target_user_ids = list(target_users.values_list("pk", flat=True))

        related_counts = {
            "削除対象ユーザー": target_users.count(),
            "プロフィール": target_users.filter(profile__isnull=False).count(),
            "マイリスト": YearPlan.objects.filter(user_id__in=target_user_ids).count(),
            "リスト項目": YearlyGoal.objects.filter(
                Q(user_id__in=target_user_ids) | Q(year_plan__user_id__in=target_user_ids)
            ).distinct().count(),
            "月TODO": MonthlyGoal.objects.filter(user_id__in=target_user_ids).count(),
            "週TODO": WeeklyGoal.objects.filter(user_id__in=target_user_ids).count(),
            "今日TODO": TodayTask.objects.filter(user_id__in=target_user_ids).count(),
            "思いつきメモ": IdeaMemo.objects.filter(user_id__in=target_user_ids).count(),
            "いいね": LikeList.objects.filter(Q(user_id__in=target_user_ids) | Q(my_list__user_id__in=target_user_ids)).distinct().count(),
            "保存リスト": SavedList.objects.filter(Q(user_id__in=target_user_ids) | Q(my_list__user_id__in=target_user_ids)).distinct().count(),
            "保存項目": SavedItem.objects.filter(Q(user_id__in=target_user_ids) | Q(item__year_plan__user_id__in=target_user_ids)).distinct().count(),
            "これもやりたい": WantToTry.objects.filter(Q(user_id__in=target_user_ids) | Q(source_item__year_plan__user_id__in=target_user_ids)).distinct().count(),
            "フォロー関係": Follow.objects.filter(Q(follower_id__in=target_user_ids) | Q(following_id__in=target_user_ids)).distinct().count(),
            "フォロー申請": FollowRequest.objects.filter(Q(requester_id__in=target_user_ids) | Q(target_id__in=target_user_ids)).distinct().count(),
            "共同編集招待": CollaborationInvite.objects.filter(
                Q(inviter_id__in=target_user_ids) | Q(invitee_id__in=target_user_ids) | Q(list__user_id__in=target_user_ids)
            ).distinct().count(),
            "一緒にやりたい申請": TogetherRequest.objects.filter(
                Q(requester_id__in=target_user_ids) | Q(receiver_id__in=target_user_ids) | Q(list_item__year_plan__user_id__in=target_user_ids)
            ).distinct().count(),
            "コメント": ListComment.objects.filter(Q(user_id__in=target_user_ids) | Q(my_list__user_id__in=target_user_ids)).distinct().count(),
        }

        self.stdout.write("残すユーザー: " + ", ".join(sorted(keep_usernames)))
        if not options["include_superusers"]:
            self.stdout.write("superuserは安全のため削除対象から除外しています。")
        self.stdout.write("削除対象件数:")
        for label, count in related_counts.items():
            self.stdout.write(f"- {label}: {count}")

        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("dry-runです。削除する場合は --confirm を付けて再実行してください。"))
            return

        deleted_count, _ = target_users.delete()
        self.stdout.write(self.style.SUCCESS(f"削除しました: {deleted_count} objects"))
