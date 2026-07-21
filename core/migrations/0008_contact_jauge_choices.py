from django.db import migrations, models


def convert_jauge_forward(apps, schema_editor):
    ContactMessage = apps.get_model("core", "ContactMessage")
    mapping = {
        50: "50",
        100: "100",
        150: "150",
        250: "250",
    }
    for msg in ContactMessage.objects.exclude(jauge_old__isnull=True):
        val = msg.jauge_old
        if val is None:
            continue
        if val >= 500:
            msg.jauge = "500plus"
        else:
            # nearest bucket
            msg.jauge = mapping.get(val) or (
                "50" if val <= 50
                else "100" if val <= 100
                else "150" if val <= 150
                else "250" if val <= 250
                else "500plus"
            )
        msg.save(update_fields=["jauge"])


def convert_jauge_backward(apps, schema_editor):
    ContactMessage = apps.get_model("core", "ContactMessage")
    mapping = {
        "50": 50,
        "100": 100,
        "150": 150,
        "250": 250,
        "500plus": 500,
    }
    for msg in ContactMessage.objects.exclude(jauge=""):
        msg.jauge_old = mapping.get(msg.jauge)
        msg.save(update_fields=["jauge_old"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_contact_prestation_and_staff_notify"),
    ]

    operations = [
        migrations.RenameField(
            model_name="contactmessage",
            old_name="jauge",
            new_name="jauge_old",
        ),
        migrations.AddField(
            model_name="contactmessage",
            name="jauge",
            field=models.CharField(
                blank=True,
                choices=[
                    ("50", "50"),
                    ("100", "100"),
                    ("150", "150"),
                    ("250", "250"),
                    ("500plus", "500 et +"),
                ],
                default="",
                max_length=20,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(convert_jauge_forward, convert_jauge_backward),
        migrations.RemoveField(
            model_name="contactmessage",
            name="jauge_old",
        ),
    ]
