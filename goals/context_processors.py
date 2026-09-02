from .models import (
    CollaborationInvite,
    Follow,
    FollowRequest,
    LikeList,
    Profile,
    SavedList,
)


def notification_counts(request):
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0}

    profile, _ = Profile.objects.get_or_create(user=request.user, defaults={"display_name": request.user.username})
    last_seen = profile.last_notification_seen

    follow_request_count = FollowRequest.objects.filter(target=request.user, status=FollowRequest.STATUS_PENDING)
    collaboration_invite_count = CollaborationInvite.objects.filter(invitee=request.user, status=CollaborationInvite.STATUS_PENDING)
    new_follow_count = Follow.objects.filter(following=request.user).exclude(follower=request.user)
    like_notification_count = LikeList.objects.filter(my_list__user=request.user).exclude(user=request.user)
    save_notification_count = SavedList.objects.filter(my_list__user=request.user).exclude(user=request.user)

    if last_seen:
        follow_request_count = follow_request_count.filter(created_at__gt=last_seen)
        collaboration_invite_count = collaboration_invite_count.filter(created_at__gt=last_seen)
        new_follow_count = new_follow_count.filter(created_at__gt=last_seen)
        like_notification_count = like_notification_count.filter(created_at__gt=last_seen)
        save_notification_count = save_notification_count.filter(created_at__gt=last_seen)

    unread_count = (
        follow_request_count.count()
        + collaboration_invite_count.count()
        + new_follow_count.count()
        + like_notification_count.count()
        + save_notification_count.count()
    )
    return {"unread_notification_count": unread_count}
