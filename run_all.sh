#!/bin/bash
echo "========================================================="
echo "   Digital Twin Proactive SDN - One-Click Environment    "
echo "========================================================="

# Clean up any previous Mininet instances to prevent errors
sudo mn -c 2>/dev/null

# Function to cleanup all background processes when script exits
cleanup() {
    echo -e "\n[Shutdown] Shutting down all services..."
    # Stop ZooKeeper
    if [ -f "./apache-zookeeper-3.9.2-bin/bin/zkServer.sh" ]; then
        ./apache-zookeeper-3.9.2-bin/bin/zkServer.sh stop
    fi
    # Kill all background processes spawned by this script
    pkill -P $$
    echo "[Shutdown] Cleaning up Mininet..."
    sudo mn -c 2>/dev/null
    echo "Goodbye!"
    exit 0
}

# Catch Ctrl+C and exit signals
trap cleanup SIGINT SIGTERM

# Activate python virtual environment
if [ -d "$HOME/venv" ]; then
    source ~/venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Warning: No venv found. Proceeding with default python."
fi

# 1. Start ZooKeeper (Runs as a background daemon by default)
if [ -f "./apache-zookeeper-3.9.2-bin/bin/zkServer.sh" ]; then
    echo "[1/5] Starting ZooKeeper..."
    ./apache-zookeeper-3.9.2-bin/bin/zkServer.sh start
else
    echo "ZooKeeper not found. Skipping HA/ZooKeeper setup."
fi

# 2. Start Prometheus (Run in background)
if [ -f "./prometheus-2.54.1.linux-amd64/prometheus" ]; then
    echo "[2/5] Starting Prometheus..."
    ./prometheus-2.54.1.linux-amd64/prometheus --config.file=prometheus.yml > prometheus.log 2>&1 &
else
    echo "Prometheus not found. Skipping."
fi

# 3. Start Ryu Controller (Run in background)
echo "[3/5] Starting Ryu Controller..."
# We use start_controller_advanced.sh for HA and VLAN support
bash start_controller_advanced.sh > ryu_controller.log 2>&1 &
sleep 2 # Give the controller a moment to bind ports

# 4. Start Digital Twin & Dashboard (Run in background)
echo "[4/5] Starting Digital Twin & Dashboard..."
python dashboard/app.py > dashboard.log 2>&1 &

# 5. Delayed Routing Initialization (Run in subshell background)
echo "[5/5] Scheduling Routing Initialization (will run in 12s)..."
(
    sleep 12
    echo -e "\n[Routing] Initializing static proactive routing..."
    python sdn_env/init_routing.py
    echo "[Routing] Flow rules installed. Network is ready!"
    echo -n "mininet> " # Reprint mininet prompt to keep UI clean
) &

# 6. Start Mininet Topology (Foreground)
echo ""
echo "========================================================="
echo " Starting Mininet! You can use the CLI below."
echo " To test congestion: h1 iperf -c h4 -b 50M -t 60"
echo " To exit: type 'exit' or press Ctrl+C"
echo "========================================================="
sudo python3 sdn_env/topology.py

# When user types 'exit' in mininet, the script reaches here and cleans up.
cleanup
