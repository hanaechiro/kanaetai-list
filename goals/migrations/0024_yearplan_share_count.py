from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0023_yearplan_description_yearplan_icon"),
    ]

    operations = [
        migrations.AddField(
            model_name="yearplan",
            name="share_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Share count"),
        ),
    ]
