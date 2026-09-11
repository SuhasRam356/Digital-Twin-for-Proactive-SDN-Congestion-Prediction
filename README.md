# Digital Twin for Proactive SDN Congestion Prediction

![Digital Twin SDN Architecture](https://img.shields.io/badge/Architecture-Digital%20Twin-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![SDN](https://img.shields.io/badge/SDN-Ryu%20%7C%20Mininet-green)
![Flask](https://img.shields.io/badge/Dashboard-Flask-lightgrey)
![Status](https://img.shields.io/badge/Status-Active-success)

Welcome to the **Digital Twin for Proactive SDN Congestion Prediction** project. This repository contains the source code for a comprehensive software-defined network (SDN) system that employs the concept of a Digital Twin to monitor, predict, and proactively mitigate network congestion before it impacts end-user experience.

By combining real-time telemetry from a physical (or emulated) network, an Exponentially Weighted Moving Average (EWMA) traffic predictor, and a robust decision engine, this project aims to autonomously compute alternative routing paths and actuate them via a centralized Ryu SDN controller.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Architecture and System Flow](#architecture-and-system-flow)
4. [Detailed Component Breakdown](#detailed-component-breakdown)
    - [1. SDN Environment](#1-sdn-environment)
    - [2. Telemetry Collector](#2-telemetry-collector)
    - [3. Digital Twin Engine](#3-digital-twin-engine)
    - [4. Predictor Module](#4-predictor-module)
    - [5. Decision Engine](#5-decision-engine)
    - [6. Actuator](#6-actuator)
    - [7. Web Dashboard](#7-web-dashboard)
5. [Prerequisites](#prerequisites)
6. [Installation and Setup](#installation-and-setup)
7. [Running the Application](#running-the-application)
8. [Simulating Network Traffic](#simulating-network-traffic)
9. [Phase 5 Evaluation Results](#phase-5-evaluation-results)
10. [Configuration](#configuration)
11. [REST API Endpoints](#rest-api-endpoints)
12. [Project Directory Structure](#project-directory-structure)
13. [Algorithms and Methodologies](#algorithms-and-methodologies)
14. [Limitations and Known Issues](#limitations-and-known-issues)
15. [Future Enhancements Roadmap](#future-enhancements-roadmap)
16. [Contributing](#contributing)
17. [License](#license)
18. [Acknowledgements](#acknowledgements)

---

## Overview

Modern networks face unprecedented levels of traffic unpredictability, which often leads to temporary congestion, packet loss, and high latency. Reactive networking strategies (reacting *after* congestion occurs) are no longer sufficient for mission-critical applications. 

This project solves this by using a **Digital Twin**: a virtual, real-time software replica of the underlying SDN. 
The Digital Twin mirrors the state of the network switches, links, and hosts. By aggregating port statistics and link utilizations over time, the twin employs forecasting algorithms (like EWMA) to predict if a link will exceed a critical utilization threshold. If a potential congestion point is identified, the twin proactively simulates alternative paths, selects the most optimal route, and commands the SDN controller to apply new flow rules, thereby avoiding the congestion entirely.

---

## Key Features

- **Real-Time Network Mirroring**: Dynamically maps and synchronizes Mininet/OpenFlow network topologies into a NetworkX graph.
- **Proactive Congestion Prediction**: Utilizes an EWMA-based forecasting model to predict near-future traffic spikes on a per-link basis.
- **Intelligent Decision Engine**: Simulates "what-if" scenarios for heavy elephant flows, calculating k-shortest paths to bypass predicted bottlenecks.
- **IEEE 802.1Q (VLANs)**: Implements tenant isolation and routes traffic on the core exclusively via VLAN tags.
- **IEEE 802.1X (Network Access Control)**: Employs MAC Authentication Bypass (MAB) to identify and drop unauthorized traffic at the edge.
- **Telemetry Streaming**: Sub-second ZeroMQ (ZMQ) streams push telemetry from Ryu to the Digital Twin, bypassing the sluggish REST API.
- **Time-Series Database**: Natively exposes `sdn_link_utilization` gauges for **Prometheus**, allowing long-term historical retention and graphing.
- **High Availability**: Features an Active-Standby controller clustering setup orchestrated via **Apache ZooKeeper** for seamless failover.
- **Automated Actuation**: Communicates directly with the Ryu REST API to inject proactive OpenFlow routing rules (FlowMods).
- **Live Web Dashboard**: Features a responsive Flask-based web application to visualize the network graph, live link utilization, and recently triggered autonomous reroutes.

---

## Architecture and System Flow

The system is designed as a closed-loop control system:

1. **Sense (Telemetry)**: The Ryu controller periodically polls the OpenFlow switches for port statistics. The `Collector` module aggregates these stats.
2. **Sync (Digital Twin)**: The `DigitalTwin` module fetches the topology and stats from Ryu, updating its internal `networkx` graph representation.
3. **Predict (Predictor)**: For every link, the current utilization is fed into the EWMA predictor to forecast upcoming utilization levels.
4. **Decide (Decision Engine)**: If the predicted utilization exceeds a predefined threshold (e.g., 40%), the `DecisionEngine` is invoked to find the heavy flow and simulate alternative paths.
5. **Act (Actuator)**: Once a safe alternative path is found, the `Actuator` pushes the corresponding OpenFlow rules via Ryu to redirect the heavy flow.
6. **Visualize (Dashboard)**: All states, logs, and events are continuously served to the browser via a Flask backend.

---

## Detailed Component Breakdown

### 1. SDN Environment & VLANs
Located in `sdn_env/topology.py` and `sdn_env/init_routing.py`, this module utilizes Mininet to construct a redundant physical network. It uses OpenFlow 1.3 to push/pop VLANs at edge switches, enabling multi-tenant traffic isolation (IEEE 802.1Q) across the core.

### 2. Network Access Control (MAB)
Located in `sdn_env/nac_mab.py`. Simulates IEEE 802.1X via MAC Authentication Bypass. The Ryu app intercepts `PacketIn` events, checks the source MAC against an allowed list, and instantly drops unauthorized rogue devices.

### 3. Telemetry Streamer & Prometheus
Located in `sdn_env/telemetry_streamer.py`, this Ryu app requests stats sub-second and pushes them via a ZeroMQ (ZMQ) PUB socket. The Digital Twin subscribes to this socket, processing telemetry instantly and exposing Prometheus Gauges (`UTILIZATION_GAUGE`, `PREDICTED_UTIL_GAUGE`) on port 8000 for a Time-Series Database.

### 4. Digital Twin Engine
The heart of the project, located in `twin/digital_twin.py`. It:
- Subscribes to ZMQ telemetry streams.
- Reconstructs a NetworkX graph mirroring the SDN.
- Calculates link utilization as a percentage of link capacity.
- Evaluates EWMA predictions to check for future congestion states.
- Triggers the Decision Engine when limits are breached.
- Acts as a Prometheus metric exporter.

### 5. High Availability Manager
Located in `sdn_env/ha_manager.py`. Uses Apache ZooKeeper and the `kazoo` library to manage Active-Standby clustering. Multiple controllers can run, but only the elected Leader actually boots the Ryu process, enabling resilient failover.

### 6. Predictor & Decision Engine
Located in `twin/predictor.py` and `twin/decision_engine.py`. Leverages an **Exponentially Weighted Moving Average (EWMA)** model to predict congestion. The Decision Engine then identifies "Elephant Flows" and calculates `k` shortest alternative paths to bypass predicted bottlenecks.

### 7. Actuator & Web Dashboard
Located in `twin/actuator.py` and `dashboard/app.py`. The Actuator takes the path calculated by the Decision Engine and formats it into standard OpenFlow rules via REST. A Flask server runs the Digital Twin sync loop in a background daemon thread while simultaneously serving a web frontend for dynamic D3.js visualization.

---

## Prerequisites

To run this project, you must be in an environment capable of running Mininet (typically a Linux VM or WSL).

- **OS**: Ubuntu 20.04+ or WSL2.
- **Python**: Python 3.8 or higher.
- **Mininet**: `sudo apt-get install mininet`
- **ZooKeeper & Prometheus**: (Installed automatically via setup script)
- **Git**: To clone the repository.

---

## Installation and Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/SuhasRam356/Digital-Twin-for-Proactive-SDN-Congestion-Prediction.git
   cd Digital-Twin-for-Proactive-SDN-Congestion-Prediction
   ```

2. **Create a Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies & Infrastructure**
   ```bash
   pip install -r requirements.txt
   bash setup_infra.sh
   ```
   *Note: `setup_infra.sh` downloads Apache ZooKeeper and Prometheus binaries required for High Availability and Time-Series telemetry.*

---

## Running the Application

Running the full system requires opening multiple terminal windows to run the components simultaneously.

### Terminal 1: Infrastructure (ZooKeeper & Prometheus)
```bash
# Start ZooKeeper (background daemon)
./apache-zookeeper-3.9.2-bin/bin/zkServer.sh start

# Start Prometheus (foreground)
./prometheus-2.54.1.linux-amd64/prometheus --config.file=prometheus.yml
```
*(Prometheus UI available at http://localhost:9090)*

### Terminal 2: Start Mininet Topology
Start the highly redundant Mininet network. This requires `sudo` privileges.
```bash
sudo python3 sdn_env/topology.py
```

### Terminal 3: High Availability Ryu Controller
Run the HA Manager, which uses ZooKeeper leader election to start the Ryu Controller.
```bash
source ~/venv/bin/activate
bash start_controller.sh
```

### Terminal 4: Digital Twin & Web Dashboard
The Flask app will start the ZMQ telemetry subscriber and Prometheus exporter.
```bash
source ~/venv/bin/activate
python dashboard/app.py
```
*(Dashboard available at http://localhost:5000)*

### Terminal 5: Initialize Proactive Static Routing
Wait about 10 seconds for Ryu to discover all the links, then run the startup routing script. This script acts as a proactive SDN controller, computing shortest paths and pre-installing flow rules for all hosts with VLAN tagging.
```bash
source ~/venv/bin/activate
python sdn_env/init_routing.py
```

---

## Simulating Network Traffic

To test the proactive congestion prediction, you need to generate traffic within the Mininet network.

1. Go to the `mininet>` prompt in **Terminal 2**.
2. Run an `iperf` test between two hosts to simulate an elephant flow. For example, to generate a 50Mbps flow from `h1` to `h4`:
   ```bash
   mininet> h4 iperf -s &
   mininet> h1 iperf -c h4 -b 50M -t 60
   ```
3. Open your browser and navigate to the Dashboard (`http://localhost:5000`).
4. Watch the link utilization spike. As it approaches the EWMA prediction threshold (e.g., 40%), you will see the Twin automatically calculate a new route and the Actuator will push the flow rules to Ryu.
5. The traffic will automatically shift to the newly assigned, less congested path.

---

## Phase 5 Evaluation Results

The system was systematically evaluated by simulating heavy Elephant Flows and capturing the network state telemetry. 
We compared a reactive-only network (Baseline) with standard ECMP against our proactive Digital Twin network. 

### 1. EWMA Predictor Accuracy
The predictor attempts to forecast the near-future utilization of every link based on recent telemetry observations. Below is the EWMA predictor tracking a highly variable traffic burst on a core link. 
![EWMA Prediction Accuracy](evaluation_results/ewma_accuracy_baseline.png?v=2)
*(The prediction algorithm is able to successfully mirror sharp spikes and quickly decay once traffic ceases.)*

### 2. Proactive Congestion Avoidance
By predicting traffic surges, the Twin is able to simulate and inject rerouting rules *before* a physical bottleneck reaches 100% capacity. 
![Congestion Over Time](evaluation_results/congestion_over_time.png?v=2)
*(Notice how the Proactive Reroute (Green) intercepts the traffic spike at the 85% threshold, completely preventing the link from reaching the severe congestion sustained by the Baseline (Red).)*

### 3. Peak Utilization Comparison
The success metric of the system is the reduction of maximum stress on the network's busiest links.
![Peak Utilization](evaluation_results/peak_utilization.png?v=2)
*(The Digital Twin proactive interventions capped the max link utilization, avoiding packet drops and preserving quality of service).*

---

## Configuration

You can tweak the behavior of the Digital Twin by modifying parameters in the source code:

- **Polling Interval**: Defined in `dashboard/app.py` (`SYNC_INTERVAL = 2`). Lowering this increases responsiveness but adds overhead to the controller.
- **Congestion Threshold**: Defined in `twin/digital_twin.py` when initializing `DecisionEngine(threshold=40.0)`. You can increase or decrease this based on your network capacity.
- **EWMA Alpha Factor**: Defined in `twin/digital_twin.py` when initializing `EWMAPredictor(alpha=0.3)`. Higher values give more weight to recent spikes; lower values smooth out the prediction over a longer history.
- **Link Capacity**: Defined in `twin/digital_twin.py` (`link_capacity_mbps=100`). Adjust this to match your Mininet link capacities.

---

## REST API Endpoints

The Flask Dashboard exposes a JSON endpoint useful for third-party integrations:

- **`GET /api/state`**
  Returns the complete current state of the Digital Twin.
  **Response Snippet:**
  ```json
  {
    "is_connected": true,
    "last_sync": "2023-10-14T10:00:05.123",
    "num_hosts": 4,
    "num_links": 6,
    "num_switches": 6,
    "sync_count": 42,
    "nodes": [...],
    "edges": [...],
    "utilization_history": [...],
    "active_reroutes": [...]
  }
  ```

---

## Project Directory Structure

```text
Digital-Twin-for-Proactive-SDN-Congestion-Prediction/
├── dashboard/
│   ├── app.py                # Flask Web Server
│   └── templates/            # HTML/JS/CSS for the Dashboard
├── sdn_env/
│   ├── topology.py           # Mininet Python Script for topology
│   ├── traffic.sh            # Helper script for traffic generation
│   └── start_controller.sh   # Helper to start Ryu
├── telemetry/
│   ├── collector.py          # Standalone SQLite DB telemetry logger
│   └── telemetry.db          # Generated SQLite database file
├── twin/
│   ├── __init__.py
│   ├── actuator.py           # Converts decisions into Ryu REST calls
│   ├── decision_engine.py    # Simulates and selects alternate paths
│   ├── digital_twin.py       # Core Twin logic and Graph sync
│   └── predictor.py          # EWMA forecasting logic
├── requirements.txt          # Python pip dependencies
├── dataset.csv               # Generated CSV of live telemetry
└── README.md                 # This file
```

---

## Algorithms and Methodologies

### Exponentially Weighted Moving Average (EWMA)
To predict traffic at time $t+1$, the EWMA algorithm takes the actual observed traffic at time $t$ and the previously predicted traffic for time $t$.
Formula: `Forecast(t+1) = (Alpha * Actual(t)) + ((1 - Alpha) * Forecast(t))`
We use an alpha of `0.3`, which provides a balance between reactivity to sudden bursts and smoothing out micro-jitter.

### k-Shortest Paths (Yen's Algorithm)
The `DecisionEngine` uses NetworkX's `shortest_simple_paths` to compute loop-free alternative routes when a link is predicted to congest. We limit the search to the top $k=3$ paths to ensure low computational latency, allowing the twin to react in milliseconds.

---

## Limitations and Known Issues

1. **Ryu Controller Version Compatibility**: Ryu is currently best supported on Python 3.8/3.9. Running on Python 3.10+ may yield `eventlet` related async errors. Ensure you are using `eventlet==0.30.2`.
2. **Single Controller Bottleneck**: The current architecture assumes a single centralized Ryu controller. In a massive deployment, the controller could become a bottleneck for polling requests.
3. **Symmetric Routing Assumptions**: The Actuator pushes reverse rules for the alternate path to maintain symmetric routing (crucial for TCP). If the physical network has complex asymmetric policies, this could override them.

---

## Future Enhancements Roadmap

- [ ] **Machine Learning Integration**: Replace the simple EWMA model with a deep learning LSTM (Long Short-Term Memory) or GRU model for more accurate, long-horizon time-series forecasting.
- [ ] **Multi-Controller Support**: Scale the Digital Twin to support distributed ONOS or OpenDaylight controllers.
- [ ] **Containerization**: Provide a Docker Compose file to spin up the Dashboard, Twin, and Controller in isolated containers.
- [ ] **Advanced QoS**: Implement OpenFlow Queueing (QoS) rules to throttle low-priority traffic rather than just rerouting.

---

## Contributing

Contributions are heavily encouraged! If you'd like to improve the prediction models or the web dashboard:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details. You are free to use, modify, and distribute this software in both academic and commercial environments.

---

## Acknowledgements

- The [Mininet](http://mininet.org/) project for their incredible network emulation tool.
- The [Ryu SDN Framework](https://ryu-sdn.org/) for providing an accessible, Python-based OpenFlow controller.
- [NetworkX](https://networkx.org/) for making graph algorithms extremely straightforward in Python.
