import time
import requests
import os
from prometheus_client import start_http_server, Gauge

RYU_URL = os.environ.get('RYU_URL', 'http://127.0.0.1:8080')
POLL_INTERVAL = 5  # seconds

# Define Prometheus Gauges
TX_BYTES = Gauge('sdn_link_tx_bytes', 'Transmit bytes', ['src_dpid', 'src_port', 'dst_dpid', 'dst_port'])
RX_BYTES = Gauge('sdn_link_rx_bytes', 'Receive bytes', ['src_dpid', 'src_port', 'dst_dpid', 'dst_port'])

def get_topology_links():
    try:
        response = requests.get(f"{RYU_URL}/v1.0/topology/links", timeout=3)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching topology: {e}")
    return []

def get_port_stats():
    try:
        response = requests.get(f"{RYU_URL}/stats/port/ALL", timeout=3)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching port stats: {e}")
    return {}

def main():
    # Start Prometheus metrics server
    start_http_server(8000)
    print(f"Starting Telemetry Collector on port 8000. Polling every {POLL_INTERVAL} seconds...")

    while True:
        links = get_topology_links()
        port_stats = get_port_stats()
        
        for link in links:
            src_dpid = str(link['src']['dpid'])
            src_port = int(link['src']['port_no'])
            dst_dpid = str(link['dst']['dpid'])
            dst_port = int(link['dst']['port_no'])
            
            tx_bytes = 0
            rx_bytes = 0
            if src_dpid in port_stats:
                for port_stat in port_stats[src_dpid]:
                    if port_stat['port_no'] == src_port:
                        tx_bytes = port_stat['tx_bytes']
                        rx_bytes = port_stat['rx_bytes']
                        break
            
            # Update Prometheus metrics
            labels = [src_dpid, str(src_port), dst_dpid, str(dst_port)]
            TX_BYTES.labels(*labels).set(tx_bytes)
            RX_BYTES.labels(*labels).set(rx_bytes)
            
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()
