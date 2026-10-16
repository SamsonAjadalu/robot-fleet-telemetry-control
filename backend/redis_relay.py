"""Redis Pub/Sub transport for cross-instance WebSocket events."""

import asyncio
import inspect
import json
import logging
import os
import uuid
from typing import Awaitable, Callable, Optional

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - exercised when Redis is not installed.
    Redis = None


logger = logging.getLogger(__name__)
RelayCallback = Callable[[str, dict], Awaitable[None]]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        await value


class RedisRelay:
    """Publish events once and deliver only events from other API instances."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        instance_id: Optional[str] = None,
        channel: Optional[str] = None,
        redis_factory=None,
        redis_required: Optional[bool] = None,
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL")
        self.redis_required = (
            self._parse_bool(os.getenv("REDIS_REQUIRED", "false"))
            if redis_required is None
            else redis_required
        )
        self.instance_id = (
            instance_id
            or os.getenv("RELAY_INSTANCE_ID")
            or uuid.uuid4().hex
        )
        self.channel = channel or os.getenv(
            "REDIS_CHANNEL", "robot-fleet:websocket"
        )
        self._redis_factory = redis_factory
        self._redis = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._stopping = False
        self._callback: Optional[RelayCallback] = None
        self._connected = False

    @staticmethod
    def _parse_bool(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @property
    def enabled(self) -> bool:
        return self._connected

    @property
    def connected(self) -> bool:
        """Whether the relay listener is currently connected and running."""
        return self._connected

    def readiness_status(self) -> dict:
        """Return readiness without conflating it with process liveness."""
        if not self.redis_required:
            return {
                "ready": True,
                "redis_required": False,
                "redis_connected": self.connected,
                "mode": "redis" if self.connected else "single-instance",
            }
        return {
            "ready": self.connected,
            "redis_required": True,
            "redis_connected": self.connected,
            "mode": "redis" if self.connected else "redis-required",
        }

    async def start(self, callback: RelayCallback) -> bool:
        """Connect and subscribe; leave the API local-only if Redis is unavailable."""
        self._callback = callback
        if not self.redis_url:
            return False
        if self.enabled:
            return True

        factory = self._redis_factory
        if factory is None:
            if Redis is None:
                logger.warning("REDIS_URL is set but redis is not installed")
                return False
            factory = Redis.from_url

        try:
            self._redis = factory(self.redis_url, decode_responses=True)
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self.channel)
            self._stopping = False
            self._connected = True
            self._listener_task = asyncio.create_task(self._listen())
            logger.info(
                "Redis WebSocket relay enabled on %s as %s",
                self.channel,
                self.instance_id,
            )
            return True
        except Exception as exc:
            if self.redis_required:
                logger.warning(
                    "Redis relay startup failed; readiness remains blocked: %s",
                    exc,
                )
            else:
                logger.warning(
                    "Redis relay startup failed; using local routing: %s",
                    exc,
                )
            await self.stop()
            return False

    async def stop(self):
        """Stop the listener and close Redis resources without leaking tasks."""
        self._stopping = True
        self._connected = False
        task = self._listener_task
        self._listener_task = None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        pubsub = self._pubsub
        self._pubsub = None
        if pubsub is not None:
            try:
                await _maybe_await(pubsub.unsubscribe(self.channel))
            except Exception:
                pass
            try:
                await _maybe_await(pubsub.aclose())
            except AttributeError:
                try:
                    await _maybe_await(pubsub.close())
                except Exception:
                    pass
            except Exception:
                pass

        redis = self._redis
        self._redis = None
        if redis is not None:
            try:
                await _maybe_await(redis.aclose())
            except AttributeError:
                try:
                    await _maybe_await(redis.close())
                except Exception:
                    pass
            except Exception:
                pass

    async def publish(self, kind: str, payload: dict) -> bool:
        """Publish an internal envelope while keeping the client payload unchanged."""
        if not self.enabled:
            return False

        envelope = {
            "source_id": self.instance_id,
            "kind": kind,
            "payload": payload,
        }
        try:
            await self._redis.publish(self.channel, json.dumps(envelope))
            return True
        except Exception as exc:
            self._connected = False
            logger.warning("Redis relay publish failed: %s", exc)
            return False

    async def _listen(self):
        while not self._stopping:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
            except asyncio.CancelledError:
                self._connected = False
                raise
            except Exception as exc:
                self._connected = False
                logger.warning("Redis relay listener stopped: %s", exc)
                return

            if not message or message.get("type") != "message":
                continue

            raw_data = message.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")
            try:
                envelope = json.loads(raw_data)
                source_id = envelope.get("source_id")
                kind = envelope["kind"]
                payload = envelope["payload"]
                if source_id == self.instance_id or not isinstance(payload, dict):
                    continue
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                logger.warning("Ignoring malformed Redis relay message")
                continue

            if self._callback is not None:
                try:
                    await self._callback(kind, payload)
                except Exception as exc:
                    logger.warning("Redis relay callback failed: %s", exc)
