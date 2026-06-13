import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from goals.models import Profile, YearPlan, YearlyGoal


CATEGORY_BY_TITLE = {
    "沖縄旅行に行く": "travel",
    "京都でひとり旅をする": "travel",
    "富士山を見に行く": "travel",
    "浴衣を着て花火大会に行く": "hobby",
    "朝カフェで読書する": "hobby",
    "編み物作品を10個完成させる": "hobby",
    "月5万円貯金する": "money",
    "本を100冊読む": "study",
    "英語で日記を書けるようになる": "study",
    "朝活を習慣にする": "health",
    "東京で行きたいカフェを20店巡る": "hobby",
    "部屋をかわいく整える": "other",
    "週3回ストレッチする": "health",
    "副業の売上を作る": "work",
    "資格の勉強を始める": "study",
}

DEFAULT_CATEGORY = "other"


def category_for(title):
    for keyword, category in CATEGORY_BY_TITLE.items():
        if keyword in title or title in keyword:
            return category
    if any(word in title for word in ["旅行", "旅", "沖縄", "京都", "ホテル", "温泉", "富士山"]):
        return "travel"
    if any(word in title for word in ["美容", "メイク", "ネイル", "髪", "スキンケア"]):
        return "beauty"
    if any(word in title for word in ["本", "英語", "資格", "勉強", "読書", "日記"]):
        return "study"
    if any(word in title for word in ["仕事", "副業", "ポートフォリオ", "売上"]):
        return "work"
    if any(word in title for word in ["編み物", "カフェ", "花火", "美術館", "写真", "映画"]):
        return "hobby"
    if any(word in title for word in ["朝活", "ストレッチ", "ヨガ", "散歩", "健康"]):
        return "health"
    if any(word in title for word in ["貯金", "家計", "投資", "お金"]):
        return "money"
    return DEFAULT_CATEGORY


DEMO_USERS = [
    {
        "username": "はな",
        "display_name": "はな",
        "bio": "やりたいことを少しずつ形にしているマイリストです。",
        "password": "hanae2816",
        "lists": [
            {
                "title": "2026年やりたいこと",
                "target_count": 100,
                "is_public": True,
                "items": [
                    "沖縄旅行に行く",
                    "京都でひとり旅をする",
                    "本を100冊読む",
                    "英語で日記を書けるようになる",
                    "月5万円貯金する",
                    "朝活を習慣にする",
                    "編み物作品を10個完成させる",
                    "富士山を見に行く",
                    "カフェ巡りをする",
                    "美術館に行く",
                    "資格の勉強を始める",
                    "部屋をかわいく整える",
                    "新しいレシピを20個作る",
                    "週3回ストレッチする",
                    "副業の売上を作る",
                    "写真アルバムを作る",
                    "家計簿を3か月続ける",
                    "お気に入りの香水を見つける",
                    "海の見えるホテルに泊まる",
                    "手帳を毎週見返す",
                ],
            },
            {
                "title": "編み物で作りたいもの",
                "target_count": 30,
                "is_public": False,
                "items": [
                    "春色のショールを編む",
                    "自分用のカーディガンを完成させる",
                    "友だちに小さなポーチを贈る",
                    "余り糸でコースターを作る",
                    "丸ヨークセーターに挑戦する",
                    "編み込み模様のミトンを作る",
                    "夏用バッグを編む",
                    "お気に入り糸の見本帳を作る",
                    "ベビー用ブランケットを編む",
                    "作品写真をきれいに撮る",
                    "編み図を1つ自作する",
                    "毛糸収納を整える",
                ],
            },
        ],
    },
    {
        "username": "yui",
        "display_name": "Yui",
        "bio": "旅と季節のイベントを集めています。",
        "password": "demo-pass-123",
        "lists": [
            {
                "title": "夏にやりたいこと",
                "target_count": 30,
                "is_public": True,
                "items": [
                    "浴衣を着て花火大会に行く",
                    "海辺で朝日を見る",
                    "かき氷の有名店に行く",
                    "夏野菜カレーを作る",
                    "友だちとナイトプールに行く",
                    "ひまわり畑で写真を撮る",
                    "ベランダで小さなハーブを育てる",
                    "涼しい図書館で読書する",
                    "日焼け止めを毎日塗る",
                    "夏のワンピースを1着買う",
                    "冷たい抹茶ラテを作る",
                    "夕方に川沿いを散歩する",
                    "夏限定の美術展に行く",
                    "旅行用ポーチを整理する",
                ],
            },
            {
                "title": "一人旅でしたいこと",
                "target_count": 50,
                "is_public": True,
                "items": [
                    "京都で朝のお寺を散歩する",
                    "ローカル線に乗って知らない町へ行く",
                    "旅先で手紙を書く",
                    "市場で朝ごはんを食べる",
                    "小さな宿に泊まる",
                    "旅ノートに写真を貼る",
                    "美術館をゆっくり見る",
                    "海の見えるカフェで読書する",
                    "温泉街を歩く",
                    "ご当地スーパーで買い物する",
                    "旅先でランニングする",
                    "カメラだけ持って半日歩く",
                ],
            },
        ],
    },
    {
        "username": "mika",
        "display_name": "Mika",
        "bio": "カフェ、美容、お金のことを楽しく整え中です。",
        "password": "demo-pass-123",
        "lists": [
            {
                "title": "東京カフェ巡り",
                "target_count": 30,
                "is_public": True,
                "items": [
                    "朝カフェで読書する",
                    "蔵前のカフェでプリンを食べる",
                    "表参道でラテアートを楽しむ",
                    "神保町で本屋カフェに行く",
                    "清澄白河でコーヒー豆を買う",
                    "吉祥寺でテラス席のある店に行く",
                    "日本橋で静かな喫茶店を探す",
                    "代々木上原で焼き菓子を買う",
                    "中目黒で桜の時期にカフェへ行く",
                    "浅草で和カフェに入る",
                    "カフェ巡りマップを作る",
                    "お気に入りの席を写真に残す",
                    "月1回カフェ予算を決める",
                ],
            },
            {
                "title": "美容と健康を整える",
                "target_count": 50,
                "is_public": False,
                "items": [
                    "週3回ストレッチする",
                    "スキンケアを朝晩続ける",
                    "似合うリップを見つける",
                    "髪をつやつやに保つ",
                    "毎日水を1.5リットル飲む",
                    "寝る前のスマホ時間を減らす",
                    "月1回ネイルを整える",
                    "姿勢改善の動画を続ける",
                    "お気に入りの香りを探す",
                    "健康診断の予約をする",
                    "湯船にゆっくり浸かる日を作る",
                    "メイクポーチを整理する",
                ],
            },
        ],
    },
    {
        "username": "rina",
        "display_name": "Rina",
        "bio": "仕事と暮らしのリストを育てています。",
        "password": "demo-pass-123",
        "lists": [
            {
                "title": "恋人とやりたいこと",
                "target_count": 30,
                "is_public": True,
                "items": [
                    "一緒に水族館へ行く",
                    "記念日に手紙を書く",
                    "夜景の見えるレストランに行く",
                    "週末に映画を2本見る",
                    "お互いの好きな本を交換する",
                    "温泉旅行を計画する",
                    "一緒に料理を作る",
                    "写真をアルバムにまとめる",
                    "朝の公園を散歩する",
                    "クリスマスマーケットに行く",
                    "おそろいのマグカップを買う",
                    "家でたこ焼きパーティーをする",
                ],
            },
            {
                "title": "仕事で伸ばしたいこと",
                "target_count": 70,
                "is_public": False,
                "items": [
                    "ポートフォリオを作り直す",
                    "資格の勉強を始める",
                    "朝30分だけ専門書を読む",
                    "副業の売上を作る",
                    "週1回ふりかえりを書く",
                    "プレゼン資料を改善する",
                    "作業時間を記録する",
                    "新しいツールを1つ試す",
                    "英語のメール表現を覚える",
                    "上司にキャリア相談をする",
                    "集中できるデスク環境を作る",
                    "月末に成果をまとめる",
                    "仕事用プロフィールを更新する",
                ],
            },
            {
                "title": "一人旅でしたいこと",
                "target_count": 30,
                "is_public": True,
                "items": [
                    "沖縄で海を見ながら朝ごはんを食べる",
                    "旅先の小さな本屋に入る",
                    "ローカルカフェで日記を書く",
                    "港町で夕焼けを眺める",
                    "市場でおみやげを選ぶ",
                    "古い町並みを写真に撮る",
                    "一人で温泉宿に泊まる",
                    "旅ノートに使ったお金をまとめる",
                    "美術館を時間を気にせず見る",
                    "知らない駅で途中下車する",
                    "朝の散歩で神社に行く",
                    "帰ってから写真を整理する",
                ],
            },
        ],
    },
]


class Command(BaseCommand):
    help = "Create demo users, my lists, and concrete public/private list items."

    def handle(self, *args, **options):
        User = get_user_model()
        today = timezone.localdate()
        random.seed(20260511)

        created_users = 0
        created_plans = 0
        created_goals = 0
        updated_goals = 0
        deleted_old_goals = 0

        for user_spec in DEMO_USERS:
            user, user_created = User.objects.get_or_create(
                username=user_spec["username"],
                defaults={"email": f"{user_spec['username']}@example.com"},
            )
            if user_created:
                user.set_password(user_spec["password"])
                user.save(update_fields=["password"])
                created_users += 1

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.display_name = user_spec["display_name"]
            profile.bio = user_spec["bio"]
            profile.save(update_fields=["display_name", "bio"])

            for plan_index, list_spec in enumerate(user_spec["lists"]):
                year = today.year + plan_index
                plan = YearPlan.objects.filter(user=user, list_title=list_spec["title"]).first()
                if plan is None:
                    plan = YearPlan.objects.create(
                        user=user,
                        year=year,
                        list_title=list_spec["title"],
                        target_count=list_spec["target_count"],
                        is_public=list_spec["is_public"],
                    )
                    created_plans += 1
                else:
                    plan.year = year
                    plan.target_count = list_spec["target_count"]
                    plan.is_public = list_spec["is_public"]
                    plan.save(update_fields=["year", "target_count", "is_public"])

                cleanup_result = YearlyGoal.objects.filter(
                    user=user,
                    year_plan=plan,
                ).exclude(title__in=list_spec["items"]).delete()
                deleted_old_goals += cleanup_result[0]

                for item_index, title in enumerate(list_spec["items"], start=1):
                    is_done = item_index % 5 == 0
                    item_is_public = item_index % 6 != 0
                    completed_date = today - timedelta(days=item_index * 3) if is_done else None
                    category = category_for(title)

                    goal = YearlyGoal.objects.filter(
                        user=user,
                        year_plan=plan,
                        title=title,
                    ).first()
                    defaults = {
                        "description": f"{list_spec['title']}の確認用ダミーデータ",
                        "category": category,
                        "is_done": is_done,
                        "completed_date": completed_date,
                        "is_public": list_spec["is_public"],
                        "item_is_public": item_is_public,
                    }
                    if goal is None:
                        YearlyGoal.objects.create(user=user, year_plan=plan, title=title, **defaults)
                        created_goals += 1
                    else:
                        for field, value in defaults.items():
                            setattr(goal, field, value)
                        goal.save(update_fields=[*defaults.keys(), "updated_at"])
                        updated_goals += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data ready. "
                f"users created: {created_users}, "
                f"lists created: {created_plans}, "
                f"goals created: {created_goals}, "
                f"goals updated: {updated_goals}, "
                f"old demo goals removed: {deleted_old_goals}"
            )
        )
