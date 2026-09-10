# traffic.sh - Mininet CLI script for generating varied traffic patterns
# Usage inside mininet> prompt: source sdn_env/traffic.sh

echo "*** Starting iperf3 servers on h3 and h4..."
h3 iperf3 -s -D
h4 iperf3 -s -D

echo "*** Generating Steady Traffic (h1 -> h4) at 20Mbps for 30s..."
h1 iperf3 -c 10.0.0.4 -t 30 -b 20M &

echo "*** Generating Bursty Traffic (h2 -> h3)..."
# Burst 1
h2 iperf3 -c 10.0.0.3 -t 5 -b 80M
# Pause
sh sleep 3
# Burst 2
h2 iperf3 -c 10.0.0.3 -t 5 -b 90M
# Pause
sh sleep 3
# Burst 3
h2 iperf3 -c 10.0.0.3 -t 5 -b 95M

echo "*** Generating Ramping Traffic (h1 -> h4)..."
h1 iperf3 -c 10.0.0.4 -t 5 -b 40M
h1 iperf3 -c 10.0.0.4 -t 5 -b 60M
h1 iperf3 -c 10.0.0.4 -t 5 -b 80M
h1 iperf3 -c 10.0.0.4 -t 10 -b 95M

echo "*** Traffic generation complete!"
