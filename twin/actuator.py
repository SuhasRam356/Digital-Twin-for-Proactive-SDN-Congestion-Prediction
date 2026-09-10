import requests

class Actuator:
    def __init__(self, controller_url):
        self.controller_url = controller_url

    def push_reroute(self, src_mac, dst_mac, path, port_map):
        """
        Pushes OpenFlow rules to force traffic between src_mac and dst_mac 
        along the specified path (list of switch DPIDs).
        """
        print(f"[Actuator] Pushing route for {src_mac} -> {dst_mac} via {path}")
        
        for i in range(len(path)):
            current_dpid = path[i]
            
            # If it's the last switch, the out_port goes to the host.
            # (In a real system, we'd look up the host port, but simple_switch 
            # will handle delivery to the host once it reaches the edge switch,
            # or we can explicitly set it if we know the host port).
            # Actually, to be safe, we only need to reroute intermediate hops!
            # If we just push rules for path[:-1], simple_switch handles the final hop.
            if i < len(path) - 1:
                next_dpid = path[i+1]
                
                # Get the exact port connecting current_dpid to next_dpid
                out_port = port_map.get((current_dpid, next_dpid))
                if not out_port:
                    print(f"[Actuator] Error: No port found for {current_dpid} -> {next_dpid}")
                    continue
                
                # Rule: Match on dst_mac, output to out_port
                self._add_flow(current_dpid, dst_mac, out_port, priority=100)

        print("[Actuator] Reroute successfully installed.")

    def _add_flow(self, dpid, dst_mac, out_port, priority=100):
        url = f"{self.controller_url}/stats/flowentry/add"
        payload = {
            "dpid": int(dpid, 16) if isinstance(dpid, str) else dpid,
            "cookie": 1,
            "cookie_mask": 1,
            "table_id": 0,
            "idle_timeout": 60, # Remove rule after 60s of inactivity
            "hard_timeout": 0,
            "priority": priority,
            "flags": 1,
            "match": {
                "dl_dst": dst_mac
            },
            "actions": [
                {
                    "type": "OUTPUT",
                    "port": out_port
                }
            ]
        }
        try:
            r = requests.post(url, json=payload, timeout=2)
            if r.status_code != 200:
                print(f"[Actuator] Failed to push flow to {dpid}: {r.text}")
        except Exception as e:
            print(f"[Actuator] Error pushing flow: {e}")
