from datetime import timedelta
from math import ceil

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.db.models import Count, F, Max, Q, Sum
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode
from django.views.generic import CreateView, DeleteView, UpdateView
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .forms import (
    AccountEmailChangeForm,
    IdeaMemoForm,
    GoalImageForm,
    GoalLinkForm,
    ListCommentForm,
    MonthlyGoalForm,
    ProfileForm,
    ProfilePrivacyForm,
    ProfilePrivacyToggleForm,
    SignUpForm,
    TodayTaskForm,
    WeeklyGoalForm,
    YearlyGoalCreateForm,
    YearlyGoalForm,
    YearlyGoalInlineCreateForm,
    YearlyGoalInlineUpdateForm,
    YearPlanForm,
)
from .models import (
    CollaborationInvite,
    FollowRequest,
    GoalImage,
    GoalLink,
    GoalSetting,
    Follow,
    IdeaMemo,
    ListComment,
    LikeList,
    MonthlyGoal,
    Profile,
    SavedList,
    SavedItem,
    TodayTask,
    TogetherRequest,
    UserActivity,
    WantToTry,
    WeeklyGoal,
    YearlyGoal,
    YearPlan,
)
from .template_data import LIST_TEMPLATES as CURATED_LIST_TEMPLATES
from .template_data import TEMPLATE_CATEGORIES


USERNAME_DUPLICATE_ERROR = "このユーザーネームはすでに使用されています。"


LIST_TEMPLATES = [
    {
        "slug": "summer",
        "title": "夏にやりたいこと",
        "target_count": 30,
        "items": [
            ("浴衣を着て花火大会に行く", "hobby"),
            ("海辺で朝日を見る", "travel"),
            ("かき氷の有名店に行く", "hobby"),
            ("ひまわり畑で写真を撮る", "hobby"),
            ("夕方に川沿いを散歩する", "health"),
        ],
    },
    {
        "slug": "year-2026",
        "title": "2026年やりたいこと",
        "target_count": 100,
        "items": [
            ("沖縄旅行に行く", "travel"),
            ("本を100冊読む", "study"),
            ("月5万円貯金する", "money"),
            ("朝活を習慣にする", "health"),
            ("副業の売上を作る", "work"),
        ],
    },
    {
        "slug": "couple",
        "title": "恋人とやりたいこと",
        "target_count": 30,
        "items": [
            ("一緒に水族館へ行く", "travel"),
            ("記念日に手紙を書く", "other"),
            ("夜景の見えるレストランに行く", "hobby"),
            ("温泉旅行を計画する", "travel"),
            ("一緒に料理を作る", "hobby"),
        ],
    },
    {
        "slug": "friends",
        "title": "友達とやりたいこと",
        "target_count": 30,
        "items": [
            ("ボードゲーム会を開く", "hobby"),
            ("日帰り旅行に行く", "travel"),
            ("おそろいの写真を撮る", "hobby"),
            ("誕生日をサプライズで祝う", "other"),
            ("カフェで近況報告をする", "hobby"),
        ],
    },
    {
        "slug": "solo-trip",
        "title": "一人旅でしたいこと",
        "target_count": 50,
        "items": [
            ("京都で朝のお寺を散歩する", "travel"),
            ("旅先で手紙を書く", "other"),
            ("市場で朝ごはんを食べる", "travel"),
            ("小さな宿に泊まる", "travel"),
            ("旅ノートに写真を貼る", "hobby"),
        ],
    },
    {
        "slug": "tokyo-cafe",
        "title": "東京カフェ巡り",
        "target_count": 30,
        "items": [
            ("朝カフェで読書する", "hobby"),
            ("蔵前のカフェでプリンを食べる", "hobby"),
            ("神保町で本屋カフェに行く", "hobby"),
            ("清澄白河でコーヒー豆を買う", "hobby"),
            ("カフェ巡りマップを作る", "hobby"),
        ],
    },
    {
        "slug": "knitting",
        "title": "編み物で作りたいもの",
        "target_count": 30,
        "items": [
            ("春色のショールを編む", "hobby"),
            ("自分用のカーディガンを完成させる", "hobby"),
            ("丸ヨークセーターに挑戦する", "hobby"),
            ("夏用バッグを編む", "hobby"),
            ("編み図を1つ自作する", "hobby"),
        ],
    },
    {
        "slug": "self-care",
        "title": "自分磨きリスト",
        "target_count": 50,
        "items": [
            ("週3回ストレッチする", "health"),
            ("スキンケアを朝晩続ける", "beauty"),
            ("似合うリップを見つける", "beauty"),
            ("毎日水を1.5リットル飲む", "health"),
            ("寝る前のスマホ時間を減らす", "health"),
        ],
    },
    {
        "slug": "kyoto-trip",
        "title": "京都旅行",
        "target_count": 30,
        "items": [
            ("朝の清水寺をゆっくり歩く", "travel"),
            ("鴨川沿いでコーヒーを飲む", "travel"),
            ("町家カフェで和スイーツを食べる", "hobby"),
            ("着物で祇園を散歩する", "beauty"),
            ("お気に入りのお守りを選ぶ", "other"),
        ],
    },
    {
        "slug": "hokkaido-trip",
        "title": "北海道旅行",
        "target_count": 30,
        "items": [
            ("富良野のラベンダー畑に行く", "travel"),
            ("札幌で味噌ラーメンを食べる", "travel"),
            ("小樽運河を夜に散歩する", "travel"),
            ("函館山の夜景を見る", "travel"),
            ("牧場でソフトクリームを食べる", "hobby"),
        ],
    },
    {
        "slug": "korea-trip",
        "title": "韓国旅行",
        "target_count": 30,
        "items": [
            ("ソウルでカフェ巡りをする", "travel"),
            ("韓国コスメを見に行く", "beauty"),
            ("市場で屋台グルメを食べる", "travel"),
            ("韓国語で注文してみる", "study"),
            ("お気に入りの雑貨屋さんを探す", "hobby"),
        ],
    },
    {
        "slug": "onsen-tour",
        "title": "温泉巡り",
        "target_count": 30,
        "items": [
            ("露天風呂のある宿に泊まる", "travel"),
            ("朝風呂に入る", "health"),
            ("温泉街で食べ歩きをする", "travel"),
            ("浴衣で写真を撮る", "hobby"),
            ("地元の名物料理を食べる", "travel"),
        ],
    },
    {
        "slug": "couple-100",
        "title": "恋人とやりたいこと100",
        "target_count": 100,
        "items": [
            ("一緒に旅行のしおりを作る", "travel"),
            ("記念日に手紙を交換する", "other"),
            ("夜景の見える場所へ行く", "hobby"),
            ("一緒に新しい料理を作る", "hobby"),
            ("お互いの行きたい場所リストを作る", "other"),
        ],
    },
    {
        "slug": "date-ideas",
        "title": "デートアイデア集",
        "target_count": 50,
        "items": [
            ("朝カフェデートをする", "hobby"),
            ("美術館デートをする", "hobby"),
            ("公園でピクニックする", "health"),
            ("映画館でレイトショーを見る", "hobby"),
            ("日帰り温泉に行く", "travel"),
        ],
    },
    {
        "slug": "anniversary",
        "title": "記念日にやりたいこと",
        "target_count": 30,
        "items": [
            ("思い出の写真をアルバムにする", "hobby"),
            ("少し特別なレストランを予約する", "hobby"),
            ("手紙を書いて渡す", "other"),
            ("おそろいの小物を選ぶ", "beauty"),
            ("来年の約束をひとつ決める", "other"),
        ],
    },
    {
        "slug": "glow-up",
        "title": "垢抜けリスト",
        "target_count": 50,
        "items": [
            ("似合う髪型を研究する", "beauty"),
            ("眉毛を整える", "beauty"),
            ("姿勢を意識して歩く", "health"),
            ("クローゼットを整理する", "other"),
            ("自分に似合う色を知る", "beauty"),
        ],
    },
    {
        "slug": "skincare-routine",
        "title": "スキンケア習慣",
        "target_count": 30,
        "items": [
            ("毎朝日焼け止めを塗る", "beauty"),
            ("週1回シートマスクをする", "beauty"),
            ("メイクを落としてから寝る", "beauty"),
            ("水をこまめに飲む", "health"),
            ("肌の記録をメモする", "beauty"),
        ],
    },
    {
        "slug": "healthy-habits-30",
        "title": "健康習慣30",
        "target_count": 30,
        "items": [
            ("朝起きたら白湯を飲む", "health"),
            ("寝る前にストレッチする", "health"),
            ("週3回散歩する", "health"),
            ("野菜を一品足す", "health"),
            ("睡眠時間を記録する", "health"),
        ],
    },
    {
        "slug": "exercise-challenge",
        "title": "運動チャレンジ",
        "target_count": 30,
        "items": [
            ("10分ウォーキングする", "health"),
            ("スクワットを続ける", "health"),
            ("ヨガ動画を見ながら動く", "health"),
            ("階段を使う日を増やす", "health"),
            ("運動できた日を記録する", "health"),
        ],
    },
    {
        "slug": "diet-goals",
        "title": "ダイエット目標",
        "target_count": 30,
        "items": [
            ("間食を見直す", "health"),
            ("タンパク質を意識する", "health"),
            ("週に一度体型を記録する", "health"),
            ("夜更かしを減らす", "health"),
            ("ご褒美メニューを決める", "hobby"),
        ],
    },
    {
        "slug": "certification-roadmap",
        "title": "資格取得ロードマップ",
        "target_count": 50,
        "items": [
            ("試験日を確認する", "study"),
            ("参考書を1冊選ぶ", "study"),
            ("毎週の勉強時間を決める", "study"),
            ("過去問を解く日を作る", "study"),
            ("模試を受ける", "study"),
        ],
    },
    {
        "slug": "english-study",
        "title": "英語学習リスト",
        "target_count": 50,
        "items": [
            ("英語で日記を3行書く", "study"),
            ("朝に単語を10個覚える", "study"),
            ("英語の動画を字幕付きで見る", "study"),
            ("オンライン英会話を試す", "study"),
            ("好きな曲の歌詞を訳す", "hobby"),
        ],
    },
    {
        "slug": "reading-list",
        "title": "読書リスト",
        "target_count": 50,
        "items": [
            ("読みたい本を10冊書き出す", "study"),
            ("寝る前に15分読む", "study"),
            ("読書ノートを作る", "study"),
            ("本屋さんで気になる本を探す", "hobby"),
            ("月に1冊レビューを書く", "study"),
        ],
    },
    {
        "slug": "cafe-wishlist",
        "title": "行きたいカフェ",
        "target_count": 30,
        "items": [
            ("朝に行きたいカフェを探す", "hobby"),
            ("読書できる静かなカフェへ行く", "hobby"),
            ("季節限定スイーツを食べる", "hobby"),
            ("友達におすすめカフェを聞く", "hobby"),
            ("カフェマップを作る", "other"),
        ],
    },
    {
        "slug": "movie-watchlist",
        "title": "見たい映画",
        "target_count": 50,
        "items": [
            ("名作映画を1本見る", "hobby"),
            ("映画館で新作を見る", "hobby"),
            ("好きな監督の作品を調べる", "hobby"),
            ("映画ノートを書く", "hobby"),
            ("友達と映画会をする", "hobby"),
        ],
    },
    {
        "slug": "saving-challenge",
        "title": "貯金チャレンジ",
        "target_count": 30,
        "items": [
            ("毎月の貯金額を決める", "money"),
            ("使っていないサブスクを見直す", "money"),
            ("欲しいものリストを整理する", "money"),
            ("1週間の予算を決める", "money"),
            ("貯金できた日を記録する", "money"),
        ],
    },
    {
        "slug": "money-reset",
        "title": "お金を整える",
        "target_count": 30,
        "items": [
            ("固定費を見直す", "money"),
            ("家計簿を1か月つける", "money"),
            ("貯金用口座を整える", "money"),
            ("不要な出費を書き出す", "money"),
            ("年間の大きな支出を確認する", "money"),
        ],
    },
    {
        "slug": "investment-study",
        "title": "投資の勉強",
        "target_count": 30,
        "items": [
            ("NISAについて調べる", "money"),
            ("投資用語を10個覚える", "study"),
            ("少額投資の本を読む", "study"),
            ("リスク許容度を考える", "money"),
            ("毎月の積立額をシミュレーションする", "money"),
        ],
    },
    {
        "slug": "bucket-list-100",
        "title": "死ぬまでにやりたいこと100",
        "target_count": 100,
        "items": [
            ("見たことのない景色を見に行く", "travel"),
            ("大切な人に手紙を書く", "other"),
            ("夢中になれる趣味を続ける", "hobby"),
            ("自分の作品を世に出す", "work"),
            ("人生で一度はオーロラを見る", "travel"),
        ],
    },
    {
        "slug": "life-achievements",
        "title": "人生で達成したいこと",
        "target_count": 100,
        "items": [
            ("自分らしい働き方を見つける", "work"),
            ("安心できる暮らしを整える", "money"),
            ("大切な人との時間を増やす", "other"),
            ("健康でいられる習慣を作る", "health"),
            ("いつか本当に住みたい場所を決める", "travel"),
        ],
    },
]


TEMPLATE_SAMPLE_POOL = [
    ("朝カフェで読書する", "hobby"),
    ("沖縄旅行に行く", "travel"),
    ("京都でひとり旅をする", "travel"),
    ("本を12冊読む", "study"),
    ("月5万円貯金する", "money"),
    ("週3回ストレッチする", "health"),
    ("新しいレシピを作る", "hobby"),
    ("美術館に行く", "hobby"),
    ("資格の勉強を始める", "study"),
    ("部屋をかわいく整える", "other"),
    ("副業の売上を作る", "work"),
    ("英語で日記を書く", "study"),
    ("富士山を見に行く", "travel"),
    ("カフェ巡りマップを作る", "hobby"),
    ("編み物作品を完成させる", "hobby"),
    ("スキンケアを見直す", "beauty"),
    ("早寝早起きを続ける", "health"),
    ("スマホの写真を整理する", "other"),
    ("お気に入りの服を見つける", "beauty"),
    ("家計簿を1か月続ける", "money"),
    ("行きたいお店リストを作る", "hobby"),
    ("仕事のポートフォリオを整える", "work"),
    ("海辺で夕日を見る", "travel"),
    ("季節の花を見に行く", "travel"),
    ("手帳に夢リストを書く", "other"),
]


TEMPLATE_EXTRA_POOLS = {
    "summer": [
        ("海で朝日を見る", "travel"),
        ("浴衣に合う髪型を試す", "beauty"),
        ("夜の散歩をする", "health"),
        ("夏野菜の料理を作る", "hobby"),
        ("レモネードを手作りする", "hobby"),
        ("川沿いでピクニックする", "travel"),
        ("夏の読書リストを読む", "study"),
        ("水族館へ行く", "travel"),
        ("夕涼みカフェに行く", "hobby"),
        ("夏服をすっきり整理する", "other"),
    ],
    "couple": [
        ("一緒に朝ごはんを作る", "hobby"),
        ("記念写真を撮る", "hobby"),
        ("行きたい旅行先を相談する", "travel"),
        ("お互いに本をすすめる", "study"),
        ("映画館でレイトショーを見る", "hobby"),
        ("公園でのんびり散歩する", "health"),
        ("おそろいの小物を選ぶ", "hobby"),
        ("将来のやりたいことを話す", "other"),
        ("温泉宿を調べる", "travel"),
        ("手紙を交換する", "other"),
    ],
    "friends": [
        ("友達と朝カフェに行く", "hobby"),
        ("写真を撮り合う", "hobby"),
        ("小さな旅行を計画する", "travel"),
        ("おすすめ本を交換する", "study"),
        ("手作りごはん会をする", "hobby"),
        ("美術館へ行く", "hobby"),
        ("お祝いカードを書く", "other"),
        ("公園でピクニックする", "travel"),
        ("共通のやりたいことリストを作る", "other"),
        ("カラオケで好きな曲を歌う", "hobby"),
    ],
    "solo-trip": [
        ("ローカル線に乗る", "travel"),
        ("旅先のカフェで日記を書く", "hobby"),
        ("朝市で買い物する", "travel"),
        ("海の見える宿に泊まる", "travel"),
        ("小さな美術館に寄る", "hobby"),
        ("旅先で本を読む", "study"),
        ("ご当地スイーツを食べる", "travel"),
        ("夕方の街を散歩する", "health"),
        ("旅の予算を決める", "money"),
        ("お気に入りの景色を写真に残す", "hobby"),
    ],
    "tokyo-cafe": [
        ("代々木上原のカフェへ行く", "hobby"),
        ("吉祥寺で喫茶店巡りをする", "hobby"),
        ("浅草で和カフェを探す", "hobby"),
        ("中目黒でモーニングする", "hobby"),
        ("表参道でラテを飲む", "hobby"),
        ("高円寺の純喫茶へ行く", "hobby"),
        ("池袋で読書カフェに行く", "hobby"),
        ("神楽坂で甘味処に行く", "hobby"),
        ("カフェ予算を決める", "money"),
        ("お気に入りカフェをノートにまとめる", "other"),
    ],
    "knitting": [
        ("靴下を一足編む", "hobby"),
        ("ミトンを編む", "hobby"),
        ("透かし編みを練習する", "study"),
        ("余り糸で小物を作る", "hobby"),
        ("編み物道具を整理する", "other"),
        ("新しい毛糸屋さんへ行く", "hobby"),
        ("友達へのプレゼントを編む", "hobby"),
        ("編み物ノートを作る", "other"),
        ("英文パターンに挑戦する", "study"),
        ("ブランケットを少しずつ編む", "hobby"),
    ],
    "self-care": [
        ("朝に白湯を飲む", "health"),
        ("髪のケアを丁寧にする", "beauty"),
        ("クローゼットを整理する", "other"),
        ("姿勢を意識して歩く", "health"),
        ("メイクブラシを洗う", "beauty"),
        ("週末にゆっくりお風呂に入る", "health"),
        ("気になる講座を受ける", "study"),
        ("寝室を整える", "other"),
        ("小さなご褒美予算を作る", "money"),
        ("1日10分だけ片付ける", "other"),
    ],
}


def fill_template_items():
    for template in LIST_TEMPLATES:
        items = list(template["items"])
        pool = TEMPLATE_EXTRA_POOLS.get(template["slug"], []) + TEMPLATE_SAMPLE_POOL
        index = 0
        while len(items) < template["target_count"]:
            title, category = pool[index % len(pool)]
            candidate = title if title not in {item[0] for item in items} else f"{title} {len(items) + 1}"
            items.append((candidate, category))
            index += 1
        template["items"] = items[: template["target_count"]]


fill_template_items()


def build_theme_items(seed_items, places, actions, target_count, default_category):
    items = []
    seen = set()
    for title, category in seed_items:
        if title not in seen:
            items.append((title, category))
            seen.add(title)
    index = 0
    max_combinations = max(1, len(places) * len(actions))
    while len(items) < target_count:
        place = places[index % len(places)]
        action = actions[(index // len(places)) % len(actions)]
        title = f"{place}{action}"
        if index >= max_combinations and title in seen:
            title = f"{title} {len(items) + 1}"
        if title not in seen:
            items.append((title, default_category))
            seen.add(title)
        index += 1
    return items[:target_count]


QUALITY_TEMPLATE_SPECS = [
    {
        "slug": "tokyo-cafe",
        "title": "東京カフェ巡り",
        "target_count": 30,
        "category": "hobby",
        "seeds": [("浅草のカフェに行く", "hobby"), ("表参道のカフェに行く", "hobby"), ("レトロ喫茶巡りをする", "hobby"), ("モーニングを食べに行く", "hobby")],
        "places": ["浅草で", "表参道で", "蔵前で", "神保町で", "清澄白河で", "中目黒で", "代々木上原で", "吉祥寺で", "高円寺で", "谷中で"],
        "actions": ["カフェ時間を楽しむ", "朝カフェをする", "プリンを食べる", "読書する", "写真を撮る", "一人時間を過ごす"],
    },
    {
        "slug": "kyoto-trip",
        "title": "京都旅行",
        "target_count": 30,
        "category": "travel",
        "seeds": [("朝の清水寺を歩く", "travel"), ("鴨川沿いでコーヒーを飲む", "travel"), ("町家カフェで和スイーツを食べる", "hobby"), ("着物で祇園を散歩する", "beauty")],
        "places": ["清水寺で", "祇園で", "嵐山で", "鴨川沿いで", "伏見稲荷で", "錦市場で", "南禅寺で", "哲学の道で"],
        "actions": ["ゆっくり散歩する", "写真を撮る", "朝時間を楽しむ", "甘味を食べる", "お土産を選ぶ", "季節の景色を見る"],
    },
    {
        "slug": "hokkaido-trip",
        "title": "北海道旅行",
        "target_count": 30,
        "category": "travel",
        "seeds": [("富良野のラベンダー畑に行く", "travel"), ("札幌で味噌ラーメンを食べる", "travel"), ("小樽運河を夜に散歩する", "travel"), ("函館山の夜景を見る", "travel")],
        "places": ["札幌で", "小樽で", "函館で", "富良野で", "美瑛で", "旭川で", "洞爺湖で", "知床で"],
        "actions": ["名物を食べる", "景色を眺める", "写真を撮る", "朝市に行く", "カフェに寄る", "自然を楽しむ"],
    },
    {
        "slug": "korea-trip",
        "title": "韓国旅行",
        "target_count": 30,
        "category": "travel",
        "seeds": [("ソウルでカフェ巡りをする", "travel"), ("韓国コスメを見に行く", "beauty"), ("市場で屋台グルメを食べる", "travel"), ("韓国語で注文してみる", "study")],
        "places": ["ソウルで", "弘大で", "聖水で", "明洞で", "漢江沿いで", "市場で", "雑貨屋で", "カフェで"],
        "actions": ["写真を撮る", "食べ歩きをする", "コスメを探す", "韓国語を使う", "お土産を選ぶ", "朝時間を楽しむ"],
    },
    {
        "slug": "onsen-tour",
        "title": "温泉巡り",
        "target_count": 30,
        "category": "travel",
        "seeds": [("露天風呂のある宿に泊まる", "travel"), ("朝風呂に入る", "health"), ("温泉街で食べ歩きをする", "travel"), ("浴衣で写真を撮る", "hobby")],
        "places": ["箱根で", "草津で", "別府で", "有馬で", "伊香保で", "道後で", "城崎で", "黒川で"],
        "actions": ["温泉に入る", "温泉街を歩く", "名物を食べる", "宿でのんびりする", "朝風呂を楽しむ", "旅の記録を書く"],
    },
    {
        "slug": "couple-100",
        "title": "恋人とやりたいこと100",
        "target_count": 100,
        "category": "hobby",
        "seeds": [("おそろいのマグカップを買う", "hobby"), ("クリスマスマーケットに行く", "travel"), ("旅行に行く", "travel"), ("記念日ディナーをする", "hobby")],
        "places": ["春に二人で", "夏に二人で", "秋に二人で", "冬に二人で", "休日に二人で", "記念日に二人で", "夜に二人で", "朝に二人で", "おうちで二人で", "旅先で二人で"],
        "actions": ["写真を撮る", "手紙を書く", "新しいお店に行く", "映画を見る", "料理を作る", "散歩する", "プレゼントを選ぶ", "旅行計画を立てる", "カフェに行く", "思い出を記録する"],
    },
    {
        "slug": "date-ideas",
        "title": "デートアイデア集",
        "target_count": 50,
        "category": "hobby",
        "seeds": [("朝カフェデートをする", "hobby"), ("美術館デートをする", "hobby"), ("公園でピクニックする", "health"), ("映画館でレイトショーを見る", "hobby")],
        "places": ["カフェで", "公園で", "映画館で", "美術館で", "水族館で", "商店街で", "温泉で", "夜景スポットで"],
        "actions": ["デートする", "写真を撮る", "ゆっくり話す", "新しい体験をする", "季節を楽しむ", "おそろいを選ぶ"],
    },
    {
        "slug": "anniversary",
        "title": "記念日にやりたいこと",
        "target_count": 30,
        "category": "other",
        "seeds": [("手紙を書いて渡す", "other"), ("記念日ディナーを予約する", "hobby"), ("思い出の写真をアルバムにする", "hobby"), ("来年の約束をひとつ決める", "other")],
        "places": ["記念日に", "お祝いの日に", "二人の思い出として", "少し特別な日に", "夜の時間に", "休日に"],
        "actions": ["手紙を書く", "写真を残す", "プレゼントを選ぶ", "レストランを予約する", "思い出を振り返る", "次の目標を話す"],
    },
    {
        "slug": "glow-up",
        "title": "垢抜けリスト",
        "target_count": 50,
        "category": "beauty",
        "seeds": [("眉毛サロンに行く", "beauty"), ("スキンケアを見直す", "beauty"), ("ヘアケアを始める", "beauty"), ("姿勢改善をする", "health")],
        "places": ["朝に", "夜に", "週末に", "月初に", "美容の日に", "外出前に", "お風呂上がりに", "クローゼットで"],
        "actions": ["眉毛を整える", "肌の調子を記録する", "髪を丁寧にケアする", "似合う色を試す", "姿勢を意識する", "服を見直す"],
    },
    {
        "slug": "skincare-routine",
        "title": "スキンケア習慣",
        "target_count": 30,
        "category": "beauty",
        "seeds": [("毎朝日焼け止めを塗る", "beauty"), ("週1回シートマスクをする", "beauty"), ("メイクを落としてから寝る", "beauty"), ("肌の記録をメモする", "beauty")],
        "places": ["朝に", "夜に", "週末に", "お風呂上がりに", "外出前に", "寝る前に"],
        "actions": ["保湿を丁寧にする", "日焼け止めを塗る", "肌状態を記録する", "シートマスクをする", "クレンジングを丁寧にする", "水を飲む"],
    },
    {
        "slug": "self-care",
        "title": "自分磨きリスト",
        "target_count": 50,
        "category": "beauty",
        "seeds": [("朝に白湯を飲む", "health"), ("髪のケアを丁寧にする", "beauty"), ("クローゼットを整理する", "other"), ("気になる講座を受ける", "study")],
        "places": ["朝に", "夜に", "休日に", "月初に", "寝る前に", "外出前に", "週末に", "自分時間に"],
        "actions": ["体を整える", "美容を見直す", "学びを増やす", "部屋を整える", "服を選び直す", "気持ちをノートに書く"],
    },
    {
        "slug": "healthy-habits-30",
        "title": "健康習慣30",
        "target_count": 30,
        "category": "health",
        "seeds": [("毎日8000歩歩く", "health"), ("毎日水を2L飲む", "health"), ("ストレッチを続ける", "health"), ("睡眠時間を記録する", "health")],
        "places": ["朝に", "昼に", "夜に", "通勤中に", "寝る前に", "休日に"],
        "actions": ["歩く", "水を飲む", "ストレッチする", "睡眠を記録する", "野菜を食べる", "深呼吸する"],
    },
    {
        "slug": "exercise-challenge",
        "title": "運動チャレンジ",
        "target_count": 30,
        "category": "health",
        "seeds": [("10分ウォーキングする", "health"), ("スクワットを続ける", "health"), ("ヨガ動画を見ながら動く", "health"), ("階段を使う日を増やす", "health")],
        "places": ["朝に", "夜に", "公園で", "家で", "週末に", "仕事終わりに"],
        "actions": ["ウォーキングする", "筋トレする", "ヨガをする", "ストレッチする", "運動を記録する", "体をほぐす"],
    },
    {
        "slug": "diet-goals",
        "title": "ダイエット目標",
        "target_count": 30,
        "category": "health",
        "seeds": [("間食を見直す", "health"), ("タンパク質を意識する", "health"), ("週に一度体型を記録する", "health"), ("夜更かしを減らす", "health")],
        "places": ["朝食で", "昼食で", "夕食で", "買い物前に", "寝る前に", "週末に"],
        "actions": ["食事を整える", "体重を記録する", "間食を見直す", "歩く時間を作る", "睡眠を整える", "ご褒美を決める"],
    },
    {
        "slug": "certification-roadmap",
        "title": "資格取得ロードマップ",
        "target_count": 50,
        "category": "study",
        "seeds": [("試験日を確認する", "study"), ("参考書を1冊選ぶ", "study"), ("毎週の勉強時間を決める", "study"), ("過去問を解く日を作る", "study")],
        "places": ["試験対策として", "朝学習で", "週末に", "スキマ時間に", "模試前に", "復習日に"],
        "actions": ["参考書を進める", "過去問を解く", "弱点を見直す", "ノートを作る", "模試を受ける", "学習計画を直す"],
    },
    {
        "slug": "english-study",
        "title": "英語学習リスト",
        "target_count": 50,
        "category": "study",
        "seeds": [("英単語1000語覚える", "study"), ("英語日記を書く", "study"), ("英語の動画を見る", "study"), ("TOEICを受験する", "study")],
        "places": ["朝に", "夜に", "通勤中に", "週末に", "英語学習で", "試験前に", "休憩中に", "寝る前に"],
        "actions": ["英単語を覚える", "英語日記を書く", "リスニングする", "音読する", "TOEIC対策をする", "英語動画を見る"],
    },
    {
        "slug": "reading-list",
        "title": "読書リスト",
        "target_count": 50,
        "category": "study",
        "seeds": [("読みたい本を10冊書き出す", "study"), ("寝る前に15分読む", "study"), ("読書ノートを作る", "study"), ("本屋さんで気になる本を探す", "hobby")],
        "places": ["朝に", "夜に", "休日に", "カフェで", "本屋で", "図書館で", "寝る前に", "移動中に"],
        "actions": ["本を読む", "読書ノートを書く", "気になる本を探す", "感想を書く", "積読を見直す", "学びをまとめる"],
    },
    {
        "slug": "knitting",
        "title": "編み物で作りたいもの",
        "target_count": 30,
        "category": "hobby",
        "seeds": [("春色のショールを編む", "hobby"), ("自分用のカーディガンを完成させる", "hobby"), ("ミトンを編む", "hobby"), ("ブランケットを少しずつ編む", "hobby")],
        "places": ["春に", "夏に", "秋に", "冬に", "自分用に", "友達用に", "余り糸で", "新しい毛糸で"],
        "actions": ["ショールを編む", "靴下を編む", "帽子を編む", "バッグを編む", "小物を作る", "セーターに挑戦する"],
    },
    {
        "slug": "cafe-wishlist",
        "title": "行きたいカフェ",
        "target_count": 30,
        "category": "hobby",
        "seeds": [("朝に行きたいカフェを探す", "hobby"), ("読書できる静かなカフェへ行く", "hobby"), ("季節限定スイーツを食べる", "hobby"), ("カフェマップを作る", "other")],
        "places": ["近所で", "旅先で", "駅前で", "海辺で", "本屋の近くで", "公園の近くで", "路地裏で", "レトロ喫茶で"],
        "actions": ["カフェに行く", "モーニングを食べる", "スイーツを食べる", "読書する", "写真を撮る", "一人時間を楽しむ"],
    },
    {
        "slug": "movie-watchlist",
        "title": "見たい映画",
        "target_count": 50,
        "category": "hobby",
        "seeds": [("名作映画を1本見る", "hobby"), ("映画館で新作を見る", "hobby"), ("好きな監督の作品を調べる", "hobby"), ("映画ノートを書く", "hobby")],
        "places": ["休日に", "夜に", "映画館で", "家で", "雨の日に", "友達と", "一人時間に", "連休に"],
        "actions": ["映画を見る", "感想を書く", "予告をチェックする", "名作を見直す", "映画ノートを作る", "好きな作品を探す"],
    },
    {
        "slug": "saving-challenge",
        "title": "貯金チャレンジ",
        "target_count": 30,
        "category": "money",
        "seeds": [("毎月の貯金額を決める", "money"), ("使っていないサブスクを見直す", "money"), ("欲しいものリストを整理する", "money"), ("1週間の予算を決める", "money")],
        "places": ["月初に", "給料日に", "買い物前に", "週末に", "家計簿で", "貯金用口座で"],
        "actions": ["貯金額を決める", "支出を見直す", "予算を決める", "固定費を確認する", "欲しいものを整理する", "貯金記録をつける"],
    },
    {
        "slug": "money-reset",
        "title": "お金を整える",
        "target_count": 30,
        "category": "money",
        "seeds": [("固定費を見直す", "money"), ("家計簿を1か月つける", "money"), ("貯金用口座を整える", "money"), ("年間の大きな支出を確認する", "money")],
        "places": ["月初に", "週末に", "給料日に", "買い物前に", "家計簿で", "銀行アプリで"],
        "actions": ["支出を確認する", "予算を整える", "固定費を見直す", "貯金計画を作る", "不要な出費を探す", "お金の記録をつける"],
    },
    {
        "slug": "investment-study",
        "title": "投資の勉強",
        "target_count": 30,
        "category": "money",
        "seeds": [("NISAについて調べる", "money"), ("投資用語を10個覚える", "study"), ("少額投資の本を読む", "study"), ("リスク許容度を考える", "money")],
        "places": ["投資学習で", "週末に", "本で", "動画で", "ニュースで", "家計管理で"],
        "actions": ["用語を調べる", "本を読む", "リスクを考える", "積立額を試算する", "制度を確認する", "学びをメモする"],
    },
    {
        "slug": "summer",
        "title": "夏にやりたいこと",
        "target_count": 30,
        "category": "travel",
        "seeds": [("浴衣を着て花火大会に行く", "hobby"), ("海辺で朝日を見る", "travel"), ("かき氷の有名店に行く", "hobby"), ("ひまわり畑で写真を撮る", "hobby")],
        "places": ["夏の朝に", "夏の夜に", "海辺で", "川沿いで", "花火の日に", "休日に"],
        "actions": ["季節を楽しむ", "写真を撮る", "涼みに行く", "夏スイーツを食べる", "散歩する", "思い出を残す"],
    },
    {
        "slug": "year-2026",
        "title": "2026年やりたいこと",
        "target_count": 100,
        "category": "other",
        "seeds": [("沖縄旅行に行く", "travel"), ("本を100冊読む", "study"), ("月5万円貯金する", "money"), ("朝活を習慣にする", "health")],
        "places": ["2026年に", "春までに", "夏までに", "秋までに", "年末までに", "毎月", "休日に", "自分のために", "家族と", "友達と"],
        "actions": ["旅に出る", "学びを増やす", "健康を整える", "貯金する", "作品を作る", "部屋を整える", "挑戦を記録する", "新しい場所へ行く", "習慣を作る", "夢を一つ叶える"],
    },
    {
        "slug": "bucket-list-100",
        "title": "死ぬまでにやりたいこと100",
        "target_count": 100,
        "category": "other",
        "seeds": [("見たことのない景色を見に行く", "travel"), ("大切な人に手紙を書く", "other"), ("夢中になれる趣味を続ける", "hobby"), ("人生で一度はオーロラを見る", "travel")],
        "places": ["人生で一度は", "いつか", "大切な人と", "一人で", "旅先で", "節目の日に", "夢として", "元気なうちに", "時間を作って", "心に残る形で"],
        "actions": ["景色を見る", "旅をする", "作品を作る", "感謝を伝える", "挑戦する", "学び直す", "写真を残す", "暮らしを整える", "夢を叶える", "思い出を作る"],
    },
    {
        "slug": "life-achievements",
        "title": "人生で達成したいこと",
        "target_count": 100,
        "category": "other",
        "seeds": [("自分らしい働き方を見つける", "work"), ("安心できる暮らしを整える", "money"), ("大切な人との時間を増やす", "other"), ("健康でいられる習慣を作る", "health")],
        "places": ["人生の目標として", "これから", "数年かけて", "自分のペースで", "大切な人と", "暮らしの中で", "仕事で", "学びの中で", "健康のために", "未来のために"],
        "actions": ["達成する", "整える", "続ける", "育てる", "形にする", "学ぶ", "挑戦する", "記録する", "大切にする", "実現する"],
    },
]


LIST_TEMPLATES = [
    {
        "slug": spec["slug"],
        "title": spec["title"],
        "category": spec["category"],
        "summary": "、".join(title for title, _category in spec["seeds"][:3]) + "などを集めたテンプレートです。",
        "target_count": spec["target_count"],
        "items": build_theme_items(spec["seeds"], spec["places"], spec["actions"], spec["target_count"], spec["category"]),
    }
    for spec in QUALITY_TEMPLATE_SPECS
]

LIST_TEMPLATES = CURATED_LIST_TEMPLATES


def current_week_start():
    today = timezone.localdate()
    return today - timedelta(days=today.weekday())


def month_start_for(date_value):
    return date_value.replace(day=1)


def add_months(date_value, months):
    month_index = date_value.month - 1 + months
    year = date_value.year + month_index // 12
    month = month_index % 12 + 1
    return date_value.replace(year=year, month=month, day=1)


def selected_date_from_request(request, name, default):
    value = parse_date(request.GET.get(name, ""))
    return value or default


def get_default_year_plan(user):
    year = timezone.localdate().year
    year_plan = YearPlan.objects.filter(user=user, year=year).order_by("pk").first()
    if year_plan:
        return year_plan
    return YearPlan.objects.create(
        user=user,
        year=year,
        list_title=f"{year}年やりたいこと",
        target_count=100,
        is_public=False,
    )


def touch_year_plan(plan):
    if plan:
        plan.save(update_fields=["updated_at"])


def can_manage_year_plan(user, plan):
    return user.is_authenticated and plan.user_id == user.id


def can_edit_year_plan_items(user, plan):
    return user.is_authenticated and (plan.user_id == user.id or plan.collaborators.filter(pk=user.pk).exists())


def can_view_account_details(viewer, owner):
    if viewer.is_authenticated and viewer.pk == owner.pk:
        return True
    profile = getattr(owner, "profile", None)
    if not profile or not profile.is_private:
        return True
    return viewer.is_authenticated and Follow.objects.filter(follower=viewer, following=owner).exists()


def can_view_profile(viewer, owner):
    return can_view_account_details(viewer, owner)


def can_view_year_plan(viewer, plan):
    if plan.user_id == getattr(viewer, "id", None):
        return True
    if can_edit_year_plan_items(viewer, plan):
        return True
    return plan.is_public and can_view_profile(viewer, plan.user)


def can_view_list(viewer, plan):
    return can_view_year_plan(viewer, plan)


def can_view_yearly_goal(viewer, goal):
    if goal.user_id == getattr(viewer, "id", None):
        return True
    if goal.year_plan_id:
        return goal.item_is_public and can_view_list(viewer, goal.year_plan)
    return False


def visible_public_plan_filter(viewer, prefix=""):
    user_field = f"{prefix}user"
    profile_private_field = f"{prefix}user__profile__is_private"
    profile_missing_field = f"{prefix}user__profile__isnull"
    user_id_field = f"{prefix}user_id"
    if viewer.is_authenticated:
        visible_user_ids = Follow.objects.filter(follower=viewer).values_list("following_id", flat=True)
        return (
            Q(**{profile_private_field: False})
            | Q(**{user_field: viewer})
            | Q(**{f"{user_id_field}__in": visible_user_ids})
        )
    return Q(**{profile_private_field: False}) | Q(**{profile_missing_field: True})


def visible_public_goal_filter(viewer):
    base_filter = Q(item_is_public=True, year_plan__is_public=True)
    return base_filter & visible_public_plan_filter(viewer, prefix="year_plan__")


def get_follow_request_status(requester, target):
    if not requester.is_authenticated or requester == target:
        return ""
    request_obj = FollowRequest.objects.filter(requester=requester, target=target).order_by("-updated_at").first()
    return request_obj.status if request_obj else ""


def build_user_row(user, request_user):
    profile = Profile.objects.get_or_create(user=user, defaults={"display_name": user.username})[0]
    can_view_details = can_view_profile(request_user, user)
    is_following = False
    follow_request_status = ""
    if request_user and request_user.is_authenticated and request_user != user:
        is_following = Follow.objects.filter(follower=request_user, following=user).exists()
        follow_request_status = get_follow_request_status(request_user, user)
    return {
        "user": user,
        "profile": profile,
        "display_name": profile.display_name or user.username,
        "followers_count": Follow.objects.filter(following=user).count(),
        "can_follow": bool(request_user and request_user.is_authenticated and request_user != user),
        "is_following": is_following,
        "follow_request_status": follow_request_status,
        "is_private": profile.is_private,
        "can_view_profile_details": can_view_details,
    }


def can_edit_yearly_goal(user, goal):
    if not goal.year_plan_id:
        return user.is_authenticated and goal.user_id == user.id
    return can_edit_year_plan_items(user, goal.year_plan)


def year_plan_item_limit_reached(plan):
    return plan.target_count > 0 and plan.goals.count() >= plan.target_count


def item_limit_message():
    return "このリストは設定した目標件数に達しています。"


def media_file_is_referenced(name, *, profile_pk=None, goal_image_pk=None):
    if not name:
        return False
    profiles = Profile.objects.filter(icon=name)
    if profile_pk is not None:
        profiles = profiles.exclude(pk=profile_pk)
    if profiles.exists():
        return True
    images = GoalImage.objects.filter(image=name)
    if goal_image_pk is not None:
        images = images.exclude(pk=goal_image_pk)
    return images.exists()


def delete_media_file_if_unreferenced(name, storage, *, profile_pk=None, goal_image_pk=None):
    if not name or storage is None:
        return
    if media_file_is_referenced(name, profile_pk=profile_pk, goal_image_pk=goal_image_pk):
        return
    try:
        if storage.exists(name):
            storage.delete(name)
    except OSError:
        pass


def progress_percent(done_count, total_count):
    if total_count <= 0:
        return 0
    return min(round(done_count / total_count * 100), 100)


def profile_stats(user, viewer=None):
    viewer = viewer or user
    if not can_view_profile(viewer, user):
        return None
    public_plans = YearPlan.objects.filter(user=user, is_public=True)
    goals = YearlyGoal.objects.filter(user=user)
    return {
        "list_count": YearPlan.objects.filter(user=user).count(),
        "public_list_count": public_plans.count(),
        "done_item_count": goals.filter(is_done=True).count(),
        "liked_count": LikeList.objects.filter(my_list__user=user).count(),
        "saved_count": SavedList.objects.filter(my_list__user=user).count(),
        "following_count": Follow.objects.filter(follower=user).count(),
        "followers_count": Follow.objects.filter(following=user).count(),
    }


def get_template(slug):
    return next((template for template in LIST_TEMPLATES if template["slug"] == slug), None)


def template_card(template):
    usage_count = YearPlan.objects.filter(template_slug=template["slug"]).count()
    return {
        **template,
        "usage_count": usage_count,
        "usage_label": f"{template['target_count']}項目",
    }


def home(request):
    my_lists = []
    following_groups = []
    saved_groups = []
    if request.user.is_authenticated:
        my_lists = YearPlan.objects.filter(user=request.user).annotate(
            goals_count=Count("goals"),
            goals_done_count=Count("goals", filter=Q(goals__is_done=True)),
        ).order_by("-updated_at", "-pk")[:3]
        for plan in my_lists:
            plan.progress_percent = progress_percent(plan.goals_done_count, plan.goals_count)

        following_ids = Follow.objects.filter(follower=request.user).values_list("following_id", flat=True)
        following_plans = YearPlan.objects.filter(
            user_id__in=following_ids,
            is_public=True,
        ).select_related("user", "user__profile").annotate(
            public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
        ).filter(public_goal_count__gt=0).order_by("-updated_at", "-pk")[:3]
        following_groups = build_public_list_groups(following_plans, request.user, request=request)

        saved_plans = YearPlan.objects.filter(
            saved_by__user=request.user,
            is_public=True,
        ).select_related("user", "user__profile").annotate(
            public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
            saved_at=Max("saved_by__created_at"),
        ).filter(public_goal_count__gt=0).order_by("-saved_at", "-updated_at")[:3]
        saved_groups = build_public_list_groups(saved_plans, request.user, request=request)

    context = {
        "my_lists": my_lists,
        "following_groups": following_groups,
        "saved_groups": saved_groups,
        "recommended_templates": LIST_TEMPLATES[:3],
    }
    return render(request, "goals/home.html", context)


@never_cache
def service_worker(request):
    return HttpResponse("self.addEventListener('fetch', () => {});", content_type="application/javascript")


def create_hub(request):
    return render(request, "goals/create_hub.html")


@staff_member_required
def staff_dashboard(request):
    return render(request, "goals/staff_dashboard.html", {
        "user_count": get_user_model().objects.count(),
        "list_count": YearPlan.objects.count(),
        "item_count": YearlyGoal.objects.count(),
    })


def management_chart_rows(start_date, end_date):
    rows_by_date = {
        row["date_joined__date"]: row["count"]
        for row in get_user_model().objects.filter(date_joined__date__gte=start_date, date_joined__date__lte=end_date)
        .values("date_joined__date").annotate(count=Count("id"))
    }
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    max_count = max([rows_by_date.get(day, 0) for day in dates] + [1])
    width, height = 720, 220
    usable_width, usable_height = 652, 164
    rows = []
    for index, day in enumerate(dates):
        x = 34 + (usable_width * index / max(len(dates) - 1, 1))
        count = rows_by_date.get(day, 0)
        y = 192 - (usable_height * count / max_count)
        rows.append({"date": day, "count": count, "x": round(x, 1), "y": round(y, 1)})
    return {"width": width, "height": height, "rows": rows, "points": " ".join(f"{row['x']},{row['y']}" for row in rows)}


@staff_member_required
def management_dashboard(request):
    today = timezone.localdate()
    period = request.GET.get("period", "30")
    days = {"7": 7, "30": 30, "90": 90}.get(period, 30)
    start_date = today - timedelta(days=days - 1)
    users = get_user_model().objects.all()
    kpis = [
        {"label": "総ユーザー数", "value": users.count()},
        {"label": "今日の新規登録", "value": users.filter(date_joined__date=today).count()},
        {"label": "過去7日間の新規登録", "value": users.filter(date_joined__date__gte=today - timedelta(days=6)).count()},
        {"label": "過去30日間の新規登録", "value": users.filter(date_joined__date__gte=today - timedelta(days=29)).count()},
        {"label": "総リスト数", "value": YearPlan.objects.count()},
        {"label": "総リスト項目数", "value": YearlyGoal.objects.count()},
        {"label": "達成済み項目数", "value": YearlyGoal.objects.filter(is_done=True).count()},
    ]
    usage_stats = [
        {"label": "本日作成されたリスト", "value": YearPlan.objects.filter(created_at__date=today).count()},
        {"label": "過去7日間に作成されたリスト", "value": YearPlan.objects.filter(created_at__date__gte=today - timedelta(days=6)).count()},
        {"label": "本日追加された項目", "value": YearlyGoal.objects.filter(created_at__date=today).count()},
        {"label": "過去7日間に追加された項目", "value": YearlyGoal.objects.filter(created_at__date__gte=today - timedelta(days=6)).count()},
        {"label": "本日達成された項目", "value": YearlyGoal.objects.filter(completed_date=today).count()},
        {"label": "過去7日間に達成された項目", "value": YearlyGoal.objects.filter(completed_date__gte=today - timedelta(days=6)).count()},
    ]
    recent_activities = [
        {"at": item.created_at or item.updated_at, "label": "リスト作成", "detail": item.list_title or "マイリスト"}
        for item in YearPlan.objects.select_related("user").order_by("-created_at", "-updated_at")[:5]
    ]
    return render(request, "goals/management/dashboard.html", {
        "kpis": kpis,
        "usage_stats": usage_stats,
        "chart": management_chart_rows(start_date, today),
        "recent_activities": recent_activities,
        "data_notes": ["DAU/WAU/MAUはUserActivityが蓄積された範囲で今後拡張できます。"],
    })


@staff_member_required
def management_users(request):
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "new")
    users = get_user_model().objects.select_related("profile").annotate(
        list_count=Count("year_plans", distinct=True),
        item_count=Count("yearly_goals", distinct=True),
        done_item_count=Count("yearly_goals", filter=Q(yearly_goals__is_done=True), distinct=True),
        last_activity_at=Max("wishly_activity__last_seen_at"),
    )
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    users = users.order_by("date_joined" if sort == "old" else "-date_joined")
    return render(request, "goals/management/users.html", {
        "page_obj": Paginator(users, 30).get_page(request.GET.get("page")),
        "query": query,
        "sort": sort,
    })


@staff_member_required
def management_user_detail(request, pk):
    managed_user = get_object_or_404(get_user_model().objects.select_related("profile"), pk=pk)
    managed_user.last_activity_at = UserActivity.objects.filter(user=managed_user).aggregate(Max("last_seen_at"))["last_seen_at__max"]
    stats = {
        "リスト数": YearPlan.objects.filter(user=managed_user).count(),
        "項目数": YearlyGoal.objects.filter(user=managed_user).count(),
        "達成数": YearlyGoal.objects.filter(user=managed_user, is_done=True).count(),
        "フォロー数": Follow.objects.filter(follower=managed_user).count(),
        "フォロワー数": Follow.objects.filter(following=managed_user).count(),
        "いいねした数": LikeList.objects.filter(user=managed_user).count(),
        "保存したリスト数": SavedList.objects.filter(user=managed_user).count(),
        "保存した項目数": SavedItem.objects.filter(user=managed_user).count(),
    }
    return render(request, "goals/management/user_detail.html", {"managed_user": managed_user, "stats": stats})


@staff_member_required
def management_lists(request):
    query = request.GET.get("q", "").strip()
    visibility = request.GET.get("visibility", "all")
    lists = YearPlan.objects.select_related("user").annotate(
        item_count=Count("goals", distinct=True),
        done_count=Count("goals", filter=Q(goals__is_done=True), distinct=True),
        like_count=Count("liked_by", distinct=True),
        save_count=Count("saved_by", distinct=True),
    )
    if query:
        lists = lists.filter(Q(list_title__icontains=query) | Q(user__username__icontains=query))
    if visibility == "public":
        lists = lists.filter(is_public=True)
    elif visibility == "private":
        lists = lists.filter(is_public=False)
    lists = lists.order_by("-created_at", "-updated_at")
    return render(request, "goals/management/lists.html", {
        "page_obj": Paginator(lists, 30).get_page(request.GET.get("page")),
        "query": query,
        "visibility": visibility,
    })


@staff_member_required
def management_templates(request):
    sort = request.GET.get("sort", "usage_desc")
    templates = []
    for template in LIST_TEMPLATES:
        usage_count = YearPlan.objects.filter(template_slug=template["slug"]).count()
        templates.append({
            **template,
            "category_label": template.get("category", ""),
            "item_count": len(template.get("items", [])),
            "usage_count": usage_count,
            "usage_label": usage_count,
        })
    templates.sort(key=lambda item: item["usage_count"], reverse=(sort != "usage_asc"))
    return render(request, "goals/management/templates.html", {"templates": templates, "sort": sort})


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except IntegrityError:
                form.add_error("username", USERNAME_DUPLICATE_ERROR)
            else:
                login(request, user)
                messages.success(request, "新規登録しました。")
                return redirect("goals:my_profile")
    else:
        form = SignUpForm()
    return render(request, "goals/form.html", {
        "form": form,
        "title": "新規登録",
        "cancel_url": reverse_lazy("goals:home"),
    })


@never_cache
@login_required
def my_profile(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"display_name": request.user.username},
    )
    list_filter = request.GET.get("list_status", "all")
    if list_filter not in {"all", "active", "completed"}:
        list_filter = "all"

    my_plans = YearPlan.objects.filter(user=request.user).annotate(
        goals_count=Count("goals"),
        goals_done_count=Count("goals", filter=Q(goals__is_done=True)),
    ).order_by("-updated_at", "-pk")
    my_plans = list(my_plans)
    for plan in my_plans:
        plan.progress_percent = progress_percent(plan.goals_done_count, plan.goals_count)
        # A list is complete when its completed item count reaches the configured target count.
        plan.is_target_completed = plan.target_count > 0 and plan.goals_done_count >= plan.target_count

    if list_filter == "completed":
        my_plans = [plan for plan in my_plans if plan.is_target_completed]
    elif list_filter == "active":
        my_plans = [plan for plan in my_plans if not plan.is_target_completed]

    my_list_page_obj = Paginator(my_plans, 10).get_page(request.GET.get("lists_page"))
    return render(request, "goals/profile.html", {
        "profile_user": request.user,
        "profile": profile,
        "is_own_profile": True,
        "profile_stats": profile_stats(request.user),
        "is_following": False,
        "follow_request_status": "",
        "can_view_profile_details": True,
        "my_list_page_obj": my_list_page_obj,
        "my_plans": my_list_page_obj.object_list,
        "list_filter": list_filter,
        "list_filter_query": "" if list_filter == "all" else f"list_status={list_filter}",
        "profile_share_url": request.build_absolute_uri(reverse("goals:profile_detail", kwargs={"username": request.user.username})),
    })


@login_required
def edit_profile(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"display_name": request.user.username},
    )
    if request.method == "POST":
        old_icon_name = profile.icon.name if profile.icon else ""
        old_icon_storage = profile.icon.storage if profile.icon else None
        form = ProfileForm(request.POST, request.FILES, instance=profile, user=request.user)
        if form.is_valid():
            profile_obj = form.save(commit=False)
            avatar_file = getattr(form, "processed_avatar_file", None)
            if avatar_file is not None:
                profile_obj.icon = avatar_file
            try:
                new_username = form.cleaned_data.get("username")
                if new_username and request.user.username != new_username:
                    request.user.username = new_username
                    request.user.save(update_fields=["username"])
                profile_obj.save()
            except IntegrityError:
                form.add_error("username", USERNAME_DUPLICATE_ERROR)
                return render(request, "goals/profile_form.html", {
                    "form": form,
                    "profile": profile,
                })
            new_icon_name = profile_obj.icon.name if profile_obj.icon else ""
            if old_icon_name and old_icon_name != new_icon_name:
                delete_media_file_if_unreferenced(old_icon_name, old_icon_storage, profile_pk=profile_obj.pk)
            messages.success(request, "プロフィールを保存しました。")
            return redirect("goals:my_profile")
    else:
        form = ProfileForm(instance=profile, user=request.user)
    return render(request, "goals/profile_form.html", {
        "form": form,
        "profile": profile,
    })


@login_required
def account_settings(request):
    profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"display_name": request.user.username})
    if request.method == "POST":
        form = ProfilePrivacyToggleForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "is_private": profile.is_private})
            messages.success(request, "保存しました。")
            return redirect("goals:account_settings")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)
    else:
        form = ProfilePrivacyToggleForm(instance=profile)
    return render(request, "goals/account_settings.html", {
        "profile": profile,
        "privacy_form": form,
    })


@login_required
def account_email_change(request):
    if request.method == "POST":
        form = AccountEmailChangeForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["email"])
            profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"display_name": request.user.username})
            profile.email_verified = False
            profile.save(update_fields=["email_verified"])
            messages.success(request, "メールアドレスを変更しました。")
            return redirect("goals:account_settings")
    else:
        form = AccountEmailChangeForm(user=request.user)
    return render(request, "goals/account_email_change.html", {"form": form})


@require_POST
@login_required
def resend_verification_email(request):
    messages.info(request, "認証メールの再送はメール設定完了後に利用できます。")
    return redirect("goals:account_settings")


@login_required
def account_delete(request):
    if request.method == "POST":
        user = request.user
        logout(request)
        user.is_active = False
        user.save(update_fields=["is_active"])
        return redirect("goals:home")
    return render(request, "goals/account_delete.html")


@login_required
def privacy_settings(request):
    profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"display_name": request.user.username})
    if request.method == "POST":
        form = ProfilePrivacyForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "プライバシー設定を保存しました。")
            return redirect("goals:account_settings")
    else:
        form = ProfilePrivacyForm(instance=profile)
    return render(request, "goals/privacy_settings.html", {"form": form, "profile": profile})


@login_required
def notifications_page(request):
    category = request.GET.get("category", "all")
    valid_categories = {"all", "follow", "collaboration", "like", "save"}
    if category not in valid_categories:
        category = "all"
    follow_requests = FollowRequest.objects.filter(target=request.user, status=FollowRequest.STATUS_PENDING).select_related("requester", "requester__profile")
    collaboration_invites = CollaborationInvite.objects.filter(invitee=request.user, status=CollaborationInvite.STATUS_PENDING).select_related("inviter", "inviter__profile", "list")
    like_notifications = LikeList.objects.filter(my_list__user=request.user).exclude(user=request.user).select_related("user", "user__profile", "my_list").order_by("-created_at")[:20]
    save_notifications = SavedList.objects.filter(my_list__user=request.user).exclude(user=request.user).select_related("user", "user__profile", "my_list").order_by("-created_at")[:20]
    tabs = [
        {"key": "all", "label": "すべて", "count": follow_requests.count() + collaboration_invites.count()},
        {"key": "follow", "label": "フォロー", "count": follow_requests.count()},
        {"key": "collaboration", "label": "共同リスト", "count": collaboration_invites.count()},
        {"key": "like", "label": "いいね", "count": like_notifications.count() if hasattr(like_notifications, "count") else 0},
        {"key": "save", "label": "保存", "count": save_notifications.count() if hasattr(save_notifications, "count") else 0},
    ]
    return render(request, "goals/notifications.html", {
        "notification_category": category,
        "notification_tabs": tabs,
        "follow_requests": follow_requests,
        "collaboration_invites": collaboration_invites,
        "like_notifications": like_notifications,
        "save_notifications": save_notifications,
    })


@login_required
def follow_requests_page(request):
    return notifications_page(request)


@require_POST
@login_required
def respond_follow_request(request, pk, status):
    follow_request = get_object_or_404(FollowRequest, pk=pk, target=request.user, status=FollowRequest.STATUS_PENDING)
    if status == FollowRequest.STATUS_ACCEPTED:
        Follow.objects.get_or_create(follower=follow_request.requester, following=request.user)
        follow_request.status = FollowRequest.STATUS_ACCEPTED
    elif status == FollowRequest.STATUS_REJECTED:
        follow_request.status = FollowRequest.STATUS_REJECTED
    else:
        raise PermissionDenied
    follow_request.save(update_fields=["status", "updated_at"])
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:notifications"))


@require_POST
@login_required
def respond_collaboration_invite(request, pk, status):
    invite = get_object_or_404(CollaborationInvite, pk=pk, invitee=request.user, status=CollaborationInvite.STATUS_PENDING)
    if status == CollaborationInvite.STATUS_ACCEPTED:
        invite.status = CollaborationInvite.STATUS_ACCEPTED
        invite.responded_at = timezone.now()
        invite.list.collaborators.add(request.user)
        invite.save(update_fields=["status", "responded_at"])
    elif status == CollaborationInvite.STATUS_DECLINED:
        invite.status = CollaborationInvite.STATUS_DECLINED
        invite.responded_at = timezone.now()
        invite.save(update_fields=["status", "responded_at"])
    else:
        raise PermissionDenied
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:notifications"))


def profile_detail(request, username):
    user = get_object_or_404(get_user_model(), username=username)
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"display_name": user.username})
    if request.user.is_authenticated and request.user == user:
        return redirect("goals:my_profile")
    can_view_profile_details = can_view_profile(request.user, user)
    public_plans = YearPlan.objects.none()
    goal_groups = []
    if can_view_profile_details:
        public_plans = YearPlan.objects.filter(user=user, is_public=True).select_related("user", "user__profile").order_by("-updated_at", "-pk")
        goal_groups = build_public_list_groups(public_plans, request.user, request=request)
    is_following = False
    follow_request_status = ""
    if request.user.is_authenticated:
        is_following = Follow.objects.filter(follower=request.user, following=user).exists()
        follow_request_status = get_follow_request_status(request.user, user)
    return render(request, "goals/profile.html", {
        "profile_user": user,
        "profile": profile,
        "goal_groups": goal_groups,
        "is_own_profile": False,
        "can_view_profile_details": can_view_profile_details,
        "profile_stats": profile_stats(user, request.user),
        "is_following": is_following,
        "follow_request_status": follow_request_status,
        "profile_share_url": request.build_absolute_uri(reverse("goals:profile_detail", kwargs={"username": user.username})),
    })


@login_required
def yearly_goal_list(request):
    timeline_filter = request.GET.get("type", "all")
    if timeline_filter not in {"all", "achievement", "share"}:
        timeline_filter = "all"

    following_ids = Follow.objects.filter(follower=request.user).values_list("following_id", flat=True)
    timeline_plans = YearPlan.objects.filter(
        user_id__in=following_ids,
        is_public=True,
    ).select_related("user", "user__profile").annotate(
        public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
        public_done_count=Count("goals", filter=Q(goals__item_is_public=True, goals__is_done=True)),
        latest_public_goal_at=Max("goals__updated_at", filter=Q(goals__item_is_public=True)),
    ).filter(public_goal_count__gt=0)

    if timeline_filter == "achievement":
        timeline_plans = timeline_plans.filter(public_done_count__gt=0)
    elif timeline_filter == "share":
        timeline_plans = timeline_plans.filter(public_done_count=0)

    timeline_plans = timeline_plans.distinct().order_by("-updated_at", "-latest_public_goal_at", "-pk")
    paginator = Paginator(timeline_plans, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    timeline_groups = build_public_list_groups(page_obj.object_list, request.user, request=request)
    latest_goal_filter = Q(item_is_public=True)
    if timeline_filter == "achievement":
        latest_goal_filter &= Q(is_done=True)
    latest_goals = {}
    for goal in YearlyGoal.objects.filter(
        year_plan_id__in=[group["plan"].pk for group in timeline_groups],
    ).filter(latest_goal_filter).select_related("year_plan").order_by("year_plan_id", "-updated_at", "-pk"):
        latest_goals.setdefault(goal.year_plan_id, goal)
    for group in timeline_groups:
        latest_goal = latest_goals.get(group["plan"].pk)
        if latest_goal and latest_goal.is_done:
            group["timeline_type"] = "achievement"
            group["timeline_badge"] = "達成"
            group["timeline_action"] = f"「{latest_goal.title}」を達成しました"
        else:
            group["timeline_type"] = "share"
            group["timeline_badge"] = "公開"
            group["timeline_action"] = f"「{group['list_title']}」を更新しました"

    return render(request, "goals/yearly_goal_list.html", {
        "page_obj": page_obj,
        "timeline_groups": timeline_groups,
        "timeline_filter": timeline_filter,
    })


@login_required
def my_list_detail(request, pk):
    year_plan = get_object_or_404(
        YearPlan.objects.select_related("user", "user__profile").prefetch_related("collaborators", "collaborators__profile"),
        pk=pk,
    )
    if not can_view_year_plan(request.user, year_plan):
        raise PermissionDenied

    if request.method == "POST":
        if not can_manage_year_plan(request.user, year_plan):
            raise PermissionDenied
        setting_form = YearPlanForm(request.POST, instance=year_plan)
        if setting_form.is_valid():
            setting_form.save()
            messages.success(request, "マイリスト設定を保存しました。")
            return redirect("goals:my_list_detail", pk=year_plan.pk)
    else:
        setting_form = YearPlanForm(instance=year_plan)

    all_goals = YearlyGoal.objects.filter(year_plan=year_plan).select_related(
        "added_by", "added_by__profile", "completed_by", "completed_by__profile",
    ).prefetch_related(
        "monthly_goals__weekly_goals__today_tasks",
    ).order_by("created_at")
    goals = all_goals
    done_count = all_goals.filter(is_done=True).count()
    total_count = all_goals.count()
    year_plan.progress_percent = progress_percent(done_count, year_plan.target_count)
    total_pages = max(ceil(goals.count() / 20), 1)
    try:
        current_page = int(request.GET.get("page", "1"))
    except ValueError:
        current_page = 1
    current_page = min(max(current_page, 1), total_pages)
    start = (current_page - 1) * 20
    end = start + 20
    page_goals = list(goals[start:end])

    context = {
        "setting": year_plan,
        "setting_form": setting_form,
        "add_goal_form": YearlyGoalInlineCreateForm(),
        "goals": page_goals,
        "left_goals": page_goals[:10],
        "right_goals": page_goals[10:],
        "done_count": done_count,
        "total_count": total_count,
        "remaining_count": max(year_plan.target_count - total_count, 0),
        "member_count": 1 + year_plan.collaborators.count(),
        "current_page": current_page,
        "total_pages": total_pages,
        "previous_page": current_page - 1 if current_page > 1 else None,
        "next_page": current_page + 1 if current_page < total_pages else None,
        "current_year": year_plan.year,
        "can_manage_list": can_manage_year_plan(request.user, year_plan),
        "can_edit_items": can_edit_year_plan_items(request.user, year_plan),
        "target_limit_reached": year_plan_item_limit_reached(year_plan),
        "like_count": year_plan.liked_by.count(),
        "save_count": year_plan.saved_by.count(),
        "share_count": getattr(year_plan, "share_count", 0),
        "is_liked": LikeList.objects.filter(user=request.user, my_list=year_plan).exists(),
        "is_saved": SavedList.objects.filter(user=request.user, my_list=year_plan).exists(),
    }
    return render(request, "goals/my_list_detail.html", context)


@login_required
def yearly_goal_detail(request, pk):
    goal = get_object_or_404(
        YearlyGoal.objects.select_related("year_plan", "year_plan__user", "year_plan__user__profile"),
        pk=pk,
        user=request.user,
    )
    year_plan = goal.year_plan or get_default_year_plan(request.user)
    return render(request, "goals/yearly_goal_detail.html", {
        "goal": goal,
        "year_plan": year_plan,
        "back_url": reverse("goals:my_list_detail", kwargs={"pk": year_plan.pk}),
        "back_label": year_plan.list_title or "マイリスト",
        "can_edit": True,
    })


@require_POST
@login_required
def add_my_list_goal_inline(request, pk):
    year_plan = get_object_or_404(YearPlan, pk=pk)
    if not can_edit_year_plan_items(request.user, year_plan):
        raise PermissionDenied
    form = YearlyGoalInlineCreateForm(request.POST)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if year_plan_item_limit_reached(year_plan):
        if is_ajax:
            return JsonResponse({"ok": False, "errors": {"__all__": [item_limit_message()]}}, status=400)
        messages.error(request, item_limit_message())
        return redirect("goals:my_list_detail", pk=year_plan.pk)
    if form.is_valid():
        goal = form.save(commit=False)
        goal.user = year_plan.user
        goal.year_plan = year_plan
        goal.added_by = request.user
        goal.save()
        touch_year_plan(year_plan)
        if is_ajax:
            html = render_to_string(
                "goals/partials/yearly_notebook_goal.html",
                {"goal": goal, "setting": year_plan},
                request=request,
            )
            return JsonResponse({
                "ok": True,
                "html": html,
                "goal_id": goal.pk,
                "category": goal.category,
                "total_count": year_plan.goals.count(),
            })
        messages.success(request, "やりたいことを追加しました。")
        return redirect("goals:my_list_detail", pk=year_plan.pk)
    if is_ajax:
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)
    messages.error(request, "やりたいことを入力してください。")
    return redirect("goals:my_list_detail", pk=year_plan.pk)


@require_POST
@login_required
def edit_my_list_goal_inline(request, pk):
    goal = get_object_or_404(YearlyGoal.objects.select_related("year_plan"), pk=pk, user=request.user)
    form = YearlyGoalInlineUpdateForm(request.POST, instance=goal)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if form.is_valid():
        goal = form.save()
        touch_year_plan(goal.year_plan)
        if is_ajax:
            html = render_to_string(
                "goals/partials/yearly_notebook_goal.html",
                {"goal": goal},
                request=request,
            )
            return JsonResponse({"ok": True, "html": html, "goal_id": goal.pk})
        messages.success(request, "項目を更新しました。")
        return redirect("goals:my_list_detail", pk=goal.year_plan_id)
    if is_ajax:
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)
    messages.error(request, "項目を更新できませんでした。")
    return redirect("goals:my_list_detail", pk=goal.year_plan_id)


@login_required
def monthly_goal_list(request):
    selected_month = month_start_for(selected_date_from_request(request, "month", month_start_for(timezone.localdate())))
    goals = MonthlyGoal.objects.filter(user=request.user, target_month=selected_month)
    return render(request, "goals/monthly_goal_list.html", {
        "goals": goals,
        "selected_month": selected_month,
        "previous_month": add_months(selected_month, -1),
        "next_month": add_months(selected_month, 1),
        "task_count": goals.count(),
    })


@login_required
def weekly_goal_list(request):
    selected_week = selected_date_from_request(request, "week", current_week_start())
    selected_week = selected_week - timedelta(days=selected_week.weekday())
    goals = WeeklyGoal.objects.filter(user=request.user, week_start_date=selected_week)
    return render(request, "goals/weekly_goal_list.html", {
        "goals": goals,
        "selected_week": selected_week,
        "week_end": selected_week + timedelta(days=6),
        "previous_week": selected_week - timedelta(days=7),
        "next_week": selected_week + timedelta(days=7),
        "task_count": goals.count(),
    })


@login_required
def today_task_list(request):
    today = timezone.localdate()
    selected_date = selected_date_from_request(request, "date", today)
    tasks = TodayTask.objects.filter(user=request.user, scheduled_date=selected_date)
    return render(
        request,
        "goals/today_task_list.html",
        {
            "today": today,
            "selected_date": selected_date,
            "previous_date": selected_date - timedelta(days=1),
            "next_date": selected_date + timedelta(days=1),
            "tasks": tasks,
            "task_count": tasks.count(),
        },
    )


def idea_memo_list(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return render(request, "goals/idea_memo_list.html", {"memos": IdeaMemo.objects.filter(user=request.user)})


def page_query_string(request, param, value):
    query = request.GET.copy()
    query[param] = value
    return query.urlencode()


def build_public_list_groups(plans, request_user=None, category="", request=None, include_private=False):
    plan_ids = [plan.pk for plan in plans]
    goals = YearlyGoal.objects.filter(
        year_plan_id__in=plan_ids,
    ).select_related("user", "user__profile", "year_plan").order_by("is_done", "-created_at")
    if not include_private:
        goals = goals.filter(item_is_public=True)
    if category:
        goals = goals.filter(category=category)

    grouped_goals = []
    groups_by_plan = {}
    for plan in plans:
        profile = plan.user.profile if hasattr(plan.user, "profile") else None
        display_name = profile.display_name if profile and profile.display_name else plan.user.username
        groups_by_plan[plan.pk] = {
            "plan": plan,
            "user": plan.user,
            "display_name": display_name,
            "list_title": plan.list_title or f"{plan.year}年やりたいこと",
            "target_count": plan.target_count,
            "done_count": plan.goals.filter(is_done=True).count() if include_private else plan.goals.filter(item_is_public=True, is_done=True).count(),
            "registered_count": plan.goals.count(),
            "total_count": plan.goals.count() if include_private else plan.goals.filter(item_is_public=True).count(),
            "remaining_count": max(plan.target_count - (plan.goals.count() if include_private else plan.goals.filter(item_is_public=True).count()), 0),
            "like_count": plan.liked_by.count(),
            "save_count": plan.saved_by.count(),
            "is_saved": False,
            "is_liked": False,
            "can_react": bool(request_user and request_user.is_authenticated and request_user != plan.user),
            "can_follow": bool(request_user and request_user.is_authenticated and request_user != plan.user),
            "is_private": bool(profile and profile.is_private),
            "follow_request_status": "",
            "show_item_privacy": include_private,
            "comment_form": ListCommentForm(),
            "comments": plan.comments.select_related("user", "user__profile").all(),
            "goals": [],
        }
        grouped_goals.append(groups_by_plan[plan.pk])

    if request_user and request_user.is_authenticated:
        saved_plan_ids = set(SavedList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
        liked_plan_ids = set(LikeList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
        saved_item_ids = set(SavedItem.objects.filter(user=request_user, item__year_plan_id__in=plan_ids).values_list("item_id", flat=True))
        wanted_item_ids = set(WantToTry.objects.filter(user=request_user, source_item__year_plan_id__in=plan_ids).values_list("source_item_id", flat=True))
        together_statuses = {
            request.list_item_id: request.status
            for request in TogetherRequest.objects.filter(requester=request_user, list_item__year_plan_id__in=plan_ids)
        }
        memo_titles = set(IdeaMemo.objects.filter(user=request_user).values_list("title", flat=True))
        following_user_ids = set(Follow.objects.filter(follower=request_user).values_list("following_id", flat=True))
        for plan_id, group in groups_by_plan.items():
            group["is_saved"] = plan_id in saved_plan_ids
            group["is_liked"] = plan_id in liked_plan_ids
            group["is_following"] = group["user"].pk in following_user_ids
            group["follow_request_status"] = get_follow_request_status(request_user, group["user"])
    else:
        saved_item_ids = set()
        wanted_item_ids = set()
        together_statuses = {}
        memo_titles = set()
        following_user_ids = set()

    for goal in goals:
        group = groups_by_plan.get(goal.year_plan_id)
        if group:
            goal.is_wanted_by_current_user = goal.pk in wanted_item_ids or goal.title in memo_titles
            goal.is_saved_by_current_user = goal.pk in saved_item_ids
            goal.together_status_for_current_user = together_statuses.get(goal.pk)
            group["goals"].append(goal)

    for group in grouped_goals:
        group["progress_percent"] = progress_percent(group["done_count"], group["total_count"])
        group["target_progress_percent"] = progress_percent(group["done_count"], group["target_count"])
        category_labels = []
        seen_categories = set()
        for goal in group["goals"]:
            if goal.category not in seen_categories:
                seen_categories.add(goal.category)
                category_labels.append(goal.get_category_display())
        group["category_labels"] = category_labels
        param = f"list_{group['plan'].pk}_page"
        total_items = len(group["goals"])
        total_pages = max(ceil(total_items / 20), 1)
        try:
            current_page = int(request.GET.get(param, "1")) if request else 1
        except ValueError:
            current_page = 1
        current_page = min(max(current_page, 1), total_pages)
        start = (current_page - 1) * 20
        page_goals = group["goals"][start:start + 20]
        group["left_goals"] = page_goals[:10]
        group["right_goals"] = page_goals[10:]
        group["list_current_page"] = current_page
        group["list_total_pages"] = total_pages
        group["list_previous_query"] = page_query_string(request, param, current_page - 1) if request and current_page > 1 else ""
        group["list_next_query"] = page_query_string(request, param, current_page + 1) if request and current_page < total_pages else ""
    return grouped_goals


def public_goal_list(request):
    query = request.GET.get("q", "").strip()
    result_type = request.GET.get("type", "lists")
    is_search_mode = bool(query)
    popular_keywords = ["カフェ", "旅行", "京都", "夏", "読書", "健康", "お金"]
    public_plans = YearPlan.objects.filter(is_public=True).select_related("user", "user__profile").annotate(
        public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
    ).filter(public_goal_count__gt=0)
    public_plans = public_plans.filter(visible_public_plan_filter(request.user))

    if query:
        public_plans = public_plans.filter(
            Q(list_title__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__profile__display_name__icontains=query)
            | Q(goals__title__icontains=query, goals__item_is_public=True)
        )

    public_plans = public_plans.distinct().order_by("-updated_at", "-pk")
    paginator = Paginator(public_plans, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = {}
    if query:
        query_params["q"] = query
    if result_type:
        query_params["type"] = result_type
    page_query = urlencode(query_params)
    grouped_goals = build_public_list_groups(page_obj.object_list, request.user, request=request)

    users_qs = get_user_model().objects.exclude(pk=getattr(request.user, "pk", None)).filter(
        profile__is_private=False,
    ).select_related("profile").annotate(
        followers_count=Count("follower_relations"),
    )
    if query:
        users_qs = users_qs.filter(Q(username__icontains=query) | Q(profile__display_name__icontains=query))
    users_qs = users_qs.order_by("-followers_count", "username")
    user_paginator = Paginator(users_qs, 10)
    user_page_obj = user_paginator.get_page(request.GET.get("page"))
    user_results = [build_user_row(user, request.user) for user in user_page_obj.object_list]
    recommended_users = [
        build_user_row(user, request.user)
        for user in get_user_model().objects.exclude(pk=getattr(request.user, "pk", None)).filter(
            profile__is_private=False,
        ).select_related("profile").annotate(
            followers_count=Count("follower_relations"),
        ).order_by("-followers_count", "username")[:6]
    ]

    context = {
        "goal_groups": grouped_goals,
        "page_obj": page_obj,
        "user_page_obj": user_page_obj,
        "page_query": page_query,
        "public_count": public_plans.count(),
        "done_count": sum(group["done_count"] for group in grouped_goals),
        "query": query,
        "popular_keywords": popular_keywords,
        "recommended_users": recommended_users,
        "user_results": user_results,
        "is_search_mode": is_search_mode,
        "result_type": result_type,
    }
    return render(request, "goals/public_goal_list.html", context)


def public_list_detail(request, pk):
    plan = get_object_or_404(
        YearPlan.objects.filter(is_public=True).select_related("user", "user__profile").annotate(
            public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
        ).filter(public_goal_count__gt=0).filter(visible_public_plan_filter(request.user)),
        pk=pk,
    )
    groups = build_public_list_groups([plan], request.user, request=request)
    if not groups:
        return redirect("goals:public_goal_list")
    return render(request, "goals/public_list_detail.html", {"group": groups[0]})


def public_goal_detail(request, pk):
    goal = get_object_or_404(
        YearlyGoal.objects.select_related("year_plan", "year_plan__user", "year_plan__user__profile").filter(
            visible_public_goal_filter(request.user),
        ),
        pk=pk,
    )
    year_plan = goal.year_plan
    is_saved_item = False
    can_save_item = bool(request.user.is_authenticated and year_plan.user != request.user)
    if request.user.is_authenticated:
        is_saved_item = SavedItem.objects.filter(user=request.user, item=goal).exists()
    return render(request, "goals/public_goal_detail.html", {
        "goal": goal,
        "year_plan": year_plan,
        "back_url": reverse("goals:public_list_detail", kwargs={"pk": year_plan.pk}),
        "back_label": year_plan.list_title or "公開リスト",
        "can_edit": False,
        "can_save_item": can_save_item,
        "is_saved_item": is_saved_item,
    })


@login_required
def saved_list_page(request):
    saved = SavedList.objects.filter(
        user=request.user,
        my_list__is_public=True,
    ).filter(
        visible_public_plan_filter(request.user, prefix="my_list__")
    ).select_related("my_list", "my_list__user", "my_list__user__profile").order_by("-created_at")
    plans = [item.my_list for item in saved]
    paginator = Paginator(plans, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    grouped_goals = build_public_list_groups(page_obj.object_list, request.user, request=request)
    return render(request, "goals/saved_list.html", {
        "goal_groups": grouped_goals,
        "page_heading": "保存したリスト",
        "page_obj": page_obj,
    })


@login_required
def saved_item_page(request):
    saved_items = SavedItem.objects.filter(
        user=request.user,
        item__item_is_public=True,
        item__year_plan__is_public=True,
    ).filter(
        visible_public_plan_filter(request.user, prefix="item__year_plan__")
    ).select_related("item", "item__year_plan", "item__year_plan__user", "item__year_plan__user__profile").order_by("-created_at")
    paginator = Paginator(saved_items, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "goals/saved_item_list.html", {
        "page_obj": page_obj,
        "saved_items": page_obj.object_list,
    })


def following_list_page(request):
    if not request.user.is_authenticated:
        return redirect("login")
    following_ids = Follow.objects.filter(follower=request.user).values_list("following_id", flat=True)
    public_plans = YearPlan.objects.filter(
        user_id__in=following_ids,
        is_public=True,
    ).select_related("user", "user__profile").annotate(
        public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
    ).filter(public_goal_count__gt=0).order_by("-updated_at", "-pk")
    paginator = Paginator(public_plans, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    grouped_goals = build_public_list_groups(page_obj.object_list, request.user, request=request)
    return render(request, "goals/following_list.html", {
        "goal_groups": grouped_goals,
        "page_obj": page_obj,
        "page_heading": "フォロー中の公開リスト",
    })


@login_required
def following_users_page(request):
    following = get_user_model().objects.filter(
        follower_relations__follower=request.user,
    ).select_related("profile").order_by("username")
    user_rows = [build_user_row(user, request.user) for user in following]
    return render(request, "goals/follow_user_list.html", {
        "user_rows": user_rows,
        "page_heading": "フォロー",
        "empty_message": "フォロー中のユーザーはまだいません。",
    })


@login_required
def followers_page(request):
    followers = get_user_model().objects.filter(
        following_relations__following=request.user,
    ).select_related("profile").order_by("username")
    user_rows = [build_user_row(user, request.user) for user in followers]
    return render(request, "goals/follow_user_list.html", {
        "user_rows": user_rows,
        "page_heading": "フォロワー",
        "empty_message": "フォロワーはまだいません。",
    })


@require_POST
@login_required
def toggle_follow(request, username):
    target = get_object_or_404(get_user_model(), username=username)
    if target == request.user:
        messages.info(request, "自分自身はフォローできません。")
    else:
        follow = Follow.objects.filter(follower=request.user, following=target).first()
        if follow:
            follow.delete()
            FollowRequest.objects.filter(requester=request.user, target=target).delete()
        else:
            target_profile = getattr(target, "profile", None)
            if target_profile and target_profile.is_private:
                FollowRequest.objects.update_or_create(
                    requester=request.user,
                    target=target,
                    defaults={"status": FollowRequest.STATUS_PENDING},
                )
            else:
                Follow.objects.create(follower=request.user, following=target)
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:profile_detail", kwargs={"username": username}))


@require_POST
@login_required
def toggle_saved_list(request, pk):
    plan = get_object_or_404(YearPlan, pk=pk, is_public=True)
    if not can_view_list(request.user, plan):
        raise PermissionDenied
    if plan.user == request.user:
        messages.info(request, "自分のリストは保存対象外です。")
    else:
        saved = SavedList.objects.filter(user=request.user, my_list=plan).first()
        if saved:
            saved.delete()
            messages.success(request, "保存を解除しました。")
        else:
            SavedList.objects.create(user=request.user, my_list=plan)
            messages.success(request, "保存しました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def toggle_saved_item(request, pk):
    item = get_object_or_404(
        YearlyGoal.objects.select_related("year_plan", "year_plan__user"),
        pk=pk,
        item_is_public=True,
        year_plan__is_public=True,
    )
    if not can_view_yearly_goal(request.user, item):
        raise PermissionDenied
    if item.user == request.user or item.year_plan.user == request.user:
        messages.info(request, "自分の項目は保存対象外です。")
    else:
        saved = SavedItem.objects.filter(user=request.user, item=item).first()
        if saved:
            saved.delete()
            messages.success(request, "項目の保存を解除しました。")
        else:
            SavedItem.objects.create(user=request.user, item=item)
            messages.success(request, "項目を保存しました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def toggle_like_list(request, pk):
    plan = get_object_or_404(YearPlan, pk=pk, is_public=True)
    if not can_view_list(request.user, plan):
        raise PermissionDenied
    if plan.user == request.user:
        messages.info(request, "自分のリストはいいね対象外です。")
    else:
        liked = LikeList.objects.filter(user=request.user, my_list=plan).first()
        if liked:
            liked.delete()
            messages.success(request, "いいねを解除しました。")
        else:
            LikeList.objects.create(user=request.user, my_list=plan)
            messages.success(request, "いいねしました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
def record_list_share(request, pk):
    plan = get_object_or_404(YearPlan.objects.select_related("user"), pk=pk)
    if not can_view_year_plan(request.user, plan):
        raise PermissionDenied
    YearPlan.objects.filter(pk=plan.pk).update(share_count=F("share_count") + 1)
    plan.refresh_from_db(fields=["share_count"])
    return JsonResponse({"share_count": plan.share_count})


def template_list(request):
    query = request.GET.get("q", "").strip()
    selected_category = request.GET.get("category", "all").strip() or "all"
    available_categories = {template.get("category", "その他") for template in LIST_TEMPLATES}
    template_categories = [category for category in TEMPLATE_CATEGORIES if category in available_categories]
    if selected_category not in {"all", *template_categories}:
        selected_category = "all"

    filtered_templates = LIST_TEMPLATES
    if selected_category != "all":
        filtered_templates = [
            template for template in filtered_templates
            if template.get("category") == selected_category
        ]
    if query:
        query_lower = query.lower()
        category_labels = dict(YearlyGoal.CATEGORY_CHOICES)
        filtered_templates = [
            template for template in filtered_templates
            if query_lower in template["title"].lower()
            or query_lower in template.get("summary", "").lower()
            or query_lower in category_labels.get(template.get("category"), template.get("category", "")).lower()
            or query_lower in template.get("category", "").lower()
            or any(query_lower in title.lower() for title, _category in template["items"])
        ]

    cards = [template_card(template) for template in filtered_templates]
    cards.sort(key=lambda template: (template["usage_count"], template.get("target_count", 0), template["title"]), reverse=True)
    paginator = Paginator(cards, max(len(cards), 1))
    page_obj = paginator.get_page(request.GET.get("page"))
    page_query_params = {}
    if query:
        page_query_params["q"] = query
    if selected_category != "all":
        page_query_params["category"] = selected_category

    return render(request, "goals/template_list.html", {
        "templates": page_obj.object_list,
        "popular_templates": page_obj.object_list,
        "new_templates": [],
        "template_categories": template_categories,
        "selected_category": selected_category,
        "query": query,
        "is_search_mode": bool(query),
        "page_obj": page_obj,
        "page_query": urlencode(page_query_params),
    })


def template_detail(request, slug):
    template = get_template(slug)
    if template is None:
        return redirect("goals:template_list")
    template = template_card(template)
    category_labels = dict(YearlyGoal.CATEGORY_CHOICES)
    all_display_items = [
        {
            "title": title,
            "category": category,
            "category_label": category_labels.get(category, category),
            "is_done": False,
        }
        for title, category in template["items"]
    ]
    paginator = Paginator(all_display_items, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "goals/template_detail.html", {
        "template": template,
        "display_items": page_obj.object_list,
        "page_obj": page_obj,
        "usage_label": template["usage_label"],
    })


@require_POST
@login_required
def use_template(request, slug):
    template = get_template(slug)
    if template is None:
        messages.error(request, "テンプレートが見つかりません。")
        return redirect("goals:template_list")
    plan = YearPlan.objects.create(
        user=request.user,
        year=timezone.localdate().year,
        list_title=template["title"],
        target_count=template["target_count"],
        is_public=False,
        template_slug=template["slug"],
    )
    for title, category in template["items"]:
        YearlyGoal.objects.create(
            user=request.user,
            year_plan=plan,
            title=title,
            category=category,
            item_is_public=True,
            added_by=request.user,
        )
    messages.success(request, "テンプレートからマイリストを作成しました。")
    return redirect("goals:my_list_detail", pk=plan.pk)


@require_POST
@login_required
def request_together(request, pk):
    goal = get_object_or_404(
        YearlyGoal.objects.select_related("user", "year_plan"),
        pk=pk,
        item_is_public=True,
        year_plan__is_public=True,
    )
    if not can_view_yearly_goal(request.user, goal):
        raise PermissionDenied
    if goal.user == request.user:
        messages.info(request, "自分の項目にはリクエストできません。")
    else:
        together_request, created = TogetherRequest.objects.get_or_create(
            requester=request.user,
            receiver=goal.user,
            list_item=goal,
            defaults={"status": TogetherRequest.STATUS_PENDING},
        )
        if created:
            messages.success(request, "一緒にやりたいリクエストを送りました。")
        elif together_request.status == TogetherRequest.STATUS_ACCEPTED:
            messages.info(request, "この項目は一緒にやる予定です。")
        else:
            messages.info(request, "この項目はリクエスト済みです。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def respond_together_request(request, pk, status):
    together_request = get_object_or_404(TogetherRequest, pk=pk, receiver=request.user)
    if status not in [TogetherRequest.STATUS_ACCEPTED, TogetherRequest.STATUS_REJECTED]:
        messages.error(request, "不正なステータスです。")
    else:
        together_request.status = status
        together_request.save(update_fields=["status"])
        messages.success(request, "リクエストを更新しました。")
    return redirect("goals:together_requests")


@login_required
def together_requests_page(request):
    received_requests = TogetherRequest.objects.filter(receiver=request.user).select_related(
        "requester", "requester__profile", "list_item", "list_item__year_plan"
    )
    sent_requests = TogetherRequest.objects.filter(requester=request.user).select_related(
        "receiver", "receiver__profile", "list_item", "list_item__year_plan"
    )
    return render(request, "goals/together_requests.html", {
        "received_requests": received_requests,
        "sent_requests": sent_requests,
    })


@require_POST
@login_required
def add_list_comment(request, pk):
    plan = get_object_or_404(YearPlan, pk=pk, is_public=True)
    if not can_view_list(request.user, plan):
        raise PermissionDenied
    form = ListCommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.user = request.user
        comment.my_list = plan
        comment.save()
        messages.success(request, "コメントを投稿しました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def delete_list_comment(request, pk):
    comment = get_object_or_404(ListComment, pk=pk, user=request.user)
    comment.delete()
    messages.success(request, "コメントを削除しました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def add_public_goal_to_idea(request, pk):
    goal = get_object_or_404(
        YearlyGoal.objects.select_related("year_plan"),
        pk=pk,
        item_is_public=True,
        year_plan__is_public=True,
    )
    if not can_view_yearly_goal(request.user, goal):
        raise PermissionDenied
    note_lines = []
    note_lines.append(f"カテゴリ: {goal.get_category_display()}")
    if goal.description:
        note_lines.append(goal.description)
    note_lines.append("みんなのリストから追加")
    note = "\n".join(note_lines)

    if IdeaMemo.objects.filter(user=request.user, title=goal.title).exists():
        WantToTry.objects.get_or_create(user=request.user, source_item=goal)
        messages.info(request, "この項目はすでに追加済みです。")
        return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))

    _, created = WantToTry.objects.get_or_create(user=request.user, source_item=goal)
    if not created:
        messages.info(request, "この項目はすでに追加済みです。")
        return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))

    IdeaMemo.objects.create(user=request.user, title=goal.title, note=note)
    messages.success(request, "みんなのリストから思いつきメモに追加しました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:public_goal_list"))


@require_POST
@login_required
def add_goal_link(request, pk):
    goal = get_object_or_404(YearlyGoal.objects.select_related("year_plan"), pk=pk)
    if not can_edit_yearly_goal(request.user, goal):
        raise PermissionDenied
    form = GoalLinkForm(request.POST)
    if form.is_valid():
        link = form.save(commit=False)
        link.goal = goal
        link.save()
        touch_year_plan(goal.year_plan)
    return redirect("goals:yearly_goal_edit", pk=goal.pk)


@require_POST
@login_required
def delete_goal_link(request, pk):
    link = get_object_or_404(GoalLink.objects.select_related("goal", "goal__year_plan"), pk=pk)
    if not can_edit_yearly_goal(request.user, link.goal):
        raise PermissionDenied
    goal = link.goal
    link.delete()
    touch_year_plan(goal.year_plan)
    return redirect("goals:yearly_goal_edit", pk=goal.pk)


@require_POST
@login_required
def add_goal_image(request, pk):
    goal = get_object_or_404(YearlyGoal.objects.select_related("year_plan"), pk=pk)
    if not can_edit_yearly_goal(request.user, goal):
        raise PermissionDenied
    form = GoalImageForm(request.POST, request.FILES)
    if form.is_valid():
        image = form.save(commit=False)
        image.goal = goal
        image.save()
        touch_year_plan(goal.year_plan)
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("goals:yearly_goal_edit", pk=goal.pk)


@require_POST
@login_required
def delete_goal_image(request, pk):
    image = get_object_or_404(GoalImage.objects.select_related("goal", "goal__year_plan"), pk=pk)
    if not can_edit_yearly_goal(request.user, image.goal):
        raise PermissionDenied
    goal = image.goal
    image_name = image.image.name if image.image else ""
    image_storage = image.image.storage if image.image else None
    image_pk = image.pk
    image.delete()
    delete_media_file_if_unreferenced(image_name, image_storage, goal_image_pk=image_pk)
    touch_year_plan(goal.year_plan)
    return redirect("goals:yearly_goal_edit", pk=goal.pk)


def toggle_done(request, model_name, pk):
    model_map = {
        "yearly": YearlyGoal,
        "monthly": MonthlyGoal,
        "weekly": WeeklyGoal,
        "today": TodayTask,
    }
    model = model_map[model_name]
    if not request.user.is_authenticated:
        return redirect("login")
    if model_name == "yearly":
        item = get_object_or_404(model, pk=pk, user=request.user)
    else:
        item = get_object_or_404(model, pk=pk, user=request.user)

    if request.method == "POST" and model_name == "yearly":
        was_done = item.is_done
        item.is_done = request.POST.get("is_done") == "1"
        if item.is_done:
            completed_date = parse_date(request.POST.get("completed_date", ""))
            item.completed_date = completed_date or timezone.localdate()
        else:
            item.completed_date = None
        item.save(update_fields=["is_done", "completed_date", "updated_at"])
        touch_year_plan(item.year_plan)
        return redirect(request.META.get("HTTP_REFERER") or reverse("goals:yearly_goal_list"))

    was_done = item.is_done
    item.is_done = not item.is_done
    update_fields = ["is_done", "updated_at"]
    if model_name == "yearly" and not item.is_done:
        item.completed_date = None
        update_fields.append("completed_date")
    item.save(update_fields=update_fields)
    if model_name == "yearly":
        touch_year_plan(item.year_plan)
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:home"))


class YearlyGoalCreateView(LoginRequiredMixin, CreateView):
    model = YearlyGoal
    form_class = YearlyGoalCreateForm
    template_name = "goals/form.html"
    extra_context = {"title": "マイリスト項目を追加", "cancel_url": reverse_lazy("goals:yearly_goal_list")}

    def get_year_plan(self):
        plan_pk = self.request.GET.get("list") or self.request.POST.get("list")
        if plan_pk:
            plan = get_object_or_404(YearPlan, pk=plan_pk)
            if not can_edit_year_plan_items(self.request.user, plan):
                raise PermissionDenied
            return plan
        return get_default_year_plan(self.request.user)

    def form_valid(self, form):
        year_plan = self.get_year_plan()
        if year_plan_item_limit_reached(year_plan):
            form.add_error(None, item_limit_message())
            return self.form_invalid(form)
        form.instance.user = year_plan.user
        form.instance.year_plan = year_plan
        form.instance.added_by = self.request.user
        response = super().form_valid(form)
        touch_year_plan(form.instance.year_plan)
        return response

    def get_success_url(self):
        return reverse("goals:my_list_detail", kwargs={"pk": self.object.year_plan_id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan_pk = self.request.GET.get("list")
        if plan_pk:
            context["cancel_url"] = reverse("goals:my_list_detail", kwargs={"pk": plan_pk})
        return context


class YearlyGoalUpdateView(LoginRequiredMixin, UpdateView):
    model = YearlyGoal
    form_class = YearlyGoalCreateForm
    template_name = "goals/form.html"
    extra_context = {
        "title": "マイリスト項目を編集",
        "cancel_url": reverse_lazy("goals:yearly_goal_list"),
        "actions_in_title": True,
    }

    def get_queryset(self):
        return YearlyGoal.objects.select_related("year_plan").filter(
            Q(year_plan__user=self.request.user)
            | Q(year_plan__collaborators=self.request.user, added_by=self.request.user)
        ).distinct()

    def form_valid(self, form):
        response = super().form_valid(form)
        touch_year_plan(form.instance.year_plan)
        return response

    def get_success_url(self):
        return reverse("goals:yearly_goal_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.year_plan_id:
            context["cancel_url"] = reverse("goals:my_list_detail", kwargs={"pk": self.object.year_plan_id})
            context["form_back_label"] = "← リスト詳細へ戻る"
        return context


class YearlyGoalDeleteView(LoginRequiredMixin, DeleteView):
    model = YearlyGoal
    template_name = "goals/confirm_delete.html"
    extra_context = {"cancel_url": reverse_lazy("goals:yearly_goal_list")}

    def get_queryset(self):
        return YearlyGoal.objects.filter(user=self.request.user)

    def form_valid(self, form):
        self.year_plan = self.object.year_plan
        response = super().form_valid(form)
        touch_year_plan(self.year_plan)
        return response

    def get_success_url(self):
        if self.year_plan:
            return reverse("goals:my_list_detail", kwargs={"pk": self.year_plan.pk})
        return reverse("goals:yearly_goal_list")


class UserFormKwargsMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


class YearPlanCreateView(LoginRequiredMixin, CreateView):
    model = YearPlan
    form_class = YearPlanForm
    template_name = "goals/form.html"
    extra_context = {
        "title": "マイリストを作成",
        "cancel_url": reverse_lazy("goals:yearly_goal_list"),
        "actions_in_title": True,
    }

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.year = timezone.localdate().year
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("goals:my_list_detail", kwargs={"pk": self.object.pk})


class YearPlanUpdateView(LoginRequiredMixin, UpdateView):
    model = YearPlan
    form_class = YearPlanForm
    template_name = "goals/form.html"
    extra_context = {
        "title": "リスト設定",
        "cancel_url": reverse_lazy("goals:yearly_goal_list"),
        "actions_in_title": True,
    }

    def get_queryset(self):
        return YearPlan.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("goals:my_list_detail", kwargs={"pk": self.object.pk})
        return context

    def get_success_url(self):
        return reverse("goals:my_list_detail", kwargs={"pk": self.object.pk})


class YearPlanDeleteView(LoginRequiredMixin, DeleteView):
    model = YearPlan
    template_name = "goals/confirm_delete.html"
    success_url = reverse_lazy("goals:yearly_goal_list")
    extra_context = {"cancel_url": reverse_lazy("goals:yearly_goal_list")}

    def get_queryset(self):
        return YearPlan.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cancel_url"] = reverse("goals:my_list_detail", kwargs={"pk": self.object.pk})
        return context


class MonthlyGoalCreateView(LoginRequiredMixin, UserFormKwargsMixin, CreateView):
    model = MonthlyGoal
    form_class = MonthlyGoalForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:monthly_goal_list")
    extra_context = {"title": "月の目標を追加", "cancel_url": reverse_lazy("goals:monthly_goal_list")}

    def form_valid(self, form):
        form.instance.user = self.request.user
        if not form.instance.target_month:
            form.instance.target_month = month_start_for(timezone.localdate())
        if form.instance.target_month:
            form.instance.month = form.instance.target_month
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:monthly_goal_list')}?month={self.object.target_month:%Y-%m-%d}"


class MonthlyGoalUpdateView(LoginRequiredMixin, UserFormKwargsMixin, UpdateView):
    model = MonthlyGoal
    form_class = MonthlyGoalForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:monthly_goal_list")
    extra_context = {"title": "月の目標を編集", "cancel_url": reverse_lazy("goals:monthly_goal_list")}

    def get_queryset(self):
        return MonthlyGoal.objects.filter(user=self.request.user)

    def form_valid(self, form):
        if not form.instance.target_month:
            form.instance.target_month = month_start_for(timezone.localdate())
        if form.instance.target_month:
            form.instance.month = form.instance.target_month
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:monthly_goal_list')}?month={self.object.target_month:%Y-%m-%d}"


class MonthlyGoalDeleteView(LoginRequiredMixin, DeleteView):
    model = MonthlyGoal
    template_name = "goals/confirm_delete.html"
    success_url = reverse_lazy("goals:monthly_goal_list")
    extra_context = {"cancel_url": reverse_lazy("goals:monthly_goal_list")}

    def get_queryset(self):
        return MonthlyGoal.objects.filter(user=self.request.user)


class WeeklyGoalCreateView(LoginRequiredMixin, UserFormKwargsMixin, CreateView):
    model = WeeklyGoal
    form_class = WeeklyGoalForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:weekly_goal_list")
    extra_context = {"title": "週の目標を追加", "cancel_url": reverse_lazy("goals:weekly_goal_list")}

    def form_valid(self, form):
        form.instance.user = self.request.user
        if not form.instance.week_start_date:
            form.instance.week_start_date = current_week_start()
        if form.instance.week_start_date:
            form.instance.week_start = form.instance.week_start_date
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:weekly_goal_list')}?week={self.object.week_start_date:%Y-%m-%d}"


class WeeklyGoalUpdateView(LoginRequiredMixin, UserFormKwargsMixin, UpdateView):
    model = WeeklyGoal
    form_class = WeeklyGoalForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:weekly_goal_list")
    extra_context = {"title": "週の目標を編集", "cancel_url": reverse_lazy("goals:weekly_goal_list")}

    def get_queryset(self):
        return WeeklyGoal.objects.filter(user=self.request.user)

    def form_valid(self, form):
        if not form.instance.week_start_date:
            form.instance.week_start_date = current_week_start()
        if form.instance.week_start_date:
            form.instance.week_start = form.instance.week_start_date
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:weekly_goal_list')}?week={self.object.week_start_date:%Y-%m-%d}"


class WeeklyGoalDeleteView(LoginRequiredMixin, DeleteView):
    model = WeeklyGoal
    template_name = "goals/confirm_delete.html"
    success_url = reverse_lazy("goals:weekly_goal_list")
    extra_context = {"cancel_url": reverse_lazy("goals:weekly_goal_list")}

    def get_queryset(self):
        return WeeklyGoal.objects.filter(user=self.request.user)


class TodayTaskCreateView(LoginRequiredMixin, UserFormKwargsMixin, CreateView):
    model = TodayTask
    form_class = TodayTaskForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:today_task_list")
    extra_context = {"title": "今日やることを追加", "cancel_url": reverse_lazy("goals:today_task_list")}

    def form_valid(self, form):
        form.instance.user = self.request.user
        if not form.instance.scheduled_date:
            form.instance.scheduled_date = timezone.localdate()
        if form.instance.scheduled_date:
            form.instance.date = form.instance.scheduled_date
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:today_task_list')}?date={self.object.scheduled_date:%Y-%m-%d}"


class TodayTaskUpdateView(LoginRequiredMixin, UserFormKwargsMixin, UpdateView):
    model = TodayTask
    form_class = TodayTaskForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:today_task_list")
    extra_context = {"title": "今日やることを編集", "cancel_url": reverse_lazy("goals:today_task_list")}

    def get_queryset(self):
        return TodayTask.objects.filter(user=self.request.user)

    def form_valid(self, form):
        if not form.instance.scheduled_date:
            form.instance.scheduled_date = timezone.localdate()
        if form.instance.scheduled_date:
            form.instance.date = form.instance.scheduled_date
        return super().form_valid(form)

    def get_success_url(self):
        return f"{reverse('goals:today_task_list')}?date={self.object.scheduled_date:%Y-%m-%d}"


class TodayTaskDeleteView(LoginRequiredMixin, DeleteView):
    model = TodayTask
    template_name = "goals/confirm_delete.html"
    success_url = reverse_lazy("goals:today_task_list")
    extra_context = {"cancel_url": reverse_lazy("goals:today_task_list")}

    def get_queryset(self):
        return TodayTask.objects.filter(user=self.request.user)


class IdeaMemoCreateView(LoginRequiredMixin, CreateView):
    model = IdeaMemo
    form_class = IdeaMemoForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:idea_memo_list")
    extra_context = {"title": "思いつきメモを追加", "cancel_url": reverse_lazy("goals:idea_memo_list")}

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


class IdeaMemoUpdateView(LoginRequiredMixin, UpdateView):
    model = IdeaMemo
    form_class = IdeaMemoForm
    template_name = "goals/form.html"
    success_url = reverse_lazy("goals:idea_memo_list")
    extra_context = {"title": "思いつきメモを編集", "cancel_url": reverse_lazy("goals:idea_memo_list")}

    def get_queryset(self):
        return IdeaMemo.objects.filter(user=self.request.user)


class IdeaMemoDeleteView(LoginRequiredMixin, DeleteView):
    model = IdeaMemo
    template_name = "goals/confirm_delete.html"
    success_url = reverse_lazy("goals:idea_memo_list")
    extra_context = {"cancel_url": reverse_lazy("goals:idea_memo_list")}

    def get_queryset(self):
        return IdeaMemo.objects.filter(user=self.request.user)
