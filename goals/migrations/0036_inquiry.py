from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0035_profile_last_notification_seen"),
    ]

    operations = [
        migrations.CreateModel(
            name="Inquiry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, verbose_name="名前")),
                ("email", models.EmailField(max_length=254, verbose_name="返信先メールアドレス")),
                ("message", models.TextField(max_length=2000, verbose_name="問い合わせ内容")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "未対応"), ("done", "対応済み")],
                        default="pending",
                        max_length=20,
                        verbose_name="対応状態",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="作成日時")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
