#!/bin/bash
echo "Starting Ryu Controller (Core ZMQ Pipeline)..."
ryu-manager ryu.app.ofctl_rest ryu.app.rest_topology sdn_env/telemetry_streamer.py --observe-links
