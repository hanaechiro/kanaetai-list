from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from goals.demo_profile_icons import apply_demo_profile_icon
from goals.models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    IdeaMemo,
    LikeList,
    ListComment,
    MonthlyGoal,
    Profile,
    SavedItem,
    SavedList,
    TodayTask,
    TogetherRequest,
    WantToTry,
    WeeklyGoal,
    YearPlan,
    YearlyGoal,
)


PASSWORD = "wishly-demo"

USERS = [
    ("hana", "Hana", False, "私用ユーザー①。通知とフォロー確認に使います。"),
    ("chiro", "Chiro", False, "私用ユーザー②。共同リスト招待の確認に使います。"),
    ("mika", "Mika", False, "旅行とカフェが好きな公開アカウントです。"),
    ("rina", "Rina", True, "美容と自分磨きのリストを作っています。"),
    ("yuki", "Yuki", False, "勉強と読書のリストを育てています。"),
    ("sora", "Sora", False, "お金と暮らしを整えるリストが多めです。"),
    ("aoi", "Aoi", True, "趣味のリストを静かに作っています。"),
]

BASE_LISTS = {
    "travel": {
        "title": "週末に行きたい場所",
        "target": 10,
        "public": True,
        "items": [
            ("海が見えるカフェに行く", "travel"),
            ("朝の美術館に行く", "hobby"),
            ("温泉街を散歩する", "travel"),
            ("新幹線で日帰り旅をする", "travel"),
            ("旅先でポストカードを買う", "hobby"),
        ],
    },
    "beauty": {
        "title": "自分磨きリスト",
        "target": 10,
        "public": True,
        "items": [
            ("眉毛サロンに行く", "beauty"),
            ("スキンケアを見直す", "beauty"),
            ("姿勢改善をする", "health"),
            ("ヘアケア用品を整える", "beauty"),
            ("似合う色を調べる", "beauty"),
        ],
    },
    "study": {
        "title": "勉強したいこと",
        "target": 10,
        "public": True,
        "items": [
            ("英語日記を書く", "study"),
            ("資格試験の日程を調べる", "study"),
            ("読書ノートを作る", "study"),
            ("朝に単語を10個覚える", "study"),
            ("月に2冊読む", "study"),
        ],
    },
    "money": {
        "title": "お金を整える",
        "target": 10,
        "public": True,
        "items": [
            ("欲しいものリストを作る", "money"),
            ("サブスクを整理する", "money"),
            ("家計簿アプリを導入する", "money"),
            ("毎月の貯金額を決める", "money"),
            ("投資の本を1冊読む", "study"),
        ],
    },
    "health": {
        "title": "健康習慣リスト",
        "target": 10,
        "public": True,
        "items": [
            ("毎日8000歩を目指す", "health"),
            ("寝る前にストレッチする", "health"),
            ("水をこまめに飲む", "health"),
            ("睡眠時間を記録する", "health"),
            ("週末に長めの散歩をする", "health"),
        ],
    },
    "hobby": {
        "title": "趣味でやりたいこと",
        "target": 10,
        "public": True,
        "items": [
            ("編み物作品を完成させる", "hobby"),
            ("映画を10本見る", "hobby"),
            ("写真を整理する", "hobby"),
            ("新しいレシピを作る", "hobby"),
            ("カフェ巡りマップを作る", "hobby"),
        ],
    },
}

PRIVATE_LIST = {
    "title": "非公開の準備リスト",
    "target": 5,
    "public": False,
    "items": [
        ("今後の働き方を考える", "work"),
        ("大きな買い物を検討する", "money"),
        ("体調の記録をつける", "health"),
        ("家族の予定を整理する", "other"),
        ("勉強計画を立て直す", "study"),
    ],
}

COMPLETED_LIST = {
    "title": "達成済みリスト",
    "target": 5,
    "public": True,
    "completed": True,
    "items": [
        ("気になっていたカフェに行く", "hobby"),
        ("部屋の引き出しを整理する", "other"),
        ("読みかけの本を読み終える", "study"),
        ("財布の中を整える", "money"),
        ("朝散歩をする", "health"),
    ],
}


USER_LIST_THEMES = {
    "hana": ["travel", "hobby"],
    "chiro": ["study", "money"],
    "mika": ["travel", "hobby"],
    "rina": ["beauty", "health"],
    "yuki": ["study", "hobby"],
    "sora": ["money", "study"],
    "aoi": ["hobby", "beauty"],
}


USER_RELATED_MODELS = [
    ("一緒にやりたい申請", TogetherRequest),
    ("コメント", ListComment),
    ("これもやりたい", WantToTry),
    ("保存項目", SavedItem),
    ("保存リスト", SavedList),
    ("いいね", LikeList),
    ("共同リスト招待", CollaborationInvite),
    ("フォロー申請", FollowRequest),
    ("フォロー関係", Follow),
    ("今日TODO", TodayTask),
    ("週TODO", WeeklyGoal),
    ("月TODO", MonthlyGoal),
    ("思いつきメモ", IdeaMemo),
    ("リスト項目", YearlyGoal),
    ("マイリスト", YearPlan),
    ("プロフィール", Profile),
]


class Command(BaseCommand):
    help = "開発環境の全ユーザー関連データを削除し、Wishlyテスト用データを作り直します。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="指定した場合のみ全削除と再作成を実行します。未指定ならdry-runです。",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        counts = self.current_counts(User)
        self.stdout.write("削除対象件数:")
        for label, count in counts.items():
            self.stdout.write(f"- {label}: {count}")

        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("dry-runです。実行する場合は --confirm を付けてください。"))
            self.stdout.write("実行例: py manage.py reset_demo_data --confirm")
            return

        with transaction.atomic():
            deleted = self.delete_existing_data(User)
            users = self.create_users(User)
            plans = self.create_lists(users)
            self.create_relationships(users, plans)

        self.stdout.write(self.style.SUCCESS("Wishly demo data has been reset."))
        self.stdout.write("削除件数:")
        for label, count in deleted.items():
            self.stdout.write(f"- {label}: {count}")
        self.stdout.write("作成ユーザー:")
        for username, display_name, _, _ in USERS:
            self.stdout.write(f"- {username} / {PASSWORD} ({display_name})")
        self.stdout.write("作成件数:")
        self.stdout.write(f"- ユーザー: {len(users)}")
        self.stdout.write(f"- マイリスト: {YearPlan.objects.count()}")
        self.stdout.write(f"- リスト項目: {YearlyGoal.objects.count()}")
        self.stdout.write(f"- フォロー申請: {FollowRequest.objects.count()}")
        self.stdout.write(f"- 共同リスト招待: {CollaborationInvite.objects.count()}")

    def current_counts(self, User):
        counts = {"ユーザー": User.objects.count()}
        for label, model in USER_RELATED_MODELS:
            counts[label] = model.objects.count()
        return counts

    def delete_existing_data(self, User):
        deleted = {}
        for label, model in USER_RELATED_MODELS:
            count, _ = model.objects.all().delete()
            deleted[label] = count
        count, _ = User.objects.all().delete()
        deleted["ユーザー"] = count
        return deleted

    def create_users(self, User):
        users = {}
        for username, display_name, is_private, bio in USERS:
            user = User.objects.create_user(
                username=username,
                password=PASSWORD,
                email=f"{username}@example.com",
            )
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = display_name
            profile.bio = bio
            profile.is_private = is_private
            apply_demo_profile_icon(profile, username)
            profile.save()
            users[username] = user
        return users

    def create_lists(self, users):
        today = timezone.localdate()
        plans = {}
        for username, user in users.items():
            plans[username] = []
            for theme_key in USER_LIST_THEMES[username]:
                plans[username].append(self.create_plan(user, BASE_LISTS[theme_key], today))
            plans[username].append(self.create_plan(user, PRIVATE_LIST, today))
            plans[username].append(self.create_plan(user, COMPLETED_LIST, today))
            IdeaMemo.objects.create(user=user, title="あとでやりたいことをメモする", note="気になったリストから広げるメモ")
        return plans

    def create_plan(self, user, blueprint, today):
        plan = YearPlan.objects.create(
            user=user,
            year=today.year,
            list_title=blueprint["title"],
            target_count=blueprint["target"],
            is_public=blueprint["public"],
            is_collaborative=False,
        )
        for index, (title, category) in enumerate(blueprint["items"], start=1):
            is_done = bool(blueprint.get("completed") or index in {2, 5})
            YearlyGoal.objects.create(
                user=user,
                year_plan=plan,
                title=title,
                description=f"{plan.list_title}の確認用サンプル項目です。",
                category=category,
                item_is_public=index != 4,
                is_done=is_done,
                completed_date=today if is_done else None,
                added_by=user,
                completed_by=user if is_done else None,
            )
        return plan

    def create_relationships(self, users, plans):
        # Accepted follows for timeline and public/private visibility checks.
        for follower, following in [
            ("hana", "mika"),
            ("hana", "yuki"),
            ("hana", "sora"),
            ("chiro", "hana"),
            ("chiro", "mika"),
            ("mika", "hana"),
            ("yuki", "hana"),
            ("sora", "chiro"),
        ]:
            Follow.objects.get_or_create(follower=users[follower], following=users[following])

        # Pending follow requests for notification accept/reject tests.
        for requester, target in [
            ("mika", "hana"),
            ("yuki", "hana"),
            ("sora", "chiro"),
            ("hana", "rina"),
            ("chiro", "aoi"),
        ]:
            FollowRequest.objects.create(
                requester=users[requester],
                target=users[target],
                status=FollowRequest.STATUS_PENDING,
            )

        # Historical states for visual/admin checks.
        FollowRequest.objects.create(
            requester=users["rina"],
            target=users["hana"],
            status=FollowRequest.STATUS_REJECTED,
        )
        FollowRequest.objects.create(
            requester=users["aoi"],
            target=users["chiro"],
            status=FollowRequest.STATUS_ACCEPTED,
        )

        today = timezone.localdate()
        shared_hana = YearPlan.objects.create(
            user=users["hana"],
            year=today.year,
            list_title="HanaとChiroの共同リスト",
            target_count=10,
            is_public=True,
            is_collaborative=True,
        )
        shared_hana.collaborators.add(users["chiro"])
        CollaborationInvite.objects.create(
            list=shared_hana,
            inviter=users["hana"],
            invitee=users["chiro"],
            status=CollaborationInvite.STATUS_ACCEPTED,
            responded_at=timezone.now(),
        )
        for title, category, added_by in [
            ("一緒に行きたいカフェを決める", "hobby", users["hana"]),
            ("週末の予定を相談する", "other", users["chiro"]),
            ("旅行候補を3つ出す", "travel", users["hana"]),
        ]:
            YearlyGoal.objects.create(
                user=users["hana"],
                year_plan=shared_hana,
                title=title,
                category=category,
                item_is_public=True,
                added_by=added_by,
            )

        invite_plan_hana = YearPlan.objects.create(
            user=users["mika"],
            year=today.year,
            list_title="Hanaを招待中の共同リスト",
            target_count=10,
            is_public=True,
            is_collaborative=True,
        )
        YearlyGoal.objects.create(
            user=users["mika"],
            year_plan=invite_plan_hana,
            title="一緒に東京カフェ巡りをする",
            category="hobby",
            item_is_public=True,
            added_by=users["mika"],
        )
        CollaborationInvite.objects.create(
            list=invite_plan_hana,
            inviter=users["mika"],
            invitee=users["hana"],
            status=CollaborationInvite.STATUS_PENDING,
        )

        invite_plan_chiro = YearPlan.objects.create(
            user=users["yuki"],
            year=today.year,
            list_title="Chiroを招待中の共同リスト",
            target_count=10,
            is_public=False,
            is_collaborative=True,
        )
        YearlyGoal.objects.create(
            user=users["yuki"],
            year_plan=invite_plan_chiro,
            title="資格勉強の進捗を共有する",
            category="study",
            item_is_public=True,
            added_by=users["yuki"],
        )
        CollaborationInvite.objects.create(
            list=invite_plan_chiro,
            inviter=users["yuki"],
            invitee=users["chiro"],
            status=CollaborationInvite.STATUS_PENDING,
        )

        declined_plan = YearPlan.objects.create(
            user=users["sora"],
            year=today.year,
            list_title="拒否済み招待の確認リスト",
            target_count=5,
            is_public=True,
            is_collaborative=True,
        )
        CollaborationInvite.objects.create(
            list=declined_plan,
            inviter=users["sora"],
            invitee=users["hana"],
            status=CollaborationInvite.STATUS_DECLINED,
            responded_at=timezone.now(),
        )

        for viewer in [users["hana"], users["chiro"]]:
            for owner in ["mika", "yuki", "sora"]:
                public_plan = next(plan for plan in plans[owner] if plan.is_public)
                LikeList.objects.get_or_create(user=viewer, my_list=public_plan)
                SavedList.objects.get_or_create(user=viewer, my_list=public_plan)
                first_public_item = public_plan.goals.filter(item_is_public=True).first()
                if first_public_item:
                    SavedItem.objects.get_or_create(user=viewer, item=first_public_item)
                    WantToTry.objects.get_or_create(user=viewer, source_item=first_public_item)

        target_item = plans["mika"][0].goals.filter(item_is_public=True).first()
        if target_item:
            TogetherRequest.objects.create(
                requester=users["hana"],
                receiver=users["mika"],
                list_item=target_item,
                status=TogetherRequest.STATUS_PENDING,
                message="一緒に行ってみたいです。",
            )
