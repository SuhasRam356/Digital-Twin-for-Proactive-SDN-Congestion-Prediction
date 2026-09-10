#!/bin/bash
echo "Starting Ryu Controller (REST API only, no learning switch)..."
~/venv/bin/ryu-manager ryu.app.ofctl_rest ryu.app.rest_topology --observe-links
