# scripts/audit_planning_views.py
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django
django.setup()
from django.urls import get_resolver

def list_urls_containing(needle: str):
    resolver = get_resolver()
    print(f"=== URL patterns contenant '{needle}' ===")
    for pattern in resolver.url_patterns:
        pattern_str = str(pattern.pattern)
        if needle in pattern_str:
            print(f"- {pattern_str} -> {getattr(pattern.callback, '__name__', pattern.callback)}")

if __name__ == "__main__":
    list_urls_containing("planning")
    list_urls_containing("calendar")
    list_urls_containing("concert")
