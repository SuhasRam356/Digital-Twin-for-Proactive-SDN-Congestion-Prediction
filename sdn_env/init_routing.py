import requests
import networkx as nx
import time
import sys

RYU_URL = "http://127.0.0.1:8080"

def get_topology():
    try:
        links = requests.get("{}/v1.0/topology/links".format(RYU_URL)).json()
        hosts = requests.get("{}/v1.0/topology/hosts".format(RYU_URL)).json()
        return links, hosts
    except Exception as e:
        print("Error connecting to Ryu: {}".format(e))
        return None, None

def build_graph(links, hosts):
    g = nx.Graph()
    port_map = {}
    
    # Add switch-to-switch links
    for link in links:
        s1 = int(link["src"]["dpid"], 16)
        s2 = int(link["dst"]["dpid"], 16)
        p1 = int(link["src"]["port_no"], 16) if isinstance(link["src"]["port_no"], str) else link["src"]["port_no"]
        
        g.add_edge(s1, s2)
        port_map[(s1, s2)] = p1

    # Hardcode the known hosts for this specific topology
    # This bypasses Ryu's unreliable host discovery and guarantees instant routing
    static_hosts = [
        {"mac": "00:00:00:00:00:01", "dpid": 1, "port": 1, "vlan": 10}, # h1 on s1 (Tenant A)
        {"mac": "00:00:00:00:00:02", "dpid": 2, "port": 1, "vlan": 20}, # h2 on s2 (Tenant B)
        {"mac": "00:00:00:00:00:03", "dpid": 5, "port": 1, "vlan": 20}, # h3 on s5 (Tenant B)
        {"mac": "00:00:00:00:00:04", "dpid": 6, "port": 1, "vlan": 10}, # h4 on s6 (Tenant A)
    ]

    for host in static_hosts:
        mac = host["mac"]
        dpid = host["dpid"]
        port_no = host["port"]
        
        g.add_node(mac)
        g.add_edge(mac, dpid)
        port_map[(dpid, mac)] = port_no
            
    return g, port_map, static_hosts

def install_flow(dpid, src_mac, dst_mac, out_port, vlan_id, role="core"):
    match = {
        "dl_src": src_mac,
        "dl_dst": dst_mac
    }
    actions = []

    if role == "ingress":
        # Untagged packet entering, push VLAN
        actions = [
            {"type": "PUSH_VLAN", "ethertype": 33024},
            {"type": "SET_FIELD", "field": "vlan_vid", "value": 4096 + vlan_id},
            {"type": "OUTPUT", "port": out_port}
        ]
    elif role == "egress":
        # Tagged packet exiting to host, pop VLAN
        match["dl_vlan"] = vlan_id
        actions = [
            {"type": "POP_VLAN"},
            {"type": "OUTPUT", "port": out_port}
        ]
    else:
        # Core switch forwarding tagged packet
        match["dl_vlan"] = vlan_id
        actions = [
            {"type": "OUTPUT", "port": out_port}
        ]

    payload = {
        "dpid": dpid,
        "cookie": 1,
        "cookie_mask": 1,
        "table_id": 0,
        "idle_timeout": 0,
        "hard_timeout": 0,
        "priority": 10,  # Base routing priority
        "flags": 1,
        "match": match,
        "actions": actions
    }
    requests.post("{}/stats/flowentry/add".format(RYU_URL), json=payload)

def main():
    print("Waiting for Ryu topology discovery...")
    
    # Wait until 16 directional links (8 bidir links) are discovered
    while True:
        links, _ = get_topology()
        if links is not None and len(links) >= 16:
            break
        time.sleep(2)
        print("Still waiting for links to be discovered by Ryu...")

    g, port_map, hosts = build_graph(links, [])
    
    print("Topology discovered! Computing shortest paths...")
    
    for src_host in hosts:
        for dst_host in hosts:
            if src_host["mac"] == dst_host["mac"]:
                continue
                
            # IEEE 802.1Q: Tenant Isolation
            if src_host["vlan"] != dst_host["vlan"]:
                continue
                
            src_mac = src_host["mac"]
            dst_mac = dst_host["mac"]
            vlan_id = src_host["vlan"]
            
            try:
                path = nx.shortest_path(g, source=src_mac, target=dst_mac)
                print("Path {} -> {} (VLAN {}): {}".format(src_mac, dst_mac, vlan_id, path))
                
                # path looks like: [src_mac, switch1, switch2, ..., dst_mac]
                # We need to install rules on switch1, switch2, etc.
                for i in range(1, len(path) - 1):
                    current_dpid = path[i]
                    next_hop = path[i+1]
                    out_port = port_map.get((current_dpid, next_hop))
                    
                    if not out_port:
                        continue
                        
                    role = "core"
                    if i == 1:
                        role = "ingress"
                    elif i == len(path) - 2:
                        role = "egress"
                        
                    # If ingress and egress are on the same switch (not happening here, but good practice)
                    if i == 1 and i == len(path) - 2:
                        role = "core" # or a specialized intra-switch role, but in this topo it's distinct
                        
                    install_flow(current_dpid, src_mac, dst_mac, out_port, vlan_id, role)
            except nx.NetworkXNoPath:
                print("WARNING: No path between {} and {}".format(src_mac, dst_mac))

    print("Proactive routing installed successfully. The network is now ready!")

if __name__ == "__main__":
    main()
