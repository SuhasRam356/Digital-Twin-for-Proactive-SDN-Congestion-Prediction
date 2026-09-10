import networkx as nx

class DecisionEngine:
    def __init__(self, trigger_threshold=40.0, safety_threshold=85.0):
        self.trigger_threshold = trigger_threshold    # when to start looking for a reroute
        self.safety_threshold = safety_threshold      # max util to accept a candidate as "safe enough"

    def decide_reroute(self, graph, congested_link, flow_data, port_map):
        """
        Calculates an alternative path for the heavy flow that avoids the congested link.
        Returns (best_path, simulated_max_util) or (None, None) if no valid path exists.
        
        flow_data: dict containing 'src_mac', 'dst_mac', 'tx_rate_bytes'
        """
        u, v = congested_link
        src_mac = flow_data['src_mac']
        dst_mac = flow_data['dst_mac']
        flow_rate_mbps = (flow_data['tx_rate_bytes'] * 8) / 1_000_000

        # 1. Find the attachment switches for src and dst
        src_switch = self._find_attachment_switch(graph, src_mac)
        dst_switch = self._find_attachment_switch(graph, dst_mac)
        
        if not src_switch or not dst_switch:
            print("[DecisionEngine] Could not find attachment switches for flow.")
            return None, None

        # 2. Generate candidate paths (k-shortest paths) avoiding the congested link
        temp_graph = graph.copy()
        if temp_graph.has_edge(u, v):
            temp_graph.remove_edge(u, v)

        try:
            # Get shortest paths using NetworkX
            candidates = list(nx.shortest_simple_paths(temp_graph, src_switch, dst_switch))
            # Limit to top 3 alternatives
            candidates = candidates[:3]
        except nx.NetworkXNoPath:
            print("[DecisionEngine] No alternative paths available.")
            return None, None

        # 3. Simulate ("what-if") each candidate
        best_path = None
        best_max_util = float('inf')

        for path in candidates:
            # Simulate removing the flow's bandwidth from the congested link
            # and adding it to all links in the new path.
            sim_graph = graph.copy()
            
            # (In a highly accurate simulator, we'd subtract from the old path, 
            # but for a PoC, just adding it to the new path and checking if it's safe is enough).
            max_util_in_sim = 0
            
            for i in range(len(path) - 1):
                n1, n2 = path[i], path[i+1]
                edge = sim_graph[n1][n2]
                
                capacity_mbps = edge.get('capacity_mbps', 100)
                current_util = edge.get('predicted_utilization', edge.get('utilization', 0))
                
                # Add flow volume
                sim_util = current_util + (flow_rate_mbps / capacity_mbps * 100)
                if sim_util > max_util_in_sim:
                    max_util_in_sim = sim_util
                    
            if max_util_in_sim < best_max_util:
                best_max_util = max_util_in_sim
                best_path = path

        # 4. Pick best
        if best_path and best_max_util < self.safety_threshold:
            print(f"[DecisionEngine] Selected path {best_path} with simulated max util {round(best_max_util,1)}%")
            return best_path, best_max_util
            
        print(f"[DecisionEngine] No candidate path is safe (all exceed {self.safety_threshold}% safety threshold).")
        return None, None

    def _find_attachment_switch(self, graph, mac):
        # The graph has host nodes like 'host_00:00...'. Their only neighbor is the switch.
        host_id = f"host_{mac}"
        if graph.has_node(host_id):
            neighbors = list(graph.neighbors(host_id))
            if neighbors:
                return neighbors[0] # Return the attached switch DPID
        return None
