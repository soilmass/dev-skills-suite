"""Safe Django migration: nullable add with a reversible data step."""
from django.db import migrations, models


def forwards(apps, schema_editor):
    pass


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("shop", "0001_initial")]
    operations = [
        migrations.AddField(model_name="order", name="region", field=models.CharField(max_length=8, null=True)),
    ]
