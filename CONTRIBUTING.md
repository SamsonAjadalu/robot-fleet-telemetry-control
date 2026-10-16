# Contributing

Open an [issue](https://github.com/SamsonAjadalu/robot-fleet-telemetry-control/issues) to report a bug or propose a change. Include the expected behavior, the observed result, and steps to reproduce.

## Pull requests

Create a branch from `main` and submit a focused pull request to `main`. Describe the change and how you tested it. The GitHub Actions workflow checks the frontend build, AWS infrastructure synthesis, Redis relay tests, and local WebSocket routing.

For changes to the ROS 2 bridge, run:

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select robot_bridge --symlink-install
colcon test --packages-select robot_bridge
colcon test-result --verbose
```

Use local environment variables for credentials. The [robot setup guide](docs/robot-setup.md) documents the WebSocket message formats.

Contributions are covered by the [MIT License](LICENSE).
