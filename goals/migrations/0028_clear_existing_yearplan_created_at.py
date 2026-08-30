from django.db import migrations


def clear_existing_yearplan_created_at(apps, schema_editor):
    YearPlan = apps.get_model("goals", "YearPlan")
    YearPlan.objects.update(created_at=None)


class Migration(migrations.Migration):

    dependencies = [
        ("goals", "0027_yearplan_created_at_useractivity"),
    ]

    operations = [
        migrations.RunPython(clear_existing_yearplan_created_at, migrations.RunPython.noop),
    ]
