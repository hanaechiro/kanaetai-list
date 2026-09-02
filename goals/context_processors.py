from django.db import connection

from .models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    LikeList,
    Profile,
    SavedList,
    YearPlan,
)


def _notification_count_sql(user_id, last_seen):
    def seen_clause(column_name):
        if last_seen is None:
            return "", []
        return f" AND {column_name} > %s", [last_seen]

    follow_request_seen_sql, follow_request_seen_params = seen_clause("fr.created_at")
    collaboration_seen_sql, collaboration_seen_params = seen_clause("ci.created_at")
    follow_seen_sql, follow_seen_params = seen_clause("f.created_at")
    like_seen_sql, like_seen_params = seen_clause("ll.created_at")
    save_seen_sql, save_seen_params = seen_clause("sl.created_at")

    query = f"""
        SELECT
            (SELECT COUNT(*)
             FROM {FollowRequest._meta.db_table} fr
             WHERE fr.target_id = %s
               AND fr.status = %s{follow_request_seen_sql}) AS follow_request_count,
            (SELECT COUNT(*)
             FROM {CollaborationInvite._meta.db_table} ci
             WHERE ci.invitee_id = %s
               AND ci.status = %s{collaboration_seen_sql}) AS collaboration_invite_count,
            (SELECT COUNT(*)
             FROM {Follow._meta.db_table} f
             WHERE f.following_id = %s
               AND f.follower_id <> %s{follow_seen_sql}) AS new_follow_count,
            (SELECT COUNT(*)
             FROM {LikeList._meta.db_table} ll
             INNER JOIN {YearPlan._meta.db_table} yp ON yp.id = ll.my_list_id
             WHERE yp.user_id = %s
               AND ll.user_id <> %s{like_seen_sql}) AS like_notification_count,
            (SELECT COUNT(*)
             FROM {SavedList._meta.db_table} sl
             INNER JOIN {YearPlan._meta.db_table} yp2 ON yp2.id = sl.my_list_id
             WHERE yp2.user_id = %s
               AND sl.user_id <> %s{save_seen_sql}) AS save_notification_count
    """

    params = [
        user_id,
        FollowRequest.STATUS_PENDING,
        *follow_request_seen_params,
        user_id,
        CollaborationInvite.STATUS_PENDING,
        *collaboration_seen_params,
        user_id,
        user_id,
        *follow_seen_params,
        user_id,
        user_id,
        *like_seen_params,
        user_id,
        user_id,
        *save_seen_params,
    ]

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone() or (0, 0, 0, 0, 0)

    return {
        "follow_request_count": row[0] or 0,
        "collaboration_invite_count": row[1] or 0,
        "new_follow_count": row[2] or 0,
        "like_notification_count": row[3] or 0,
        "save_notification_count": row[4] or 0,
    }


def notification_counts(request):
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0}

    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = Profile.objects.create(user=request.user, display_name=request.user.username)
    last_seen = profile.last_notification_seen

    counts = _notification_count_sql(request.user.pk, last_seen)
    unread_count = sum(counts.values())
    return {"unread_notification_count": unread_count}
