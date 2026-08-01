# Resync product tour steps after Coulisses/Chat IA change.

from django.db import migrations


def resync_tours(apps, schema_editor):
    ProductTour = apps.get_model("users", "ProductTour")
    ProductTourStep = apps.get_model("users", "ProductTourStep")

    from users.tour_defaults import MUSICIAN_STEPS, STAFF_STEPS

    specs = [
        ("musician", "Guide musicien", MUSICIAN_STEPS),
        ("staff", "Guide staff", STAFF_STEPS),
    ]
    for audience, title, steps in specs:
        tour, _ = ProductTour.objects.get_or_create(
            audience=audience,
            defaults={"title": title, "version": 2, "is_active": True},
        )
        tour.title = title
        tour.version = int(tour.version or 1) + 1
        tour.is_active = True
        tour.save(update_fields=["title", "version", "is_active"])
        tour.steps.all().delete()
        ProductTourStep.objects.bulk_create(
            [
                ProductTourStep(
                    tour=tour,
                    order=s["order"],
                    anchor=s.get("anchor") or "",
                    title=s["title"],
                    body=s["body"],
                    page_path=s.get("page_path") or "",
                    open_mobile_nav=bool(s.get("open_mobile_nav")),
                    scroll_footer=bool(s.get("scroll_footer")),
                    is_active=True,
                )
                for s in steps
            ]
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_notification_response_status"),
    ]

    operations = [
        migrations.RunPython(resync_tours, noop_reverse),
    ]
