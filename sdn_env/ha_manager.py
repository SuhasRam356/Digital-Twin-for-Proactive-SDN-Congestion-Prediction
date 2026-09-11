import sys
import os
import subprocess
import time
from kazoo.client import KazooClient
from kazoo.recipe.election import Election

# Configuration
ZK_HOSTS = os.environ.get("ZK_HOSTS", "127.0.0.1:2181")
CONTROLLER_CMD = [
    os.path.expanduser("~/venv/bin/ryu-manager"),
    "ryu.app.ofctl_rest",
    "ryu.app.rest_topology",
    "sdn_env/nac_mab.py",
    "sdn_env/telemetry_streamer.py",
    "--observe-links"
]

def leader_function():
    print("[HA Manager] I am the LEADER! Starting Ryu controller...")
    # Start Ryu as a subprocess
    process = subprocess.Popen(CONTROLLER_CMD)
    try:
        # Keep waiting for the process while maintaining ZK connection
        process.wait()
    except KeyboardInterrupt:
        print("[HA Manager] Shutting down...")
        process.terminate()
        process.wait()
    print("[HA Manager] Ryu controller stopped. Relinquishing leadership.")

def main():
    print(f"[HA Manager] Connecting to ZooKeeper at {ZK_HOSTS}...")
    zk = KazooClient(hosts=ZK_HOSTS)
    zk.start()

    # Participate in leader election
    election = Election(zk, "/ryu_controller_election")
    
    print("[HA Manager] Waiting to become leader...")
    while True:
        try:
            # This blocks until this instance becomes the leader
            election.run(leader_function)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[HA Manager] Election error: {e}")
            time.sleep(5)

    zk.stop()
    zk.close()

if __name__ == "__main__":
    main()
