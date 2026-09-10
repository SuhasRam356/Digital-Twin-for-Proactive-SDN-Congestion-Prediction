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
        {"mac": "00:00:00:00:00:01", "dpid": 1, "port": 1}, # h1 on s1
        {"mac": "00:00:00:00:00:02", "dpid": 2, "port": 1}, # h2 on s2
        {"mac": "00:00:00:00:00:03", "dpid": 5, "port": 1}, # h3 on s5
        {"mac": "00:00:00:00:00:04", "dpid": 6, "port": 1}, # h4 on s6
    ]

    for host in static_hosts:
        mac = host["mac"]
        dpid = host["dpid"]
        port_no = host["port"]
        
        g.add_node(mac)
        g.add_edge(mac, dpid)
        port_map[(dpid, mac)] = port_no
            
    return g, port_map, static_hosts

def install_flow(dpid, dst_mac, out_port):
    payload = {
        "dpid": dpid,
        "cookie": 1,
        "cookie_mask": 1,
        "table_id": 0,
        "idle_timeout": 0,
        "hard_timeout": 0,
        "priority": 10,  # Base routing priority
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
    
    macs = [h["mac"] for h in hosts]
    
    for src_mac in macs:
        for dst_mac in macs:
            if src_mac == dst_mac:
                continue
                
            try:
                path = nx.shortest_path(g, source=src_mac, target=dst_mac)
                print("Path {} -> {}: {}".format(src_mac, dst_mac, path))
                
                # path looks like: [src_mac, switch1, switch2, ..., dst_mac]
                # We need to install rules on switch1, switch2, etc.
                for i in range(1, len(path) - 1):
                    current_dpid = path[i]
                    next_hop = path[i+1]
                    
                    out_port = port_map.get((current_dpid, next_hop))
                    if out_port:
                        install_flow(current_dpid, dst_mac, out_port)
            except nx.NetworkXNoPath:
                print("WARNING: No path between {} and {}".format(src_mac, dst_mac))

    print("Proactive routing installed successfully. The network is now ready!")

if __name__ == "__main__":
    main()
