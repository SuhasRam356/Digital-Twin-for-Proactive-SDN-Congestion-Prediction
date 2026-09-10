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
from datetime import datetime
from twin.predictor import EWMAPredictor
from twin.decision_engine import DecisionEngine
from twin.actuator import Actuator


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

        # For computing byte-rate between consecutive polls
        self._prev_stats = {}
        self._prev_time = None
        self.port_map = {}
        
        # Phase 4 components
        # In baseline mode (no rerouting), we set the threshold to >100% so it never triggers.
        if os.environ.get("TWIN_BASELINE_MODE") == "1":
            print("[Twin] BASELINE MODE ENABLED: Proactive rerouting is OFF.")
            self.decision_engine = DecisionEngine(threshold=101.0)
        else:
            self.decision_engine = DecisionEngine(threshold=40.0)
        self.actuator = Actuator(self.controller_url)
        self.active_reroutes = []

        # Rolling history for the dashboard chart (last 60 samples)
        self.utilization_history = []
        self.MAX_HISTORY = 60
        
        self.predictor = EWMAPredictor(alpha=0.3)
        
        # Initialize CSV logging
        self.csv_file = "dataset.csv"
        if not os.path.exists(self.csv_file):
            with open(self.csv_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "link_id", "src_port", "dst_port", "tx_rate_bytes", "utilization_pct"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self):
        """Pull fresh state from the controller and rebuild the graph."""
        try:
            switches = self._fetch("/v1.0/topology/switches") or []
            links = self._fetch("/v1.0/topology/links") or []
            hosts = self._fetch("/v1.0/topology/hosts") or []
            
            # Fetch port stats per switch instead of using 'ALL' to avoid Ryu ValueError
            port_stats = {}
            for sw in switches:
                dpid = sw.get("dpid")
                if dpid:
                    # int(dpid, 16) is needed because dpid is hex string e.g., "0000000000000001"
                    dpid_int = int(dpid, 16)
                    stats = self._fetch(f"/stats/port/{dpid_int}")
                    if stats and str(dpid_int) in stats:
                        port_stats[str(dpid_int)] = stats[str(dpid_int)]

            with self.lock:
                self._rebuild(switches,
                              links,
                              hosts,
                              port_stats)
                self.last_sync = datetime.now()
                self.sync_count += 1
                self.is_connected = True

        except requests.exceptions.ConnectionError:
            self.is_connected = False
        except Exception as exc:
            print(f"[Twin] sync error: {exc}")

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
        r = requests.get(f"{self.controller_url}{path}", timeout=3)
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

            # Compute byte-rate since last poll
            lk = f"{src_dpid}:{src_port}"
            tx_rate = rx_rate = 0.0
            if lk in self._prev_stats and self._prev_time:
                dt = now - self._prev_time
                if dt > 0:
                    p = self._prev_stats[lk]
                    tx_rate = max(0.0, (tx_bytes - p["tx"]) / dt)
                    rx_rate = max(0.0, (rx_bytes - p["rx"]) / dt)
            self._prev_stats[lk] = {"tx": tx_bytes, "rx": rx_bytes}

            # Utilization %  (capacity in bytes/s)
            cap = (self.link_capacity_mbps * 1_000_000) / 8
            util = (max(tx_rate, rx_rate) / cap * 100) if cap else 0
            util = round(min(util, 100.0), 2)

            # Predict future utilization using EWMA
            predicted_util = self.predictor.predict(lk, util)

            # Log to CSV
            with open(self.csv_file, mode='a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    f"{src_dpid}-{dst_dpid}",
                    src_port, dst_port,
                    round(tx_rate, 2),
                    util
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

        self._prev_time = now
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
        for u, v, data in self.graph.edges(data=True):
            if data.get("link_type") != "switch":
                continue
                
            pred_util = data.get("predicted_utilization", 0)
            if pred_util > self.decision_engine.threshold:
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
                
                dst_mac = heavy_flow["match"].get("dl_dst")
                if not dst_mac:
                    continue

                # 2. Trigger Decision Engine
                # Instead of end-to-end, we compute a path from the current switch (u) 
                # to the destination host, bypassing the congested link (u,v).
                print(f"[Twin] Identified heavy flow to {dst_mac}. Simulating alternatives...")
                
                # Mock a flow_data dict with just enough info for the decision engine
                flow_data = {
                    "src_mac": "switch_source", # Will start path from u
                    "dst_mac": dst_mac,
                    "tx_rate_bytes": data["tx_rate"]
                }
                
                # Slightly modify decision engine inputs to start from switch `u`
                best_path, sim_util = self._run_decision_engine(u, dst_mac, (u, v), flow_data)
                
                # 3. Actuate!
                if best_path:
                    self.actuator.push_reroute("any", dst_mac, best_path, self.port_map)
                    self.active_reroutes.insert(0, {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "congested_link": f"{u}-{v}",
                        "dst_mac": dst_mac,
                        "new_path": " -> ".join([str(self._dpid_to_int(p)) for p in best_path]),
                        "sim_util": sim_util
                    })
                    # Keep max 5 logs
                    self.active_reroutes = self.active_reroutes[:5]

    def _find_heavy_flow(self, dpid_int, out_port):
        """Polls /stats/flow/{dpid} to find the flow with highest bytes exiting out_port."""
        flow_stats = self._fetch(f"/stats/flow/{dpid_int}")
        if not flow_stats or str(dpid_int) not in flow_stats:
            return None
            
        flows = flow_stats[str(dpid_int)]
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
        """Wrapper for decision engine to start pathing from a specific switch instead of host."""
        u, v = congested_link
        dst_switch = self.decision_engine._find_attachment_switch(self.graph, dst_mac)
        
        if not dst_switch:
            return None, None
            
        temp_graph = self.graph.copy()
        if temp_graph.has_edge(u, v):
            temp_graph.remove_edge(u, v)

        try:
            candidates = list(nx.shortest_simple_paths(temp_graph, src_switch, dst_switch))[:3]
        except nx.NetworkXNoPath:
            return None, None

        best_path, best_max_util = None, float('inf')
        flow_rate_mbps = (flow_data['tx_rate_bytes'] * 8) / 1_000_000

        for path in candidates:
            max_util_in_sim = 0
            for i in range(len(path) - 1):
                n1, n2 = path[i], path[i+1]
                edge = self.graph[n1][n2]
                cap = edge.get('capacity_mbps', 100)
                cur = edge.get('predicted_utilization', edge.get('utilization', 0))
                sim = cur + (flow_rate_mbps / cap * 100)
                if sim > max_util_in_sim:
                    max_util_in_sim = sim
            if max_util_in_sim < best_max_util:
                best_max_util = max_util_in_sim
                best_path = path

        if best_path and best_max_util < self.decision_engine.threshold:
            print(f"[DecisionEngine] Selected path {best_path} with simulated max util {round(best_max_util,1)}%")
            return best_path, best_max_util
            
        return None, None
