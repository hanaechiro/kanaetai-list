from datetime import timedelta
from math import ceil

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.db.models import Count, Max, Q, Sum
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import urlencode
from django.views.generic import CreateView, DeleteView, UpdateView
from django.views.decorators.http import require_POST

from .forms import (
    IdeaMemoForm,
    ListCommentForm,
    MonthlyGoalForm,
    ProfileForm,
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
    GoalSetting,
    Follow,
    IdeaMemo,
    ListComment,
    LikeList,
    MonthlyGoal,
    Profile,
    SavedList,
    TodayTask,
    TogetherRequest,
    WantToTry,
    WeeklyGoal,
    YearlyGoal,
    YearPlan,
)


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
]


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


def progress_percent(done_count, total_count):
    if total_count <= 0:
        return 0
    return min(round(done_count / total_count * 100), 100)


def profile_stats(user):
    public_plans = YearPlan.objects.filter(user=user, is_public=True)
    goals = YearlyGoal.objects.filter(user=user)
    return {
        "public_list_count": public_plans.count(),
        "done_item_count": goals.filter(is_done=True).count(),
        "liked_count": LikeList.objects.filter(my_list__user=user).count(),
        "saved_count": SavedList.objects.filter(my_list__user=user).count(),
        "following_count": Follow.objects.filter(follower=user).count(),
        "followers_count": Follow.objects.filter(following=user).count(),
    }


def get_template(slug):
    return next((template for template in LIST_TEMPLATES if template["slug"] == slug), None)


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


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            Profile.objects.get_or_create(user=user, defaults={"display_name": user.username})
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


@login_required
def my_profile(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"display_name": request.user.username},
    )
    plans = YearPlan.objects.filter(user=request.user).select_related("user", "user__profile").order_by("-updated_at", "-pk")
    goal_groups = build_public_list_groups(plans, request.user, request=request, include_private=True)
    return render(request, "goals/profile.html", {
        "profile_user": request.user,
        "profile": profile,
        "goal_groups": goal_groups,
        "is_own_profile": True,
        "profile_stats": profile_stats(request.user),
        "is_following": False,
    })


@login_required
def edit_profile(request):
    profile, _ = Profile.objects.get_or_create(
        user=request.user,
        defaults={"display_name": request.user.username},
    )
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "プロフィールを保存しました。")
            return redirect("goals:my_profile")
    else:
        form = ProfileForm(instance=profile)
    return render(request, "goals/form.html", {
        "form": form,
        "title": "プロフィール編集",
        "cancel_url": reverse_lazy("goals:my_profile"),
    })


def profile_detail(request, username):
    user = get_object_or_404(get_user_model(), username=username)
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"display_name": user.username})
    if request.user.is_authenticated and request.user == user:
        return redirect("goals:my_profile")
    public_plans = YearPlan.objects.filter(user=user, is_public=True).select_related("user", "user__profile").order_by("-updated_at", "-pk")
    goal_groups = build_public_list_groups(public_plans, request.user, request=request)
    is_following = False
    if request.user.is_authenticated:
        is_following = Follow.objects.filter(follower=request.user, following=user).exists()
    return render(request, "goals/profile.html", {
        "profile_user": user,
        "profile": profile,
        "goal_groups": goal_groups,
        "is_own_profile": False,
        "profile_stats": profile_stats(user),
        "is_following": is_following,
    })


@login_required
def yearly_goal_list(request):
    plans = YearPlan.objects.filter(user=request.user).annotate(
        goals_count=Count("goals"),
        goals_done_count=Count("goals", filter=Q(goals__is_done=True)),
    ).order_by("-updated_at", "-pk")
    plans = list(plans)
    for plan in plans:
        plan.progress_percent = progress_percent(plan.goals_done_count, plan.goals_count)
    paginator = Paginator(plans, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "goals/yearly_goal_list.html", {
        "page_obj": page_obj,
        "plans": page_obj.object_list,
    })


@login_required
def my_list_detail(request, pk):
    year_plan = get_object_or_404(YearPlan, pk=pk, user=request.user)

    if request.method == "POST":
        setting_form = YearPlanForm(request.POST, instance=year_plan)
        if setting_form.is_valid():
            setting_form.save()
            messages.success(request, "マイリスト設定を保存しました。")
            return redirect("goals:my_list_detail", pk=year_plan.pk)
    else:
        setting_form = YearPlanForm(instance=year_plan)

    all_goals = YearlyGoal.objects.filter(user=request.user, year_plan=year_plan).prefetch_related(
        "monthly_goals__weekly_goals__today_tasks",
    ).order_by("created_at")
    goals = all_goals
    done_count = all_goals.filter(is_done=True).count()
    total_count = all_goals.count()
    year_plan.progress_percent = progress_percent(done_count, total_count)
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
        "current_page": current_page,
        "total_pages": total_pages,
        "previous_page": current_page - 1 if current_page > 1 else None,
        "next_page": current_page + 1 if current_page < total_pages else None,
        "current_year": year_plan.year,
    }
    return render(request, "goals/my_list_detail.html", context)


@login_required
def yearly_goal_detail(request, pk):
    goal = get_object_or_404(
        YearlyGoal.objects.prefetch_related("monthly_goals__weekly_goals__today_tasks"),
        pk=pk,
        user=request.user,
    )
    year_plan = goal.year_plan or get_default_year_plan(request.user)
    return render(request, "goals/yearly_goal_detail.html", {"goal": goal, "year_plan": year_plan})


@require_POST
@login_required
def add_my_list_goal_inline(request, pk):
    year_plan = get_object_or_404(YearPlan, pk=pk, user=request.user)
    form = YearlyGoalInlineCreateForm(request.POST)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if form.is_valid():
        goal = form.save(commit=False)
        goal.user = request.user
        goal.year_plan = year_plan
        goal.save()
        touch_year_plan(year_plan)
        if is_ajax:
            html = render_to_string(
                "goals/partials/yearly_notebook_goal.html",
                {"goal": goal},
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
            "total_count": plan.goals.count() if include_private else plan.goals.filter(item_is_public=True).count(),
            "like_count": plan.liked_by.count(),
            "save_count": plan.saved_by.count(),
            "is_saved": False,
            "is_liked": False,
            "can_react": bool(request_user and request_user.is_authenticated and request_user != plan.user),
            "show_item_privacy": include_private,
            "comment_form": ListCommentForm(),
            "comments": plan.comments.select_related("user", "user__profile").all(),
            "goals": [],
        }
        grouped_goals.append(groups_by_plan[plan.pk])

    if request_user and request_user.is_authenticated:
        saved_plan_ids = set(SavedList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
        liked_plan_ids = set(LikeList.objects.filter(user=request_user, my_list_id__in=plan_ids).values_list("my_list_id", flat=True))
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
    else:
        wanted_item_ids = set()
        together_statuses = {}
        memo_titles = set()
        following_user_ids = set()

    for goal in goals:
        group = groups_by_plan.get(goal.year_plan_id)
        if group:
            goal.is_wanted_by_current_user = goal.pk in wanted_item_ids or goal.title in memo_titles
            goal.together_status_for_current_user = together_statuses.get(goal.pk)
            group["goals"].append(goal)

    for group in grouped_goals:
        group["progress_percent"] = progress_percent(group["done_count"], group["total_count"])
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
    category = request.GET.get("category", "").strip()
    public_plans = YearPlan.objects.filter(is_public=True).select_related("user", "user__profile").annotate(
        public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
    ).filter(public_goal_count__gt=0)

    if query:
        matched_categories = [
            value for value, label in YearlyGoal.CATEGORY_CHOICES
            if query.lower() in label.lower() or query.lower() in value.lower()
        ]
        public_plans = public_plans.filter(
            Q(list_title__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__profile__display_name__icontains=query)
            | Q(goals__title__icontains=query, goals__item_is_public=True)
            | Q(goals__category__icontains=query, goals__item_is_public=True)
            | Q(goals__category__in=matched_categories, goals__item_is_public=True)
        )
    if category:
        public_plans = public_plans.filter(goals__category=category, goals__item_is_public=True)

    public_plans = public_plans.distinct().order_by("-updated_at", "-pk")
    paginator = Paginator(public_plans, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = {}
    if query:
        query_params["q"] = query
    if category:
        query_params["category"] = category
    page_query = urlencode(query_params)
    grouped_goals = build_public_list_groups(page_obj.object_list, request.user, category=category, request=request)

    context = {
        "goal_groups": grouped_goals,
        "page_obj": page_obj,
        "page_query": page_query,
        "public_count": public_plans.count(),
        "done_count": sum(group["done_count"] for group in grouped_goals),
        "categories": YearlyGoal.CATEGORY_CHOICES,
        "selected_category": category,
        "query": query,
    }
    return render(request, "goals/public_goal_list.html", context)


def public_list_detail(request, pk):
    plan = get_object_or_404(
        YearPlan.objects.filter(is_public=True).select_related("user", "user__profile").annotate(
            public_goal_count=Count("goals", filter=Q(goals__item_is_public=True)),
        ).filter(public_goal_count__gt=0),
        pk=pk,
    )
    groups = build_public_list_groups([plan], request.user, request=request)
    if not groups:
        return redirect("goals:public_goal_list")
    return render(request, "goals/public_list_detail.html", {"group": groups[0]})


@login_required
def saved_list_page(request):
    saved = SavedList.objects.filter(
        user=request.user,
        my_list__is_public=True,
    ).select_related("my_list", "my_list__user", "my_list__user__profile").order_by("-created_at")
    plans = [item.my_list for item in saved]
    grouped_goals = build_public_list_groups(plans, request.user, request=request)
    return render(request, "goals/saved_list.html", {"goal_groups": grouped_goals, "page_heading": "保存したリスト"})


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
            messages.success(request, "フォローを解除しました。")
        else:
            Follow.objects.create(follower=request.user, following=target)
            messages.success(request, "フォローしました。")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:profile_detail", kwargs={"username": username}))


@require_POST
@login_required
def toggle_saved_list(request, pk):
    plan = get_object_or_404(YearPlan, pk=pk, is_public=True)
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
def toggle_like_list(request, pk):
    plan = get_object_or_404(YearPlan, pk=pk, is_public=True)
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


def template_list(request):
    return render(request, "goals/template_list.html", {"templates": LIST_TEMPLATES})


def template_detail(request, slug):
    template = get_template(slug)
    if template is None:
        return redirect("goals:template_list")
    category_labels = dict(YearlyGoal.CATEGORY_CHOICES)
    display_items = [
        {
            "title": title,
            "category": category,
            "category_label": category_labels.get(category, category),
        }
        for title, category in template["items"]
    ]
    return render(request, "goals/template_detail.html", {
        "template": template,
        "display_items": display_items,
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
    )
    for title, category in template["items"]:
        YearlyGoal.objects.create(
            user=request.user,
            year_plan=plan,
            title=title,
            category=category,
            item_is_public=True,
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
        if item.is_done and not was_done:
            messages.success(request, "達成おめでとう！")
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
    if item.is_done and not was_done:
        messages.success(request, "達成おめでとう！")
    return redirect(request.META.get("HTTP_REFERER") or reverse("goals:home"))


class YearlyGoalCreateView(LoginRequiredMixin, CreateView):
    model = YearlyGoal
    form_class = YearlyGoalCreateForm
    template_name = "goals/form.html"
    extra_context = {"title": "マイリスト項目を追加", "cancel_url": reverse_lazy("goals:yearly_goal_list")}

    def get_year_plan(self):
        plan_pk = self.request.GET.get("list") or self.request.POST.get("list")
        if plan_pk:
            return get_object_or_404(YearPlan, pk=plan_pk, user=self.request.user)
        return get_default_year_plan(self.request.user)

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.year_plan = self.get_year_plan()
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
    form_class = YearlyGoalForm
    template_name = "goals/form.html"
    extra_context = {
        "title": "マイリスト項目を編集",
        "cancel_url": reverse_lazy("goals:yearly_goal_list"),
        "actions_in_title": True,
    }

    def get_queryset(self):
        return YearlyGoal.objects.filter(user=self.request.user)

    def form_valid(self, form):
        if not form.cleaned_data.get("is_done"):
            form.instance.completed_date = None
        response = super().form_valid(form)
        touch_year_plan(form.instance.year_plan)
        return response

    def get_success_url(self):
        return reverse("goals:yearly_goal_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.year_plan_id:
            context["cancel_url"] = reverse("goals:yearly_goal_detail", kwargs={"pk": self.object.pk})
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
