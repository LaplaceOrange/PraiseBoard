from django.db import migrations, models
from django.db.migrations.recorder import MigrationRecorder


def clear_legacy_praise_points(apps, schema_editor):
    connection = schema_editor.connection
    migration = MigrationRecorder(connection).migration_qs.using(connection.alias).get(
        app="board",
        name="0002_classroom_scoring_version_praiseitem_points_and_more",
    )
    PraiseItem = apps.get_model("board", "PraiseItem")
    PraiseItem.objects.using(connection.alias).filter(
        created_at__lt=migration.applied,
    ).update(points=0)


class Migration(migrations.Migration):

    dependencies = [
        ("board", "0002_classroom_scoring_version_praiseitem_points_and_more"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_praise_points, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="praiseitem",
            name="points",
            field=models.DecimalField(
                decimal_places=2,
                default=1,
                max_digits=12,
                verbose_name="每人加分",
            ),
        ),
    ]
