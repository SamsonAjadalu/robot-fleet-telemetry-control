# Robot Setup

Build the ROS 2 bridge, launch TurtleBot3 in Gazebo, and connect the fleet to the FastAPI backend. The bridge also works with ROS 2 robots that publish odometry and accept velocity commands.

**Backend setup:** [Run locally](deployment/local.md) or [deploy to AWS](deployment/aws.md). Start the API before connecting the robot fleet.

## Requirements

- Ubuntu 22.04, ROS 2 Humble, and Gazebo Classic
- TurtleBot3 packages, Nav2, and colcon
- Python WebSocket dependency from `telemetry_requirement.txt`

```bash
sudo apt update
sudo apt install ros-humble-turtlebot3* ros-humble-navigation2 ros-humble-nav2-bringup python3-colcon-common-extensions
```

## 1. Build the ROS 2 bridge

```bash
git clone https://github.com/SamsonAjadalu/robot-fleet-telemetry-control.git
cd robot-fleet-telemetry-control

cp .env.robot.example .env.robot
export WS_ROOT="$PWD"
source /opt/ros/humble/setup.bash
python3 -m pip install -r telemetry_requirement.txt
colcon build --packages-select robot_bridge --symlink-install
source "$WS_ROOT/install/setup.bash"
```

## 2. Launch the Gazebo fleet

The integrated launch starts Gazebo, spawns the robots and their WebSocket bridges, and brings up Nav2.

Connect to an API deployed with TLS:

```bash
ros2 launch robot_bridge stack_sim_nav2.launch.py \
  count:=3 backend_url:=wss://YOUR_API_HOST
```

Or connect to a backend on the same machine:

```bash
ros2 launch robot_bridge stack_sim_nav2.launch.py \
  count:=3 backend_url:=ws://localhost:8000
```

Robot IDs follow `tb3_001`, `tb3_002`, etc. The `count` launch argument defaults to `3`; it is shared with the fleet orchestrator and Nav2.

Optional launch arguments:

| Argument | Example |
| --- | --- |
| `count` | `count:=5` |
| `headless` | `headless:=true` (no Gazebo GUI) |
| `use_rviz` | `use_rviz:=true` |
| `backend_url` | `backend_url:=wss://YOUR_API_HOST` |

To restart a simulation session after shutting it down:

```bash
bash scripts/kill_fleet_sim.sh
```

## 3. Check robot connectivity

```bash
ros2 topic list
ros2 topic echo /tb3_001/odom
```

Open the fleet dashboard. Connected robots appear with their live position, velocity, and battery telemetry. Velocity commands from the dashboard reach the selected robot's namespaced `/cmd_vel` topic. Navigation goals reach its `/goal_pose` topic.

The bridge and dashboard connect through these API WebSocket routes:

| Client | Route |
| --- | --- |
| Robot bridge | `/ws/robot/{robot_id}` |
| Dashboard | `/ws/frontend` |

## Run a bridge without the fleet launcher

The `telemetry_bridge` can connect an existing ROS 2 robot to the same backend. Start a separate bridge process for each robot with its own `ROBOT_ID` and topic names.

```bash
ROBOT_ID=robot_01 \
MAP_ID=map_01 \
ODOM_TOPIC=/odom \
CMD_VEL_TOPIC=/cmd_vel \
BACKEND_BASE_URL=wss://YOUR_API_HOST \
ros2 run robot_bridge telemetry_bridge
```

The bridge subscribes to `nav_msgs/msg/Odometry`, publishes `geometry_msgs/msg/Twist` to `/cmd_vel`, and publishes `geometry_msgs/msg/PoseStamped` navigation goals. The default goal topic is derived from the command topic, for example `/tb3_001/cmd_vel` maps to `/tb3_001/goal_pose`.

### Bridge configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ROBOT_ID` | `tb3_001` | Robot identity and WebSocket route |
| `MAP_ID` | `map_01` | Map identifier included with telemetry |
| `BACKEND_BASE_URL` | `ws://localhost:8000` | API WebSocket base URL |
| `BACKEND_WS_URL` | Derived from base URL and robot ID | Full WebSocket URL override |
| `ODOM_TOPIC` | `/odom` | Odometry input |
| `CMD_VEL_TOPIC` | `/cmd_vel` | Velocity command output |
| `GOAL_POSE_TOPIC` | Derived from `CMD_VEL_TOPIC` | Nav2 goal output |
| `GOAL_FRAME_ID` | `map` | Goal pose frame |
| `USE_SIM_TIME` | Disabled | ROS simulated clock |

`stack_sim_nav2.launch.py` reads `BACKEND_BASE_URL` from the shell or the local `.env.robot` file. Copy `.env.robot.example` to `.env.robot` and edit the URL for your API. The `backend_url` launch argument overrides that default.

## WebSocket messages

Robot telemetry sent to the API:

```json
{
  "type": "telemetry",
  "robot_id": "tb3_001",
  "map_id": "map_01",
  "session_id": "session_tb3_001_20260307",
  "timestamp": "2026-03-07T16:20:00Z",
  "x": 1.24,
  "y": 2.81,
  "yaw": 0.52,
  "linear_x": 0.12,
  "angular_z": 0.03,
  "battery": 98.5
}
```

Velocity command sent from the dashboard to a robot:

```json
{
  "type": "command",
  "robot_id": "tb3_001",
  "linear_x_cmd": 0.2,
  "angular_z_cmd": 0.0
}
```

Navigation goal:

```json
{
  "type": "goal",
  "robot_id": "tb3_001",
  "x": 4.2,
  "y": 1.8,
  "yaw": 0.0
}
```

Robot position and velocity come from odometry. The simulation bridge generates a battery level for dashboard telemetry.

## Fleet orchestrator

`fleet_orchestrator` manages Gazebo worlds, robot spawning, and per-robot bridge processes. It fills available slots in existing worlds, creates additional worlds as needed, and tracks robot IDs and world assignments in a JSON state file.

Robots are assigned names such as `tb3_001` and `tb3_002`, with ROS topics including `/tb3_001/odom` and `/tb3_001/cmd_vel`. Each robot's bridge connects to `/ws/robot/{robot_id}`.

### Run the orchestrator separately

```bash
ros2 launch robot_bridge fleet_orchestrator.launch.py count:=5
```

Here `count` specifies how many **new** robots the orchestrator adds. Run it again to add another batch. Its default state file tracks existing worlds and robots.

Advanced options:

```bash
ros2 run robot_bridge fleet_orchestrator \
  --count 5 \
  --headless true \
  --state-file /tmp/fleet_state.json \
  --backend-url ws://localhost:8000 \
  --robots-per-world 10 \
  --dry-run false
```

The state file records the next world and robot indices, available capacity, and robot assignments. For example:

```json
{
  "next_world_index": 2,
  "next_robot_index": 6,
  "worlds": [
    {
      "world_id": "map_01",
      "world_name": "sim_world_01",
      "capacity": 20,
      "headless": true,
      "robots": ["tb3_001", "tb3_002", "tb3_003", "tb3_004", "tb3_005"]
    }
  ]
}
```

Logs are written to `.fleet_logs/` alongside the state file, including `world_map_01.log`, `spawn_tb3_001.log`, and `bridge_tb3_001.log`.

Orchestrator command overrides:

| Variable | Purpose |
| --- | --- |
| `WORLD_CMD_TEMPLATE` | Gazebo world launch command |
| `SPAWN_ROBOT_CMD_TEMPLATE` | Robot spawn command |
| `BRIDGE_CMD_TEMPLATE` | Per-robot bridge command |
| `TURTLEBOT3_MODEL` | TurtleBot3 model, default `burger` |

## Map assets

The bridge includes `MAP_ID` in telemetry. The dashboard loads `/maps/{map_id}/{map_id}.png` and `/maps/{map_id}/{map_id}.yaml` from the frontend origin. Use the same map ID for the file directory and the robot bridge. Map hosting is covered in the [local setup](deployment/local.md) and [AWS deployment](deployment/aws.md) guides.
