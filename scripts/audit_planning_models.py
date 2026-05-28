# scripts/audit_planning_models.py
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django
django.setup()

from django.apps import apps

KEYWORDS = [
    "concert", "event", "planning", "calendar",
    "musician", "member", "participant", "availability",
    "slot", "attendance", "booking",
]

for model in sorted(apps.get_models(), key=lambda m: (m._meta.app_label, m.__name__)):
    haystack = f"{model._meta.app_label}.{model.__name__}".lower()
    if any(keyword in haystack for keyword in KEYWORDS):
        print(f"\n=== {model._meta.app_label}.{model.__name__} ===")
        for field in model._meta.get_fields():
            related = ""
            if getattr(field, "related_model", None):
                related = f" -> {field.related_model._meta.app_label}.{field.related_model.__name__}"
            print(f"- {field.name} ({field.__class__.__name__}){related}")
