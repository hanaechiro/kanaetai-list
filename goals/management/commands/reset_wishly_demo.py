from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from goals.demo_profile_icons import apply_demo_profile_icon
from goals.models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    LikeList,
    Profile,
    SavedItem,
    SavedList,
    YearPlan,
    YearlyGoal,
)


DEMO_USERS = {
    "hana": {"display": "Hana", "private": False},
    "chiro": {"display": "Chiro", "private": False},
    "mika": {"display": "Mika", "private": False},
    "rina": {"display": "Rina", "private": True},
    "yuki": {"display": "Yuki", "private": False},
    "sora": {"display": "Sora", "private": False},
    "aoi": {"display": "Aoi", "private": True},
}


LIST_BLUEPRINTS = [
    {
        "title": "2026年やりたいこと",
        "target": 20,
        "public": True,
        "items": [
            ("沖縄旅行に行く", "travel"),
            ("本を20冊読む", "study"),
            ("月3万円貯金する", "money"),
            ("朝の散歩を習慣にする", "health"),
            ("新しい趣味を始める", "hobby"),
        ],
    },
    {
        "title": "秘密の準備リスト",
        "target": 10,
        "public": False,
        "items": [
            ("転職の条件を整理する", "work"),
            ("家計を見直す", "money"),
            ("勉強時間を確保する", "study"),
        ],
    },
    {
        "title": "達成済みミニリスト",
        "target": 10,
        "public": True,
        "completed": True,
        "items": [
            ("気になっていたカフェに行く", "hobby"),
            ("部屋の引き出しを整理する", "other"),
            ("朝ごはんを丁寧に作る", "health"),
            ("映画を一本見る", "hobby"),
            ("友達に近況を送る", "other"),
            ("読みかけの本を読む", "study"),
            ("財布の中を整える", "money"),
            ("散歩コースを変える", "health"),
            ("花を飾る", "hobby"),
            ("写真を整理する", "other"),
        ],
    },
]


class Command(BaseCommand):
    help = "Wishlyの開発確認用ユーザーとダミーデータを作り直します。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-existing",
            action="store_true",
            help="既存の開発用ユーザーを削除せず、不足分だけ作成します。",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        usernames = list(DEMO_USERS.keys())
        if not options["keep_existing"]:
            User.objects.filter(username__in=usernames, is_superuser=False).delete()

        users = {}
        for username, spec in DEMO_USERS.items():
            user, created = User.objects.get_or_create(username=username)
            user.set_password("wishly-demo")
            user.email = f"{username}@example.com"
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = spec["display"]
            profile.bio = f"{spec['display']}の叶えたいことノートです。"
            profile.is_private = spec["private"]
            apply_demo_profile_icon(profile, username)
            profile.save()
            users[username] = user
            self.stdout.write(f"{'created' if created else 'updated'} user: {username}")

        today = timezone.localdate()
        for username, user in users.items():
            if options["keep_existing"]:
                YearPlan.objects.filter(user=user, list_title__in=[b["title"] for b in LIST_BLUEPRINTS]).delete()
            for index, blueprint in enumerate(LIST_BLUEPRINTS):
                plan = YearPlan.objects.create(
                    user=user,
                    year=today.year,
                    list_title=blueprint["title"],
                    target_count=blueprint["target"],
                    is_public=blueprint["public"],
                    is_collaborative=False,
                )
                for item_index, (title, category) in enumerate(blueprint["items"], start=1):
                    is_done = bool(blueprint.get("completed") or item_index % 4 == 0)
                    YearlyGoal.objects.create(
                        user=user,
                        year_plan=plan,
                        title=title,
                        category=category,
                        item_is_public=item_index % 5 != 0,
                        is_done=is_done,
                        completed_date=today if is_done else None,
                        added_by=user,
                        completed_by=user if is_done else None,
                    )

        hana = users["hana"]
        chiro = users["chiro"]
        mika = users["mika"]
        rina = users["rina"]
        yuki = users["yuki"]
        sora = users["sora"]
        aoi = users["aoi"]

        for follower, following in [
            (hana, mika),
            (hana, yuki),
            (hana, sora),
            (chiro, hana),
            (mika, hana),
            (yuki, hana),
            (sora, mika),
        ]:
            Follow.objects.get_or_create(follower=follower, following=following)

        FollowRequest.objects.update_or_create(
            requester=hana,
            target=rina,
            defaults={"status": FollowRequest.STATUS_PENDING},
        )
        FollowRequest.objects.update_or_create(
            requester=chiro,
            target=aoi,
            defaults={"status": FollowRequest.STATUS_PENDING},
        )

        collaborative_plan = YearPlan.objects.create(
            user=hana,
            year=today.year,
            list_title="友達と作る週末リスト",
            target_count=10,
            is_public=True,
            is_collaborative=True,
        )
        collaborative_plan.collaborators.add(mika)
        for title, category in [
            ("気になる展示を見に行く", "hobby"),
            ("新しいカフェで作戦会議する", "hobby"),
            ("日帰りで海を見に行く", "travel"),
        ]:
            YearlyGoal.objects.create(
                user=hana,
                year_plan=collaborative_plan,
                title=title,
                category=category,
                item_is_public=True,
                added_by=hana,
            )
        CollaborationInvite.objects.update_or_create(
            list=collaborative_plan,
            invitee=chiro,
            defaults={
                "inviter": hana,
                "status": CollaborationInvite.STATUS_PENDING,
                "responded_at": None,
            },
        )

        public_plans = YearPlan.objects.filter(is_public=True).exclude(user=hana)
        for plan in public_plans[:4]:
            LikeList.objects.get_or_create(user=hana, my_list=plan)
            SavedList.objects.get_or_create(user=hana, my_list=plan)
            first_item = plan.goals.filter(item_is_public=True).first()
            if first_item:
                SavedItem.objects.get_or_create(user=hana, item=first_item)

        self.stdout.write(self.style.SUCCESS("Wishly demo data is ready."))
        self.stdout.write("login users: hana / chiro / mika / rina / yuki / sora / aoi")
        self.stdout.write("password: wishly-demo")
