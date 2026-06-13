import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from goals.models import IdeaMemo, MonthlyGoal, Profile, TodayTask, WeeklyGoal, YearlyGoal, YearPlan


YEARLY_GOAL_DATA = [
    ("沖縄旅行に行く", "travel"),
    ("京都でひとり旅をする", "travel"),
    ("本を100冊読む", "study"),
    ("英語で日記を書けるようになる", "study"),
    ("月5万円貯金する", "money"),
    ("朝活を習慣にする", "health"),
    ("編み物作品を30個作る", "hobby"),
    ("富士山を見に行く", "travel"),
    ("カフェ巡りをする", "hobby"),
    ("美術館に行く", "hobby"),
    ("資格の勉強を始める", "study"),
    ("部屋をかわいく整える", "other"),
    ("新しいレシピを20個作る", "hobby"),
    ("週3回ストレッチする", "health"),
    ("副業の売上を作る", "work"),
    ("肌に合うスキンケアを見つける", "beauty"),
    ("ヘアケアを習慣にする", "beauty"),
    ("仕事用ポートフォリオを作る", "work"),
    ("家計簿を3か月続ける", "money"),
    ("温泉旅行に行く", "travel"),
    ("韓国語の勉強を始める", "study"),
    ("お気に入りの香水を見つける", "beauty"),
    ("週末に公園を散歩する", "health"),
    ("写真アルバムを作る", "hobby"),
    ("デスク周りを整える", "work"),
    ("積立投資を始める", "money"),
    ("パン作りに挑戦する", "hobby"),
    ("ヨガを体験する", "health"),
    ("鎌倉へ日帰り旅をする", "travel"),
    ("読みたい漫画を完読する", "hobby"),
    ("仕事のタスク管理を見直す", "work"),
    ("歯のメンテナンスに行く", "health"),
    ("春服を整理する", "beauty"),
    ("毎月映画を1本観る", "hobby"),
    ("ノート術を試す", "study"),
    ("ふるさと納税を調べる", "money"),
    ("友達に手紙を書く", "other"),
    ("ピクニックに行く", "travel"),
    ("肩こり対策をする", "health"),
    ("仕事の資格試験に申し込む", "work"),
    ("お気に入りの喫茶店を見つける", "hobby"),
    ("水族館に行く", "travel"),
    ("眉メイクを研究する", "beauty"),
    ("英語の本を1冊読む", "study"),
    ("毎月の固定費を見直す", "money"),
    ("寝室を整える", "other"),
    ("ランニングシューズを買う", "health"),
    ("手帳を使いこなす", "hobby"),
    ("仕事の発信を始める", "work"),
    ("北海道旅行の計画を立てる", "travel"),
    ("料理の作り置きを覚える", "hobby"),
    ("体重を記録する", "health"),
    ("ネイルケアをする", "beauty"),
    ("歴史の本を読む", "study"),
    ("副業用のサービス案を考える", "work"),
    ("非常用のお金を貯める", "money"),
    ("お気に入りの花を飾る", "other"),
    ("神社巡りをする", "travel"),
    ("編み物の販売準備をする", "hobby"),
    ("朝ごはんを整える", "health"),
    ("Excelを勉強する", "study"),
    ("仕事机の配線を整理する", "work"),
    ("クローゼットを見直す", "beauty"),
    ("貯金口座を分ける", "money"),
    ("家族写真を撮る", "other"),
    ("金沢へ旅行する", "travel"),
    ("新しいカフェで読書する", "hobby"),
    ("睡眠時間を増やす", "health"),
    ("デザインの勉強をする", "study"),
    ("仕事の振り返りを毎週書く", "work"),
    ("コスメポーチを整理する", "beauty"),
    ("年間予算を作る", "money"),
    ("玄関をすっきりさせる", "other"),
    ("海を見に行く", "travel"),
    ("刺繍に挑戦する", "hobby"),
    ("姿勢改善をする", "health"),
    ("オンライン講座を受ける", "study"),
    ("名刺を作る", "work"),
    ("美容院でイメチェンする", "beauty"),
    ("ポイント管理を見直す", "money"),
    ("観葉植物を育てる", "other"),
    ("奈良で鹿を見る", "travel"),
    ("焼き菓子を作る", "hobby"),
    ("毎日水を飲む", "health"),
    ("文章を書く練習をする", "study"),
    ("副業ページを公開する", "work"),
    ("日焼け対策を習慣にする", "beauty"),
    ("財布の中身を整理する", "money"),
    ("思い出ボックスを作る", "other"),
    ("箱根に泊まる", "travel"),
    ("季節の花を見に行く", "travel"),
    ("読書メモを残す", "study"),
    ("週1回自炊する", "health"),
    ("小さな作品を販売する", "work"),
    ("お気に入りの服だけ残す", "beauty"),
    ("貯金100万円を目指す", "money"),
    ("部屋に間接照明を置く", "other"),
    ("陶芸体験に行く", "hobby"),
    ("朝の散歩コースを作る", "health"),
    ("仕事用ブログを書く", "work"),
]


LINKED_GOAL_PLANS = [
    {
        "yearly": "本を100冊読む",
        "month": "今月10冊読む",
        "week": "今週2冊読む",
        "today": "寝る前に30分読書する",
    },
    {
        "yearly": "沖縄旅行に行く",
        "month": "旅行日程を決める",
        "week": "航空券を比較する",
        "today": "航空券サイトを見る",
    },
    {
        "yearly": "編み物作品を30個作る",
        "month": "今月は小物を3個編む",
        "week": "毛糸と編み図を選ぶ",
        "today": "作品候補を3つメモする",
    },
    {
        "yearly": "月5万円貯金する",
        "month": "今月の予算を決める",
        "week": "固定費を見直す",
        "today": "サブスクを確認する",
    },
    {
        "yearly": "英語で日記を書けるようになる",
        "month": "日記に使う表現を30個覚える",
        "week": "短い日記を3回書く",
        "today": "今日の出来事を英語で1文書く",
    },
    {
        "yearly": "朝活を習慣にする",
        "month": "起床時間を30分早める",
        "week": "平日に3回早起きする",
        "today": "明日の朝やることを決める",
    },
    {
        "yearly": "副業の売上を作る",
        "month": "販売するサービスを決める",
        "week": "サービス説明文を書く",
        "today": "価格案を3つ考える",
    },
    {
        "yearly": "部屋をかわいく整える",
        "month": "部屋のテーマカラーを決める",
        "week": "収納用品を調べる",
        "today": "机の上を片付ける",
    },
]


class Command(BaseCommand):
    help = "Create concrete demo goals and related data for the local test user."

    def handle(self, *args, **options):
        random.seed(2816)
        User = get_user_model()
        user, created = User.objects.get_or_create(username="\u306f\u306a")
        user.set_password("hanae2816")
        user.save(update_fields=["password"])

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.display_name = "\u306f\u306a"
        profile.bio = "UI確認用の具体的なダミーデータが入ったアカウントです。"
        profile.save(update_fields=["display_name", "bio"])
        YearPlan.objects.update_or_create(
            user=user,
            year=timezone.localdate().year,
            defaults={"list_title": "2026年やりたいこと", "target_count": 100, "is_public": True},
        )

        self._clear_user_demo_data(user)

        yearly_goals = self._create_yearly_goals(user)
        monthly_goals, weekly_goals, today_tasks = self._create_linked_goals(yearly_goals)
        idea_memos = self._create_idea_memos(user)

        self.stdout.write(
            self.style.SUCCESS(
                "My demo data ready. "
                f"user: {'created' if created else 'reused'}, "
                f"yearly goals: {len(yearly_goals)}, "
                f"monthly goals: {len(monthly_goals)}, "
                f"weekly goals: {len(weekly_goals)}, "
                f"today tasks: {len(today_tasks)}, "
                f"idea memos: {len(idea_memos)}"
            )
        )

    def _clear_user_demo_data(self, user):
        monthly_goals = MonthlyGoal.objects.filter(yearly_goal__user=user)
        weekly_goals = WeeklyGoal.objects.filter(monthly_goal__in=monthly_goals)

        TodayTask.objects.filter(weekly_goal__in=weekly_goals).delete()
        WeeklyGoal.objects.filter(pk__in=weekly_goals.values("pk")).delete()
        MonthlyGoal.objects.filter(pk__in=monthly_goals.values("pk")).delete()
        YearlyGoal.objects.filter(user=user).delete()
        IdeaMemo.objects.filter(user=user).delete()

    def _create_yearly_goals(self, user):
        today = timezone.localdate()
        goals = []

        for index, (title, category) in enumerate(YEARLY_GOAL_DATA, start=1):
            is_done = random.random() < 0.2
            completed_date = today - timedelta(days=random.randint(0, 180)) if is_done else None
            goals.append(
                YearlyGoal.objects.create(
                    user=user,
                    title=title,
                    category=category,
                    completed_date=completed_date,
                    is_done=is_done,
                    is_public=True,
                    item_is_public=random.random() >= 0.2,
                )
            )

        return goals

    def _create_linked_goals(self, yearly_goals):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        goals_by_title = {goal.title: goal for goal in yearly_goals}
        monthly_goals = []
        weekly_goals = []
        today_tasks = []

        for index, plan in enumerate(LINKED_GOAL_PLANS, start=1):
            yearly_goal = goals_by_title[plan["yearly"]]
            month_goal = MonthlyGoal.objects.create(
                month=today.replace(day=1),
                title=plan["month"],
                yearly_goal=yearly_goal,
                is_done=random.random() < 0.2,
            )
            week_goal = WeeklyGoal.objects.create(
                week_start=week_start + timedelta(weeks=index - 1),
                title=plan["week"],
                monthly_goal=month_goal,
                is_done=random.random() < 0.25,
            )
            task = TodayTask.objects.create(
                date=today,
                title=plan["today"],
                weekly_goal=week_goal,
                is_done=random.random() < 0.3,
            )
            monthly_goals.append(month_goal)
            weekly_goals.append(week_goal)
            today_tasks.append(task)

        return monthly_goals, weekly_goals, today_tasks

    def _create_idea_memos(self, user):
        ideas = [
            "あとでやりたいホテルステイ",
            "あとでやりたい季節の手仕事",
            "あとでやりたい読書会",
            "あとでやりたい朝カフェ",
            "あとでやりたい収納見直し",
            "あとでやりたい小旅行",
            "あとでやりたい美容メンテ",
            "あとでやりたい副業アイデア",
            "あとでやりたい健康習慣",
            "あとでやりたい貯金チャレンジ",
        ]
        return [
            IdeaMemo.objects.create(
                user=user,
                title=title,
                note="具体化する前の思いつきメモです。",
            )
            for title in ideas
        ]
