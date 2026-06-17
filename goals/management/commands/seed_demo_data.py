import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from goals.models import Follow, LikeList, Profile, SavedList, YearPlan, YearlyGoal


CATEGORIES = ["travel", "beauty", "study", "work", "hobby", "health", "money", "other"]

DEMO_USERS = [
    {
        "username": "hana",
        "display_name": "Hana",
        "bio": "行きたい場所と作りたいものを、少しずつノートに集めています。",
        "lists": [
            {
                "title": "2026年やりたいこと",
                "target_count": 100,
                "is_public": True,
                "items": [
                    ("沖縄旅行に行く", "travel"),
                    ("本を100冊読む", "study"),
                    ("月5万円貯金する", "money"),
                    ("朝活を習慣にする", "health"),
                    ("編み物作品を10個完成させる", "hobby"),
                    ("富士山を見に行く", "travel"),
                    ("カフェ巡りをする", "hobby"),
                    ("資格の勉強を始める", "study"),
                    ("部屋をかわいく整える", "other"),
                    ("副業の売上を作る", "work"),
                ],
            },
            {
                "title": "編み物で作りたいもの",
                "target_count": 30,
                "is_public": True,
                "items": [
                    ("春色のショールを編む", "hobby"),
                    ("自分用のカーディガンを完成させる", "hobby"),
                    ("友達に小さなポーチを贈る", "hobby"),
                    ("夏用バッグを編む", "hobby"),
                    ("編み図を3つ整理する", "hobby"),
                    ("余り糸でコースターを作る", "hobby"),
                    ("作品写真をきれいに撮る", "hobby"),
                    ("毛糸収納を整える", "other"),
                ],
            },
        ],
    },
    {
        "username": "mika",
        "display_name": "Mika",
        "bio": "東京のカフェと美容のリストを育てています。",
        "lists": [
            {
                "title": "東京カフェ巡り",
                "target_count": 30,
                "is_public": True,
                "items": [
                    ("朝カフェで読書する", "hobby"),
                    ("表参道でラテアートを楽しむ", "hobby"),
                    ("神保町で本屋カフェに行く", "hobby"),
                    ("清澄白河でコーヒー豆を買う", "hobby"),
                    ("月1回カフェ予算を決める", "money"),
                    ("カフェ巡りマップを作る", "hobby"),
                    ("新しいカフェを3件開拓する", "hobby"),
                    ("お気に入り席を写真に残す", "hobby"),
                ],
            },
            {
                "title": "自分磨きリスト",
                "target_count": 50,
                "is_public": False,
                "items": [
                    ("週3回ストレッチする", "health"),
                    ("スキンケアを毎晩続ける", "beauty"),
                    ("似合うリップを見つける", "beauty"),
                    ("健康診断を予約する", "health"),
                    ("寝る前のスマホ時間を減らす", "health"),
                    ("メイクポーチを整理する", "beauty"),
                ],
            },
        ],
    },
    {
        "username": "rina",
        "display_name": "Rina",
        "bio": "仕事と暮らしを整えるリストを作っています。",
        "lists": [
            {
                "title": "仕事で伸ばしたいこと",
                "target_count": 70,
                "is_public": True,
                "items": [
                    ("ポートフォリオを作り直す", "work"),
                    ("資格の勉強を始める", "study"),
                    ("月10分だけ専門書を読む", "study"),
                    ("副業の売上を作る", "work"),
                    ("週1回ふりかえりを書く", "work"),
                    ("プレゼン資料を改善する", "work"),
                    ("作業時間を記録する", "work"),
                    ("新しいツールを1つ試す", "work"),
                ],
            },
            {
                "title": "部屋を整える",
                "target_count": 20,
                "is_public": True,
                "items": [
                    ("本棚を整理する", "other"),
                    ("観葉植物を迎える", "other"),
                    ("お気に入りの香りを見つける", "beauty"),
                    ("机まわりをすっきりさせる", "other"),
                    ("キッチン収納を見直す", "other"),
                    ("写真を飾るスペースを作る", "hobby"),
                ],
            },
        ],
    },
    {
        "username": "yuki",
        "display_name": "Yuki",
        "bio": "一人旅と読書のためのマイリストです。",
        "lists": [
            {
                "title": "一人旅でしたいこと",
                "target_count": 50,
                "is_public": True,
                "items": [
                    ("京都で朝のお寺を散歩する", "travel"),
                    ("小さな宿に泊まる", "travel"),
                    ("旅ノートに写真を貼る", "hobby"),
                    ("市場で朝ごはんを食べる", "travel"),
                    ("海の見えるカフェで読書する", "hobby"),
                    ("温泉街を歩く", "travel"),
                    ("ローカル線に乗る", "travel"),
                    ("旅先で手紙を書く", "other"),
                ],
            },
            {
                "title": "本と勉強のリスト",
                "target_count": 30,
                "is_public": False,
                "items": [
                    ("寝る前に30分読書する", "study"),
                    ("読みたい本リストを作る", "study"),
                    ("英語で日記を書く", "study"),
                    ("図書館カードを更新する", "study"),
                    ("読書メモを残す", "study"),
                ],
            },
        ],
    },
    {
        "username": "sora",
        "display_name": "Sora",
        "bio": "健康とお金まわりの習慣を作りたいです。",
        "lists": [
            {
                "title": "健康習慣リスト",
                "target_count": 30,
                "is_public": True,
                "items": [
                    ("週3回ストレッチする", "health"),
                    ("朝に白湯を飲む", "health"),
                    ("月1回長めに散歩する", "health"),
                    ("睡眠時間を記録する", "health"),
                    ("野菜を多めに食べる日を作る", "health"),
                    ("スマホを見ない夜を作る", "health"),
                ],
            },
            {
                "title": "お金を整える",
                "target_count": 20,
                "is_public": True,
                "items": [
                    ("月5万円貯金する", "money"),
                    ("家計簿を週1回見直す", "money"),
                    ("サブスクを整理する", "money"),
                    ("投資の本を1冊読む", "study"),
                    ("ふるさと納税を調べる", "money"),
                    ("欲しいものリストを作る", "money"),
                ],
            },
        ],
    },
]


FOLLOW_RELATIONS = [
    ("hana", "mika"),
    ("hana", "rina"),
    ("mika", "hana"),
    ("mika", "sora"),
    ("rina", "hana"),
    ("rina", "yuki"),
    ("yuki", "mika"),
    ("sora", "hana"),
    ("sora", "rina"),
]


class Command(BaseCommand):
    help = "Create reusable demo users, profiles, public/private my lists, follows, and saved lists."

    def handle(self, *args, **options):
        User = get_user_model()
        today = timezone.localdate()
        random.seed(20260615)

        users = {}
        created_users = 0
        touched_lists = 0
        touched_items = 0

        for spec in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=spec["username"],
                defaults={"email": f"{spec['username']}@example.com"},
            )
            if created:
                user.set_password("demo-pass-123")
                user.save(update_fields=["password"])
                created_users += 1
            users[spec["username"]] = user

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = spec["display_name"]
            profile.bio = spec["bio"]
            profile.save(update_fields=["display_name", "bio"])

            for list_index, list_spec in enumerate(spec["lists"]):
                plan, _ = YearPlan.objects.update_or_create(
                    user=user,
                    list_title=list_spec["title"],
                    defaults={
                        "year": today.year + list_index,
                        "target_count": list_spec["target_count"],
                        "is_public": list_spec["is_public"],
                    },
                )
                touched_lists += 1

                for item_index, (title, category) in enumerate(list_spec["items"], start=1):
                    is_done = item_index % 4 == 0
                    item_is_public = list_spec["is_public"] and item_index % 5 != 0
                    completed_date = today - timedelta(days=item_index * 2) if is_done else None
                    YearlyGoal.objects.update_or_create(
                        user=user,
                        year_plan=plan,
                        title=title,
                        defaults={
                            "description": "UI確認用のダミーデータです。",
                            "category": category if category in CATEGORIES else "other",
                            "is_done": is_done,
                            "completed_date": completed_date,
                            "is_public": list_spec["is_public"],
                            "item_is_public": item_is_public,
                        },
                    )
                    touched_items += 1

        for follower_username, following_username in FOLLOW_RELATIONS:
            follower = users[follower_username]
            following = users[following_username]
            if follower != following:
                Follow.objects.get_or_create(follower=follower, following=following)

        public_plans = list(YearPlan.objects.filter(user__in=users.values(), is_public=True))
        saved_count = 0
        liked_count = 0
        for username, user in users.items():
            own_plan_ids = {plan.pk for plan in YearPlan.objects.filter(user=user)}
            candidates = [plan for plan in public_plans if plan.pk not in own_plan_ids]
            for plan in candidates[:3]:
                _, saved_created = SavedList.objects.get_or_create(user=user, my_list=plan)
                _, liked_created = LikeList.objects.get_or_create(user=user, my_list=plan)
                saved_count += int(saved_created)
                liked_count += int(liked_created)

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data ready: "
                f"users created={created_users}, "
                f"lists touched={touched_lists}, "
                f"items touched={touched_items}, "
                f"saved created={saved_count}, "
                f"likes created={liked_count}"
            )
        )
