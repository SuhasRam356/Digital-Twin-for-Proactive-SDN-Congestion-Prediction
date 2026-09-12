import requests

class Actuator:
    def __init__(self, controller_url):
        self.controller_url = controller_url

    def push_reroute(self, src_mac, dst_mac, path, port_map, vlan_id=None):
        """
        Pushes OpenFlow rules to force traffic between src_mac and dst_mac 
        along the specified path (list of switch DPIDs).
        Installs both forward (src->dst) and reverse (dst->src) rules.
        """
        print(f"[Actuator] Pushing route for {src_mac} -> {dst_mac} via {path}")
        
        # Coerce vlan_id to a sanitized integer if present
        if vlan_id is not None:
            try:
                if isinstance(vlan_id, (list, tuple)):
                    vlan_id = vlan_id[0]
                vlan_id = int(str(vlan_id), 0)
                if vlan_id & 0x1000:
                    vlan_id = vlan_id & ~0x1000
            except (ValueError, TypeError):
                vlan_id = None

        # Forward Path (src_mac -> dst_mac)
        # Includes path[0] so the ingress switch installs the diverting rule
        for i in range(len(path) - 1):
            current_dpid = path[i]
            next_dpid = path[i+1]
            out_port = port_map.get((current_dpid, next_dpid))
            if out_port:
                if i == 0:
                    role = "ingress"
                elif i == len(path) - 2:
                    role = "egress"
                else:
                    role = "core"
                self._add_flow(current_dpid, src_mac, dst_mac, out_port, priority=100, vlan_id=vlan_id, role=role)
                
        # Reverse Path (dst_mac -> src_mac)
        if src_mac != "any":
            rev_path = path[::-1]
            for i in range(len(rev_path) - 1):
                current_dpid = rev_path[i]
                next_dpid = rev_path[i+1]
                out_port = port_map.get((current_dpid, next_dpid))
                if out_port:
                    if i == 0:
                        role = "ingress"
                    elif i == len(rev_path) - 2:
                        role = "egress"
                    else:
                        role = "core"
                    self._add_flow(current_dpid, dst_mac, src_mac, out_port, priority=100, vlan_id=vlan_id, role=role)

        print("[Actuator] Reroute successfully installed.")

    def _add_flow(self, dpid, src_mac, dst_mac, out_port, priority=100, vlan_id=None, role="core"):
        try:
            url = f"{self.controller_url}/stats/flowentry/add"
            match_dict = {"dl_dst": dst_mac}
            if src_mac != "any":
                match_dict["dl_src"] = src_mac
            
            # Ensure vlan_id is an integer if provided
            if vlan_id is not None:
                try:
                    if isinstance(vlan_id, (list, tuple)):
                        vlan_id = vlan_id[0]
                    vlan_id = int(str(vlan_id), 0)
                    if vlan_id & 0x1000:
                        vlan_id = vlan_id & ~0x1000
                except (ValueError, TypeError):
                    vlan_id = None

            actions = []

            if role == "ingress" and vlan_id is not None:
                actions = [
                    {"type": "PUSH_VLAN", "ethertype": 33024},
                    {"type": "SET_FIELD", "field": "vlan_vid", "value": 4096 + vlan_id},
                    {"type": "OUTPUT", "port": out_port}
                ]
            elif role == "egress" and vlan_id is not None:
                match_dict["dl_vlan"] = vlan_id
                actions = [
                    {"type": "POP_VLAN"},
                    {"type": "OUTPUT", "port": out_port}
                ]
            else:
                if vlan_id is not None:
                    match_dict["dl_vlan"] = vlan_id
                actions = [
                    {"type": "OUTPUT", "port": out_port}
                ]
                
            payload = {
                "dpid": int(dpid, 16) if isinstance(dpid, str) else dpid,
                "cookie": 1,
                "cookie_mask": 1,
                "table_id": 0,
                "idle_timeout": 30, # Drop idle rules after 30 seconds to save TCAM memory
                "hard_timeout": 0,
                "priority": priority,
                "flags": 1,
                "match": match_dict,
                "actions": actions
            }
            r = requests.post(url, json=payload, timeout=2)
            if r.status_code != 200:
                print(f"[Actuator] Failed to push flow to {dpid}: {r.text}")

            # If ingress with VLAN, also install a rule matching already-tagged packets
            # (e.g. if the rerouting switch is a core switch handling already-tagged traffic)
            if role == "ingress" and vlan_id is not None:
                tagged_match = dict(match_dict)
                tagged_match["dl_vlan"] = vlan_id
                tagged_payload = dict(payload)
                tagged_payload["match"] = tagged_match
                tagged_payload["priority"] = 101
                tagged_payload["actions"] = [{"type": "OUTPUT", "port": out_port}]
                requests.post(url, json=tagged_payload, timeout=2)

        except Exception as e:
            print(f"[Actuator] Error pushing flow: {e}")
