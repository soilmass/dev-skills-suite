"""Planted Django migration: every risky operation in one file."""
from django.db import migrations, models


def forwards(apps, schema_editor):
    Order = apps.get_model("shop", "Order")
    Order.objects.filter(status="").update(status="open")


class Migration(migrations.Migration):
    dependencies = [("shop", "0002_safe")]
    operations = [
        migrations.RemoveField(model_name="order", name="notes"),
        migrations.AddField(model_name="order", name="currency", field=models.CharField(max_length=3)),
        migrations.AlterField(model_name="order", name="total", field=models.IntegerField()),
        migrations.AddIndex(model_name="order", index=models.Index(fields=["customer"], name="ix_order_customer")),
        migrations.RunPython(forwards),
    ]
