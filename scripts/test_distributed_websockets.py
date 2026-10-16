"""Verify Redis delivery between separate API processes.

Start the local stack with: docker compose up -d --build
Install client dependency with: python3 -m pip install 'websockets>=12'
"""
import asyncio
import json
import websockets

ROBOT_URL = "ws://127.0.0.1:8001/ws/robot/tb3_001"
DASHBOARD_URL = "ws://127.0.0.1:8002/ws/frontend"


async def main():
    async with websockets.connect(ROBOT_URL) as robot:
        async with websockets.connect(DASHBOARD_URL) as dashboard:
            telemetry = {
                "type": "telemetry",
                "robot_id": "tb3_001",
                "map_id": "map_01",
                "session_id": "redis-test",
                "timestamp": "2026-01-01T00:00:00Z",
                "x": 1.5,
                "y": 2.0,
                "yaw": 0.0,
                "linear_x": 0.1,
                "angular_z": 0.0,
                "battery": 95.0,
            }
            await robot.send(json.dumps(telemetry))
            delivered = json.loads(await asyncio.wait_for(dashboard.recv(), 10))
            assert delivered["robot_id"] == "tb3_001" and delivered["x"] == 1.5
            print("Robot A -> Dashboard B: PASS")

            command = {
                "type": "command",
                "robot_id": "tb3_001",
                "linear_x_cmd": 0.2,
                "angular_z_cmd": 0.0,
            }
            await dashboard.send(json.dumps(command))
            delivered = json.loads(await asyncio.wait_for(robot.recv(), 10))
            assert delivered == command
            print("Dashboard B -> Robot A: PASS")


if __name__ == "__main__":
    asyncio.run(main())
