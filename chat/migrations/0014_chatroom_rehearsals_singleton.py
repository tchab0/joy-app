# Salon unique « Répétitions » + désactivation des salons par date de répé.

from django.db import migrations, models


def create_rehearsals_room_and_deactivate_old(apps, schema_editor):
    ChatRoom = apps.get_model("chat", "ChatRoom")
    Event = apps.get_model("events", "Event")
    EventType = apps.get_model("events", "EventType")
    User = apps.get_model("users", "User")
    ChatMembership = apps.get_model("chat", "ChatMembership")
    ChatMessage = apps.get_model("chat", "ChatMessage")

    room, created = ChatRoom.objects.get_or_create(
        kind="rehearsals",
        defaults={"title": "Répétitions", "is_active": True},
    )
    if room.title != "Répétitions":
        room.title = "Répétitions"
        room.save(update_fields=["title"])
    if not room.is_active:
        room.is_active = True
        room.save(update_fields=["is_active"])

    if created or not ChatMembership.objects.filter(room=room).exists():
        staff_users = User.objects.filter(
            models.Q(is_staff=True) | models.Q(is_superuser=True),
            is_active=True,
        )
        musicians = User.objects.filter(is_musician=True, is_active=True)
        for user in list(staff_users) + list(musicians):
            ChatMembership.objects.get_or_create(
                room=room,
                user=user,
                defaults={"subscribed": True},
            )

    tip_prefix = "Proposez ici les morceaux à travailler"
    if not ChatMessage.objects.filter(
        room=room,
        kind="system",
        body__startswith=tip_prefix,
        deleted_at__isnull=True,
    ).exists():
        ChatMessage.objects.create(
            room=room,
            author=None,
            kind="system",
            body=(
                f"{tip_prefix}. "
                "Les autres votent avec 👍. "
                "Le staff compose ensuite la setlist."
            ),
        )

    rehearsal_type_ids = list(
        EventType.objects.filter(is_rehearsal=True).values_list("pk", flat=True)
    )
    # Fallback nom (types legacy).
    for et in EventType.objects.all():
        nom = (et.nom or "").strip().lower()
        if "répétition" in nom or "repetition" in nom:
            if et.pk not in rehearsal_type_ids:
                rehearsal_type_ids.append(et.pk)

    event_ids = list(
        Event.objects.filter(type_id__in=rehearsal_type_ids).values_list("pk", flat=True)
    )
    if event_ids:
        ChatRoom.objects.filter(
            kind="event",
            event_id__in=event_ids,
            is_active=True,
        ).update(is_active=False)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0013_soft_delete_poll_launch_messages"),
        ("events", "0014_organisme_url_site"),
        ("users", "0013_must_change_password"),
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
                    ("piece", "Morceau"),
                    ("staff", "Staff"),
                    ("section", "Pupitre"),
                ],
                db_index=True,
                max_length=20,
                verbose_name="Type",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatroom",
            constraint=models.UniqueConstraint(
                condition=models.Q(("kind", "rehearsals")),
                fields=("kind",),
                name="unique_rehearsals_chat_room",
            ),
        ),
        migrations.RunPython(create_rehearsals_room_and_deactivate_old, noop_reverse),
    ]
