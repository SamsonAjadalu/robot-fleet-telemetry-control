# Local Setup

Run Robot Fleet Telemetry & Control with PostgreSQL, Redis, two FastAPI instances, an Nginx API gateway, and the React dashboard.

## Requirements

- Docker with Docker Compose

## Start the stack

```bash
git clone https://github.com/SamsonAjadalu/robot-fleet-telemetry-control.git
cd robot-fleet-telemetry-control
docker compose up -d --build
```

Open the dashboard at **http://localhost:3000**. The API gateway listens at **http://localhost:8000** and distributes requests across both API instances.

```bash
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

The two API instances are also available on ports `8001` and `8002` for direct testing.

## Verify distributed WebSocket routing

Run the integration test, which connects a robot to API A and a dashboard to API B. It checks telemetry delivery and the return command.

```bash
python3 -m pip install "websockets>=12"
python3 scripts/test_distributed_websockets.py
```

## Connect ROS 2 robots

Follow the [ROS 2 robot setup](../robot-setup.md), connecting to `ws://localhost:8000`.

## Map assets

The repository includes a sample map at `frontend/public/maps/map_01/`. Replace its PNG and YAML with maps exported for your robot environment. For additional maps, use the same layout:

```text
frontend/public/maps/map_02/
├── map_02.png
└── map_02.yaml
```

The dashboard requests `/maps/{map_id}/{map_id}.png` and `.yaml`. Set the robot bridge's `MAP_ID` to the corresponding directory name. Rebuild the frontend after changing files for the Docker setup:

```bash
docker compose up -d --build frontend
```

For frontend development, `npm --prefix frontend ci` followed by `npm --prefix frontend run dev` serves the map directory through Vite.

## Stop

```bash
docker compose down
```

PostgreSQL data remains in the `postgres_data` Docker volume.
