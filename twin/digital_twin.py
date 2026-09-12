"""
digital_twin.py — The core Digital Twin engine.

Maintains a NetworkX graph that mirrors the real SDN network's topology
and link utilization in near real-time by polling the Ryu controller's
REST API.
"""

import time
import threading
import requests
import networkx as nx
import csv
import os
import zmq
import json
from prometheus_client import start_http_server, Gauge
from datetime import datetime
from twin.predictor import EWMAPredictor
from twin.decision_engine import DecisionEngine
from twin.actuator import Actuator

# Prometheus Gauges
PROMETHEUS_PORT = 8000
UTILIZATION_GAUGE = Gauge('sdn_link_utilization_percent', 'Current Link Utilization', ['src_dpid', 'dst_dpid'])
PREDICTED_UTIL_GAUGE = Gauge('sdn_link_predicted_utilization_percent', 'Predicted Link Utilization', ['src_dpid', 'dst_dpid'])


class DigitalTwin:
    """
    A software replica of the physical SDN network.

    The twin periodically syncs with the Ryu controller to:
      1. Discover switches and links (topology).
      2. Fetch per-port byte counters (telemetry).
      3. Compute per-link throughput and utilization.
    """

    def __init__(self, controller_url="http://127.0.0.1:8080",
                 link_capacity_mbps=100):
        self.controller_url = controller_url
        self.graph = nx.Graph()
        self.lock = threading.Lock()
        self.last_sync = None
        self.sync_count = 0
        self.link_capacity_mbps = link_capacity_mbps
        self.is_connected = False
        self.session = requests.Session()
        
        # Start Prometheus Metrics Server
        try:
            start_http_server(PROMETHEUS_PORT)
            print(f"[Twin] Prometheus metrics server started on port {PROMETHEUS_PORT}")
        except Exception as e:
            print(f"[Twin] Prometheus server failed to start: {e}")

        # ZeroMQ setup
        self.zmq_context = zmq.Context()
        self.zmq_socket = self.zmq_context.socket(zmq.SUB)
        self.zmq_socket.connect("tcp://127.0.0.1:5555")
        self.zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "telemetry ")

        # For computing byte-rate between consecutive polls
        self._prev_stats = {}
        self._prev_time = None
        self.port_map = {}
        self._flow_stats_cache = {}
        self.latest_port_stats = {}
        self.latest_flow_stats = {}
        self._prev_flow_stats = {}
        
        # Phase 4 components
        # In baseline mode (no rerouting), we set trigger_threshold to >100% so it never fires.
        if os.environ.get("TWIN_BASELINE_MODE") == "1":
            print("[Twin] BASELINE MODE ENABLED: Proactive rerouting is OFF.")
            self.decision_engine = DecisionEngine(trigger_threshold=101.0)
        else:
            self.decision_engine = DecisionEngine(trigger_threshold=40.0, safety_threshold=85.0)
        self.actuator = Actuator(self.controller_url)
        self.active_reroutes = []

        # Rolling history for the dashboard chart (last 60 samples)
        self.utilization_history = []
        self.MAX_HISTORY = 60
        
        self.predictor = EWMAPredictor(alpha=0.3)
        
        # Initialize CSV logging
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.csv_file = os.path.join(project_root, "dataset.csv")
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "link_id", "src_port", "dst_port", "tx_rate_bytes", "utilization_pct", "predicted_utilization"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_streaming(self):
        """Perform initial topology sync via REST, then start ZMQ listening."""
        try:
            self.switches = self._fetch("/v1.0/topology/switches") or []
            self.links = self._fetch("/v1.0/topology/links") or []
            self.hosts = self._fetch("/v1.0/topology/hosts") or []
            self.is_connected = True
            
            # Start background ZMQ loop
            t = threading.Thread(target=self._zmq_loop, daemon=True)
            t.start()
        except Exception as e:
            print(f"[Twin] Initial sync error: {e}")
            self.is_connected = False

    def _zmq_loop(self):
        print("[Twin] Listening for ZMQ telemetry streams...")
        while True:
            try:
                msg = self.zmq_socket.recv_string()
                topic, data_str = msg.split(" ", 1)
                data = json.loads(data_str)
                
                if data["type"] == "port_stats":
                    dpid = str(data["dpid"])
                    self.latest_port_stats[dpid] = data["stats"]
                    
                    with self.lock:
                        self._rebuild(self.switches, self.links, self.hosts, self.latest_port_stats)
                        self.last_sync = datetime.now()
                        self.sync_count += 1
                elif data["type"] == "flow_stats":
                    dpid = data["dpid"]
                    flows = data.get("flows", [])
                    now = time.time()
                    for f in flows:
                        match = f.get("match", {})
                        actions = f.get("actions", [])
                        b_count = f.get("byte_count", 0)
                        fk = f"{dpid}_{match.get('dl_src')}_{match.get('dl_dst')}_{match.get('dl_vlan')}_{str(actions)}"
                        if fk in self._prev_flow_stats:
                            prev = self._prev_flow_stats[fk]
                            dt = now - prev["time"]
                            delta = b_count - prev["bytes"]
                            if dt > 0 and delta >= 0:
                                rate = delta / dt
                            else:
                                rate = prev.get("last_rate", 0.0)
                            self._prev_flow_stats[fk] = {"bytes": b_count, "time": now, "last_rate": rate}
                        else:
                            rate = 0.0
                            self._prev_flow_stats[fk] = {"bytes": b_count, "time": now, "last_rate": rate}
                        f["tx_rate_bytes"] = rate

                    with self.lock:
                        self.latest_flow_stats[dpid] = flows
                        self.latest_flow_stats[str(dpid)] = flows
                        try:
                            self.latest_flow_stats[int(dpid)] = flows
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                print(f"[Twin] ZMQ loop error: {e}")

    def get_state(self):
        """Return the full twin state as a JSON-serialisable dict."""
        with self.lock:
            nodes = []
            for nid, data in self.graph.nodes(data=True):
                d = dict(data)
                d["id"] = nid
                nodes.append(d)

            edges = []
            for u, v, data in self.graph.edges(data=True):
                d = dict(data)
                d["source"] = u
                d["target"] = v
                edges.append(d)

            n_switches = sum(
                1 for _, d in self.graph.nodes(data=True)
                if d.get("node_type") == "switch"
            )
            n_hosts = sum(
                1 for _, d in self.graph.nodes(data=True)
                if d.get("node_type") == "host"
            )
            n_links = sum(
                1 for _, _, d in self.graph.edges(data=True)
                if d.get("link_type") == "switch"
            )

            return {
                "nodes": nodes,
                "edges": edges,
                "last_sync": (self.last_sync.isoformat()
                              if self.last_sync else None),
                "sync_count": self.sync_count,
                "is_connected": self.is_connected,
                "num_switches": n_switches,
                "num_hosts": n_hosts,
                "num_links": n_links,
                "utilization_history": list(self.utilization_history),
                "active_reroutes": self.active_reroutes
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fetch(self, path):
        """GET JSON from the Ryu REST API."""
        r = self.session.get(f"{self.controller_url}{path}", timeout=3)
        return r.json() if r.status_code == 200 else None

    @staticmethod
    def _parse_port_no(raw):
        """
        Ryu returns port_no as a hex-padded string ("00000002") from
        the topology API and as a plain int from the stats API.
        This helper normalises both into a Python int.
        """
        if isinstance(raw, int):
            return raw
        s = str(raw).strip()
        if len(s) >= 8 and all(c in "0123456789abcdefABCDEF" for c in s):
            return int(s, 16)
        return int(s)

    @staticmethod
    def _dpid_to_int(dpid_hex):
        return int(dpid_hex, 16)

    # ------------------------------------------------------------------
    # Graph rebuild
    # ------------------------------------------------------------------

    def _rebuild(self, switches, links, hosts, port_stats):
        now = time.time()
        g = nx.Graph()

        # ---- switches ----
        for sw in switches:
            dpid = sw["dpid"]
            g.add_node(dpid,
                       node_type="switch",
                       label=f"s{self._dpid_to_int(dpid)}")

        # ---- hosts ----
        for host in hosts:
            mac = host.get("mac", "??")
            ipv4_list = host.get("ipv4", [])
            ipv4 = ipv4_list[0] if ipv4_list else ""
            port = host.get("port", {})
            att_dpid = port.get("dpid", "")
            att_port = port.get("port_no", "")

            hid = f"host_{mac}"
            g.add_node(hid,
                       node_type="host",
                       label=ipv4 or mac,
                       mac=mac,
                       ipv4=ipv4)

            if att_dpid and att_dpid in g:
                g.add_edge(hid, att_dpid,
                           link_type="host",
                           utilization=0,
                           tx_rate=0, rx_rate=0,
                           tx_bytes=0, rx_bytes=0,
                           capacity_mbps=self.link_capacity_mbps)

        # ---- switch-to-switch links ----
        self.port_map.clear()
        
        for link in links:
            src_dpid = link["src"]["dpid"]
            dst_dpid = link["dst"]["dpid"]
            src_port = self._parse_port_no(link["src"]["port_no"])
            dst_port = self._parse_port_no(link["dst"]["port_no"])
            
            self.port_map[(src_dpid, dst_dpid)] = src_port

            # Look up byte counters (stats keys are *decimal* dpid strings)
            src_key = str(self._dpid_to_int(src_dpid))
            tx_bytes = rx_bytes = 0
            if src_key in port_stats:
                for ps in port_stats[src_key]:
                    if ps["port_no"] == src_port:
                        tx_bytes = ps.get("tx_bytes", 0)
                        rx_bytes = ps.get("rx_bytes", 0)
                        break

            # Compute byte-rate since last poll.
            # Key insight: ZMQ delivers per-switch replies, so each
            # _rebuild sees counter updates for only ONE switch.
            # We must track prev counters AND prev time *per link key*
            # and skip recomputation when counters haven't changed.
            lk = f"{src_dpid}:{src_port}"
            tx_rate = 0.0
            rx_rate = 0.0
            util = 0.0

            if lk in self._prev_stats:
                prev = self._prev_stats[lk]
                delta_tx = tx_bytes - prev["tx"]
                delta_rx = rx_bytes - prev["rx"]

                if delta_tx != 0 or delta_rx != 0:
                    # Counters actually changed → real update arrived
                    dt = now - prev["time"]
                    if dt > 0:
                        tx_rate = max(0.0, delta_tx / dt)
                        rx_rate = max(0.0, delta_rx / dt)
                    # Store updated counters and timestamp
                    self._prev_stats[lk] = {"tx": tx_bytes, "rx": rx_bytes, "time": now}
                else:
                    # Counters unchanged → stale rebuild, reuse last known rate
                    tx_rate = prev.get("last_tx_rate", 0.0)
                    rx_rate = prev.get("last_rx_rate", 0.0)
            else:
                # First observation for this link — seed it, rate stays 0
                self._prev_stats[lk] = {"tx": tx_bytes, "rx": rx_bytes, "time": now}

            # Cache the computed rates back for stale-rebuild reuse
            self._prev_stats[lk]["last_tx_rate"] = tx_rate
            self._prev_stats[lk]["last_rx_rate"] = rx_rate

            # Utilization %  (capacity in bytes/s)
            cap = (self.link_capacity_mbps * 1_000_000) / 8
            util = (max(tx_rate, rx_rate) / cap * 100) if cap else 0
            util = round(min(util, 100.0), 2)

            # Predict future utilization using EWMA
            predicted_util = self.predictor.predict(lk, util)

            # Update Prometheus metrics
            UTILIZATION_GAUGE.labels(src_dpid, dst_dpid).set(util)
            PREDICTED_UTIL_GAUGE.labels(src_dpid, dst_dpid).set(predicted_util)

            # Log to CSV
            with open(self.csv_file, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    f"{src_dpid}-{dst_dpid}",
                    src_port, dst_port,
                    round(tx_rate, 2),
                    util,
                    predicted_util
                ])

            if g.has_edge(src_dpid, dst_dpid):
                # Merge: keep the higher utilisation direction
                e = g[src_dpid][dst_dpid]
                if util > e["utilization"]:
                    e.update(utilization=util,
                             predicted_utilization=predicted_util,
                             tx_rate=round(tx_rate, 2),
                             rx_rate=round(rx_rate, 2),
                             tx_bytes=tx_bytes,
                             rx_bytes=rx_bytes,
                             src_port=src_port,
                             dst_port=dst_port)
            else:
                g.add_edge(src_dpid, dst_dpid,
                           link_type="switch",
                           src_port=src_port,
                           dst_port=dst_port,
                           tx_bytes=tx_bytes,
                           rx_bytes=rx_bytes,
                           tx_rate=round(tx_rate, 2),
                           rx_rate=round(rx_rate, 2),
                           utilization=util,
                           predicted_utilization=predicted_util,
                           capacity_mbps=self.link_capacity_mbps)

        self.graph = g

        # Phase 4: Proactive Rerouting Logic
        self._check_for_congestion()

        # Record avg utilisation for the history chart
        switch_edges = [d for _, _, d in g.edges(data=True)
                        if d.get("link_type") == "switch"]
        if switch_edges:
            avg = round(sum(e["utilization"] for e in switch_edges)
                        / len(switch_edges), 2)
            peak = round(max(e["utilization"] for e in switch_edges), 2)
        else:
            avg = peak = 0.0

        self.utilization_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "avg": avg,
            "peak": peak,
        })
        if len(self.utilization_history) > self.MAX_HISTORY:
            self.utilization_history.pop(0)

    # ------------------------------------------------------------------
    # Phase 4: Proactive Decision Logic
    # ------------------------------------------------------------------

    def _check_for_congestion(self):
        """
        Scans all links for predicted congestion (>85%).
        If found, tracks the heavy flow and triggers the decision engine.
        """
        self._flow_stats_cache.clear()
        for u, v, data in self.graph.edges(data=True):
            if data.get("link_type") != "switch":
                continue
                
            pred_util = data.get("predicted_utilization", 0)
            if pred_util > self.decision_engine.trigger_threshold:
                # To prevent spamming reroutes for the same link
                if any(r["congested_link"] == f"{u}-{v}" for r in self.active_reroutes):
                    continue

                print(f"[Twin] WARNING: Link {u}-{v} predicted to reach {pred_util}%!")
                
                # 1. Flow Tracking (Elephant Flow Detection)
                dpid_int = self._dpid_to_int(u)
                out_port = data["src_port"]
                heavy_flow = self._find_heavy_flow(dpid_int, out_port)
                
                if not heavy_flow:
                    continue
                
                match = heavy_flow.get("match", {})
                dst_mac = match.get("dl_dst") or match.get("eth_dst")
                if not dst_mac:
                    continue

                # 2. Trigger Decision Engine
                # Instead of end-to-end, we compute a path from the current switch (u) 
                # to the destination host, bypassing the congested link (u,v).
                
                # Mock a flow_data dict with just enough info for the decision engine
                # Get real source MAC if available, else default to "any"
                src_mac = match.get("dl_src") or match.get("eth_src") or "any"
                vlan_id = match.get("dl_vlan") or match.get("vlan_vid")
                if vlan_id is not None:
                    try:
                        if isinstance(vlan_id, (list, tuple)):
                            vlan_id = vlan_id[0]
                        vlan_id = int(str(vlan_id), 0)
                        if vlan_id & 0x1000:
                            vlan_id = vlan_id & ~0x1000
                    except (ValueError, TypeError):
                        vlan_id = None

                # Fallback to known static VLANs if not in match
                if vlan_id is None:
                    STATIC_VLANS = {
                        "00:00:00:00:00:01": 10,
                        "00:00:00:00:00:04": 10,
                        "00:00:00:00:00:02": 20,
                        "00:00:00:00:00:03": 20,
                    }
                    vlan_id = STATIC_VLANS.get(src_mac) or STATIC_VLANS.get(dst_mac)

                flow_id = f"{src_mac}_{dst_mac}_{vlan_id}_{match.get('in_port', 'any')}"

                # Flapping protection: Have we already rerouted this specific flow recently?
                if any(r["flow_id"] == flow_id for r in self.active_reroutes):
                    continue
                
                vlan_str = f" (VLAN {vlan_id})" if vlan_id is not None else ""
                print(f"[Twin] WARNING: Link {u}-{v} predicted to reach {pred_util:.1f}%. Triggering reroute for {src_mac}->{dst_mac}{vlan_str}...")
                
                flow_rate = heavy_flow.get("tx_rate_bytes", 0.0)
                if flow_rate <= 0:
                    port_flows = [fl for fl in self.latest_flow_stats.get(dpid_int, []) if f"OUTPUT:{out_port}" in fl.get("actions", [])]
                    port_bytes = sum(fl.get("byte_count", 0) for fl in port_flows)
                    if port_bytes > 0:
                        flow_rate = data.get("tx_rate", 0) * (heavy_flow.get("byte_count", 0) / port_bytes)
                    else:
                        flow_rate = data.get("tx_rate", 0)

                flow_data = {
                    "src_mac": src_mac,
                    "dst_mac": dst_mac,
                    "tx_rate_bytes": flow_rate
                }
                
                # 2. Trigger Decision Engine
                best_path, sim_util = self.decision_engine.decide_reroute(self.graph, (u, v), flow_data, src_switch=u)
                
                # 3. Actuate!
                if best_path:
                    self.actuator.push_reroute(src_mac, dst_mac, best_path, self.port_map, vlan_id=vlan_id)
                    
                    self.active_reroutes.insert(0, {
                        "flow_id": flow_id,
                        "congested_link": f"{u}-{v}",
                        "new_path": " -> ".join([str(p) for p in best_path]),
                        "timestamp": time.time(),
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "dst_mac": dst_mac
                    })
                    # Keep max 10 logs (preventing flapping across multiple flows)
                    self.active_reroutes = self.active_reroutes[:10]

    def _find_heavy_flow(self, dpid_int, out_port):
        """Finds the flow with highest bytes exiting out_port, preferring streamed ZMQ flow stats, falling back to REST."""
        flows = self.latest_flow_stats.get(dpid_int) or self.latest_flow_stats.get(str(dpid_int))
        if not flows:
            if dpid_int not in self._flow_stats_cache:
                flow_stats = self._fetch(f"/stats/flow/{dpid_int}")
                if flow_stats and str(dpid_int) in flow_stats:
                    self._flow_stats_cache[dpid_int] = flow_stats[str(dpid_int)]
                else:
                    self._flow_stats_cache[dpid_int] = []
            flows = self._flow_stats_cache[dpid_int]

        heavy_flow = None
        max_bytes = -1
        
        for f in flows:
            actions = f.get("actions", [])
            # Look for actions like "OUTPUT:2"
            if f"OUTPUT:{out_port}" in actions:
                b_count = f.get("byte_count", 0)
                if b_count > max_bytes:
                    max_bytes = b_count
                    heavy_flow = f
                    
        return heavy_flow

    def _run_decision_engine(self, src_switch, dst_mac, congested_link, flow_data):
        """Wrapper for decision engine delegating directly to DecisionEngine.decide_reroute."""
        return self.decision_engine.decide_reroute(self.graph, congested_link, flow_data, src_switch=src_switch)
