from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0024_yearplan_share_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="yearplan",
            name="template_slug",
            field=models.SlugField(blank=True, db_index=True, max_length=80, verbose_name="Template slug"),
        ),
    ]
