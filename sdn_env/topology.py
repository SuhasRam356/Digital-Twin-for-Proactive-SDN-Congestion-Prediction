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

    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    info('*** Creating links\n')
    # Connect hosts to edge switches
    net.addLink(h1, s1, bw=100)
    net.addLink(h2, s2, bw=100)
    net.addLink(h3, s5, bw=100)
    net.addLink(h4, s6, bw=100)

    # Core topology (loops removed to prevent broadcast storms)
    # s1 - s3 - s5
    # |
    # s2 - s4 - s6
    net.addLink(s1, s2, bw=100)
    net.addLink(s1, s3, bw=100)
    net.addLink(s2, s4, bw=100)
    net.addLink(s3, s5, bw=100)
    net.addLink(s4, s6, bw=100)


    info('*** Starting network\n')
    net.build()
    c0.start()
    net.start()

    info('*** Running CLI\n')
    CLI(net)

    info('*** Stopping network\n')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    create_topology()
