"""Local WebSocket routing plus optional cross-instance Redis relay."""

import os
from typing import Dict, Optional

from redis_relay import RedisRelay


class ConnectionManager:
    def __init__(
        self,
        redis_url: Optional[str] = None,
        relay=None,
        redis_required: Optional[bool] = None,
    ):
        self.frontend_connections = set()
        self.active_robots: Dict[str, object] = {}
        self.relay = relay or RedisRelay(
            redis_url=redis_url or os.getenv("REDIS_URL"),
            redis_required=redis_required,
        )

    async def start(self):
        await self.relay.start(self._handle_relay_event)

    async def stop(self):
        await self.relay.stop()

    def readiness_status(self) -> dict:
        return self.relay.readiness_status()

    async def connect_frontend(self, ws):
        await ws.accept()
        self.frontend_connections.add(ws)
        print("🟢 Frontend connected!")

    async def connect_robot(self, ws, robot_id: str):
        await ws.accept()
        self.active_robots[robot_id] = ws
        print(f"🟢 Robot [{robot_id}] connected!")

    def disconnect_frontend(self, ws=None):
        if ws is None:
            self.frontend_connections.clear()
        else:
            self.frontend_connections.discard(ws)
        print("🔴 Frontend disconnected.")

    def disconnect_robot(self, robot_id: str, ws=None):
        if robot_id in self.active_robots:
            if ws is None or self.active_robots[robot_id] is ws:
                del self.active_robots[robot_id]
                print(f"🔴 Robot [{robot_id}] disconnected.")

    async def _send_to_frontend_local(self, message: dict):
        for ws in tuple(self.frontend_connections):
            try:
                await ws.send_json(message)
            except Exception as exc:
                self.frontend_connections.discard(ws)
                print(f"⚠️ Frontend send failed: {exc}")

    async def _send_to_robot_local(self, robot_id: str, message: dict):
        ws = self.active_robots.get(robot_id)
        if ws:
            try:
                await ws.send_json(message)
                print(
                    f"📥 [Routed to Robot {robot_id}] "
                    f"Message type: {message.get('type')}"
                )
            except Exception as exc:
                if self.active_robots.get(robot_id) is ws:
                    del self.active_robots[robot_id]
                print(f"⚠️ Robot [{robot_id}] send failed: {exc}")

    async def _handle_relay_event(self, kind: str, message: dict):
        if kind == "telemetry":
            await self._send_to_frontend_local(message)
        elif kind == "command":
            robot_id = message.get("robot_id")
            if robot_id:
                await self._send_to_robot_local(robot_id, message)

    async def send_to_frontend(self, message: dict):
        # Local delivery preserves single-instance behavior. The sender's
        # source_id is ignored by its own Redis subscriber, avoiding duplicates.
        await self._send_to_frontend_local(message)
        await self.relay.publish("telemetry", message)

    async def send_to_robot(self, robot_id: str, message: dict):
        # Publish even when this instance has no local robot; another API
        # instance may own the connection.
        await self._send_to_robot_local(robot_id, message)
        await self.relay.publish("command", message)
