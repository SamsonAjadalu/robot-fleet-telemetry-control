import asyncio
import json
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connection_manager import ConnectionManager
from redis_relay import RedisRelay


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.messages.append(message)


class FakePubSub:
    def __init__(self, bus):
        self.bus = bus
        self.queue = asyncio.Queue()
        self.channels = set()
        self.failure = None

    async def subscribe(self, channel):
        self.channels.add(channel)
        self.bus.channels[channel].add(self)

    async def unsubscribe(self, channel):
        self.channels.discard(channel)
        self.bus.channels[channel].discard(self)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        if self.failure is not None:
            raise self.failure
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def aclose(self):
        for channel in list(self.channels):
            await self.unsubscribe(channel)


class FakeRedis:
    def __init__(self, bus):
        self.bus = bus
        self.pubsub_instance = FakePubSub(bus)

    async def ping(self):
        return True

    def pubsub(self):
        return self.pubsub_instance

    async def publish(self, channel, message):
        for subscriber in list(self.bus.channels[channel]):
            await subscriber.queue.put({"type": "message", "data": message})
        return len(self.bus.channels[channel])

    async def aclose(self):
        return None


class FakeRedisBus:
    def __init__(self):
        self.channels = defaultdict(set)

    def factory(self):
        return lambda _url, decode_responses=True: FakeRedis(self)


class UnavailableRedis:
    async def ping(self):
        raise ConnectionError("Redis is unavailable")


def unavailable_factory(_url, decode_responses=True):
    return UnavailableRedis()


async def wait_for_messages(websocket, count):
    for _ in range(20):
        if len(websocket.messages) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"timed out waiting for {count} messages")


async def wait_until(predicate):
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("timed out waiting for condition")


class RedisWebSocketRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bus = FakeRedisBus()
        self.manager_a = ConnectionManager(
            relay=RedisRelay(
                redis_url="redis://fake",
                instance_id="api-a",
                redis_factory=bus.factory(),
            )
        )
        self.manager_b = ConnectionManager(
            relay=RedisRelay(
                redis_url="redis://fake",
                instance_id="api-b",
                redis_factory=bus.factory(),
            )
        )
        await self.manager_a.start()
        await self.manager_b.start()

    async def asyncTearDown(self):
        await self.manager_a.stop()
        await self.manager_b.stop()

    async def test_telemetry_from_robot_on_a_reaches_dashboard_on_b(self):
        frontend_a = FakeWebSocket()
        frontend_b = FakeWebSocket()
        await self.manager_a.connect_frontend(frontend_a)
        await self.manager_b.connect_frontend(frontend_b)

        telemetry = {
            "type": "telemetry",
            "robot_id": "tb3_01",
            "map_id": "map_01",
            "session_id": "session-a",
            "timestamp": "2026-10-12T00:00:00Z",
            "x": 1.0,
            "y": 2.0,
            "yaw": 0.2,
            "linear_x": 0.1,
            "angular_z": 0.0,
            "battery": 88.0,
        }

        await self.manager_a.send_to_frontend(telemetry)
        await wait_for_messages(frontend_b, 1)

        self.assertEqual(frontend_a.messages, [telemetry])
        self.assertEqual(frontend_b.messages, [telemetry])

    async def test_command_from_dashboard_on_b_reaches_robot_on_a(self):
        robot_a = FakeWebSocket()
        await self.manager_a.connect_robot(robot_a, "tb3_01")

        command = {
            "type": "command",
            "robot_id": "tb3_01",
            "linear_x_cmd": 0.25,
            "angular_z_cmd": -0.1,
        }

        await self.manager_b.send_to_robot("tb3_01", command)
        await wait_for_messages(robot_a, 1)

        self.assertEqual(robot_a.messages, [command])
        self.assertEqual(json.loads(json.dumps(robot_a.messages[0])), command)

    async def test_required_redis_unavailable_is_not_ready(self):
        relay = RedisRelay(
            redis_url="redis://unavailable",
            redis_required=True,
            redis_factory=unavailable_factory,
        )

        self.assertFalse(await relay.start(lambda _kind, _message: None))
        self.assertEqual(
            relay.readiness_status(),
            {
                "ready": False,
                "redis_required": True,
                "redis_connected": False,
                "mode": "redis-required",
            },
        )
        await relay.stop()

    async def test_required_redis_disconnect_is_not_ready_until_restored(self):
        bus = FakeRedisBus()
        relay = RedisRelay(
            redis_url="redis://fake",
            redis_required=True,
            redis_factory=bus.factory(),
        )

        self.assertTrue(await relay.start(lambda _kind, _message: None))
        self.assertTrue(relay.readiness_status()["ready"])

        relay._pubsub.failure = ConnectionError("Redis disconnected")
        await wait_until(lambda: not relay.connected)
        self.assertFalse(relay.readiness_status()["ready"])

        await relay.stop()
        self.assertTrue(await relay.start(lambda _kind, _message: None))
        self.assertTrue(relay.readiness_status()["ready"])
        await relay.stop()

    async def test_optional_redis_unavailable_keeps_single_instance_ready(self):
        manager = ConnectionManager(
            relay=RedisRelay(
                redis_url="redis://unavailable",
                redis_required=False,
                redis_factory=unavailable_factory,
            )
        )
        await manager.start()

        self.assertEqual(
            manager.readiness_status(),
            {
                "ready": True,
                "redis_required": False,
                "redis_connected": False,
                "mode": "single-instance",
            },
        )

        frontend = FakeWebSocket()
        await manager.connect_frontend(frontend)
        message = {"type": "telemetry", "robot_id": "tb3_01"}
        await manager.send_to_frontend(message)
        self.assertEqual(frontend.messages, [message])
        await manager.stop()
