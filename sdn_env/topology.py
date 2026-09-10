#!/usr/bin/env python3
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink

def create_topology():
    net = Mininet(controller=RemoteController, switch=OVSKernelSwitch, link=TCLink)

    info('*** Adding controller\n')
    # Use Ryu's default OpenFlow port
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)

    info('*** Adding switches\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow13')
    s2 = net.addSwitch('s2', protocols='OpenFlow13')
    s3 = net.addSwitch('s3', protocols='OpenFlow13')
    s4 = net.addSwitch('s4', protocols='OpenFlow13')
    s5 = net.addSwitch('s5', protocols='OpenFlow13')
    s6 = net.addSwitch('s6', protocols='OpenFlow13')

    info('*** Adding hosts (with static MACs)\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
    h4 = net.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

    info('*** Creating links\n')
    # Connect hosts to edge switches
    net.addLink(h1, s1, bw=100)
    net.addLink(h2, s2, bw=100)
    net.addLink(h3, s5, bw=100)
    net.addLink(h4, s6, bw=100)

    # Core topology (Redundant mesh restored!)
    # s1 - s3 - s5
    # |  X  |  X |
    # s2 - s4 - s6
    net.addLink(s1, s2, bw=100)
    net.addLink(s1, s3, bw=100)
    net.addLink(s1, s4, bw=100)
    
    net.addLink(s2, s4, bw=100)
    net.addLink(s2, s3, bw=100)
    
    net.addLink(s3, s4, bw=100)
    net.addLink(s3, s5, bw=100)
    net.addLink(s3, s6, bw=100)
    
    net.addLink(s4, s6, bw=100)
    net.addLink(s4, s5, bw=100)
    
    net.addLink(s5, s6, bw=100)

    info('*** Starting network\n')
    net.build()
    c0.start()
    net.start()
    
    info('*** Configuring Static ARP (preventing broadcast storms)\n')
    hosts = [h1, h2, h3, h4]
    for src in hosts:
        for dst in hosts:
            if src != dst:
                src.cmd("arp -s {} {}".format(dst.IP(), dst.MAC()))
                
    info('*** Configuring default PacketIn rules on switches\n')
    for sw in [s1, s2, s3, s4, s5, s6]:
        # Send unmatched traffic to the controller (so rest_topology can discover hosts)
        sw.cmd("ovs-ofctl add-flow {} priority=1,actions=CONTROLLER".format(sw.name))

    info('*** Sending dummy packets for host discovery\n')
    # This ensures Ryu learns where the hosts are immediately
    for h in hosts:
        h.cmd("ping -c 1 -W 1 10.0.0.254 > /dev/null 2>&1 &")

    info('*** Running CLI\n')
    CLI(net)

    info('*** Stopping network\n')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    create_topology()
