import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from chat.services import (
    active_membership,
    ensure_staff_membership,
    post_message,
    user_can_access_room,
)
from chat.models import ChatRoom


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = int(self.scope["url_route"]["kwargs"]["room_id"])
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        room = await self._get_room()
        if room is None or not await self._can_access(room):
            await self.close()
            return

        self.room = room
        if self.user.is_staff or self.user.is_superuser:
            await self._ensure_staff_membership()
        self.group_name = room.channel_group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"type": "error", "error": "JSON invalide"}))
            return

        if payload.get("type") != "chat.message":
            return

        body = (payload.get("body") or "").strip()
        if not body:
            await self.send(
                text_data=json.dumps({"type": "error", "error": "Message vide"})
            )
            return

        membership = await self._active_membership()
        if membership is None and not (self.user.is_staff or self.user.is_superuser):
            await self.send(
                text_data=json.dumps({"type": "error", "error": "Accès refusé"})
            )
            return
        if membership is None and (self.user.is_staff or self.user.is_superuser):
            await self._ensure_staff_membership()

        try:
            message = await self._post(body)
        except ValueError as exc:
            await self.send(text_data=json.dumps({"type": "error", "error": str(exc)}))
            return

        # broadcast is done inside post_message; also echo is via group

    async def chat_message(self, event):
        await self.send(
            text_data=json.dumps({"type": "chat.message", "message": event["message"]})
        )

    @database_sync_to_async
    def _get_room(self):
        try:
            return ChatRoom.objects.get(pk=self.room_id, is_active=True)
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def _can_access(self, room):
        return user_can_access_room(self.user, room)

    @database_sync_to_async
    def _active_membership(self):
        return active_membership(self.room, self.user)

    @database_sync_to_async
    def _ensure_staff_membership(self):
        return ensure_staff_membership(self.room, self.user)

    @database_sync_to_async
    def _post(self, body: str):
        return post_message(room=self.room, author=self.user, body=body)
