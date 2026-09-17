# Generated manually for ChatRoom.Kind.THEMATIC

from django.db import migrations, models


def convert_staff_thematic_rooms(apps, schema_editor):
    """
    Reclasse les salons EVENT sans événement (créés via l’UI staff) en thématiques.
    Conserve « Montaigu Joy » en salon privé ad hoc (EVENT sans Event).
    """
    ChatRoom = apps.get_model("chat", "ChatRoom")
    qs = ChatRoom.objects.filter(kind="event", event_id__isnull=True)
    for room in qs:
        title = (room.title or "").strip().casefold()
        if title == "montaigu joy":
            continue
        room.kind = "thematic"
        room.save(update_fields=["kind"])


def revert_thematic_to_event(apps, schema_editor):
    ChatRoom = apps.get_model("chat", "ChatRoom")
    ChatRoom.objects.filter(kind="thematic").update(kind="event")


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0015_chatmessage_thread_event"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatroom",
            name="kind",
            field=models.CharField(
                choices=[
                    ("orchestra", "Orchestre"),
                    ("rehearsals", "Répétitions"),
                    ("event", "Événement"),
                    ("thematic", "Thématique"),
                    ("piece", "Morceau"),
                    ("staff", "Staff"),
                    ("section", "Pupitre"),
                ],
                db_index=True,
                max_length=20,
                verbose_name="Type",
            ),
        ),
        migrations.RunPython(convert_staff_thematic_rooms, revert_thematic_to_event),
    ]
