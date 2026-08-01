"""Shim notify_users for tests that patch planning.services.notify_users."""

from users.notify import notify_users as notify_users

__all__ = ["notify_users"]
