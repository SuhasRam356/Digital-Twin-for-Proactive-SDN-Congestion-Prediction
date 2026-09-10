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

    # Add host links
    for host in hosts:
        mac = host["mac"]
        port = host.get("port")
        if port:
            dpid = int(port["dpid"], 16)
            port_no = int(port["port_no"], 16) if isinstance(port["port_no"], str) else port["port_no"]
            
            g.add_node(mac)
            g.add_edge(mac, dpid)
            port_map[(dpid, mac)] = port_no
            
    return g, port_map

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
    
    # Wait until all 4 hosts and switches are discovered
    while True:
        links, hosts = get_topology()
        if links is not None and len(hosts) >= 4 and len(links) >= 16: # 8 bidir links
            break
        time.sleep(2)
        print("Still waiting for hosts to be discovered (did you run the ping dummy packets?)...")

    g, port_map = build_graph(links, hosts)
    
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
