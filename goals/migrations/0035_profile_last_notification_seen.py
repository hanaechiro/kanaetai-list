from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0034_unique_lower_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="last_notification_seen",
            field=models.DateTimeField(blank=True, null=True, verbose_name="最後に通知を確認した日時"),
        ),
    ]
