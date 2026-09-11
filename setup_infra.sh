#!/bin/bash
echo "=========================================================="
echo "Infrastructure Setup (No Docker)"
echo "=========================================================="

# 1. Install Java (Required for ZooKeeper)
echo "Checking for Java (required by ZooKeeper)..."
if ! command -v java &> /dev/null; then
    echo "Java not found. Installing default-jre..."
    sudo apt update && sudo apt install -y default-jre
else
    echo "Java is already installed."
fi

# 2. Download ZooKeeper
ZK_VERSION="3.9.2"
echo "Downloading Apache ZooKeeper v${ZK_VERSION}..."
if [ ! -d "apache-zookeeper-${ZK_VERSION}-bin" ]; then
    wget -qO- "https://dlcdn.apache.org/zookeeper/zookeeper-${ZK_VERSION}/apache-zookeeper-${ZK_VERSION}-bin.tar.gz" | tar xz
    # Setup basic config
    cp apache-zookeeper-${ZK_VERSION}-bin/conf/zoo_sample.cfg apache-zookeeper-${ZK_VERSION}-bin/conf/zoo.cfg
    echo "ZooKeeper downloaded and configured."
else
    echo "ZooKeeper already exists."
fi

# 3. Download Prometheus
PROM_VERSION="2.54.1"
echo "Downloading Prometheus v${PROM_VERSION}..."
if [ ! -d "prometheus-${PROM_VERSION}.linux-amd64" ]; then
    wget -qO- "https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-amd64.tar.gz" | tar xz
    echo "Prometheus downloaded."
else
    echo "Prometheus already exists."
fi

echo "=========================================================="
echo "Infrastructure Setup Complete!"
echo "To start ZooKeeper: ./apache-zookeeper-${ZK_VERSION}-bin/bin/zkServer.sh start"
echo "To start Prometheus: ./prometheus-${PROM_VERSION}.linux-amd64/prometheus --config.file=prometheus.yml"
echo "=========================================================="
