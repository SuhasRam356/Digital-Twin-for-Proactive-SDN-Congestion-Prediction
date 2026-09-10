"""
app.py — Flask web server for the Digital Twin dashboard.

Runs the twin sync loop in a background thread and serves:
  GET /           → the single-page dashboard UI
  GET /api/state  → JSON snapshot of the twin's current state
"""

import sys
import os
import threading
import time

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify
from twin.digital_twin import DigitalTwin

# --------------- configuration ---------------
SYNC_INTERVAL = 2        # seconds between twin syncs
DASHBOARD_PORT = 5000
RYU_URL = "http://127.0.0.1:8080"

# --------------- app setup ---------------
app = Flask(__name__)
twin = DigitalTwin(controller_url=RYU_URL)


def sync_loop():
    """Background thread that keeps the twin in sync."""
    print(f"[Dashboard] Twin sync loop started (every {SYNC_INTERVAL}s)")
    while True:
        twin.sync()
        time.sleep(SYNC_INTERVAL)


# --------------- routes ---------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(twin.get_state())


# --------------- entry point ---------------

if __name__ == "__main__":
    t = threading.Thread(target=sync_loop, daemon=True)
    t.start()
    print(f"[Dashboard] Serving on http://0.0.0.0:{DASHBOARD_PORT}")
    print(f"[Dashboard] Open http://localhost:{DASHBOARD_PORT} in your browser")
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
