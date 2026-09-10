import time
import requests
import sqlite3
import json
from datetime import datetime

RYU_URL = 'http://127.0.0.1:8080'
POLL_INTERVAL = 5  # seconds

def init_db():
    conn = sqlite3.connect('telemetry.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS link_stats (
            timestamp DATETIME,
            src_dpid TEXT,
            src_port INTEGER,
            dst_dpid TEXT,
            dst_port INTEGER,
            tx_bytes INTEGER,
            rx_bytes INTEGER
        )
    ''')
    conn.commit()
    return conn

def get_topology_links():
    try:
        response = requests.get(f"{RYU_URL}/v1.0/topology/links")
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching topology: {e}")
    return []

def get_port_stats():
    try:
        response = requests.get(f"{RYU_URL}/stats/port/ALL")
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching port stats: {e}")
    return {}

def main():
    conn = init_db()
    c = conn.cursor()
    print(f"Starting Telemetry Collector. Polling every {POLL_INTERVAL} seconds...")

    # Dictionary to keep track of previous tx/rx values to compute rates if needed later
    # For Phase 1, we just log raw bytes.
    
    while True:
        links = get_topology_links()
        port_stats = get_port_stats()
        
        now = datetime.now()
        
        # We use the links to understand the topology, and port_stats to get traffic
        for link in links:
            src_dpid = str(link['src']['dpid'])
            src_port = int(link['src']['port_no'])
            dst_dpid = str(link['dst']['dpid'])
            dst_port = int(link['dst']['port_no'])
            
            # Find stats for src_port
            tx_bytes = 0
            rx_bytes = 0
            if src_dpid in port_stats:
                for port_stat in port_stats[src_dpid]:
                    if port_stat['port_no'] == src_port:
                        tx_bytes = port_stat['tx_bytes']
                        rx_bytes = port_stat['rx_bytes']
                        break
            
            c.execute('''
                INSERT INTO link_stats (timestamp, src_dpid, src_port, dst_dpid, dst_port, tx_bytes, rx_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (now, src_dpid, src_port, dst_dpid, dst_port, tx_bytes, rx_bytes))
            
            print(f"[{now}] Logged: Switch {src_dpid}:Port {src_port} -> Switch {dst_dpid}:Port {dst_port} | TX: {tx_bytes}, RX: {rx_bytes}")
            
        conn.commit()
        time.sleep(POLL_INTERVAL)

if __name__ == '__main__':
    main()
