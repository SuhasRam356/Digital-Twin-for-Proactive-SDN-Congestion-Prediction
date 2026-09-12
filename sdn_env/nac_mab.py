from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet

class NAC_MAB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(NAC_MAB, self).__init__(*args, **kwargs)
        # Controller-based MAC Authentication Bypass (MAB)
        # Only allow known, authenticated host MAC addresses.
        self.ALLOWED_MACS = {
            "00:00:00:00:00:01", # h1
            "00:00:00:00:00:02", # h2
            "00:00:00:00:00:03", # h3
            "00:00:00:00:00:04"  # h4
        }
        self.logger.info("NAC MAB (802.1X simulation) started.")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        
        # Ignore LLDP (Topology discovery packets)
        if eth.ethertype == 35020:
            return

        src_mac = eth.src
        
        # MAC Authentication Bypass Check
        if src_mac not in self.ALLOWED_MACS:
            self.logger.warning(f"[NAC] Unauthorized host detected! Dropping traffic from MAC: {src_mac}")
            
            # Install a high priority drop rule for this unauthorized MAC
            match = parser.OFPMatch(eth_src=src_mac)
            actions = [] # Empty actions = DROP
            
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            
            # Priority 1000 ensures it overrides all routing rules
            mod = parser.OFPFlowMod(
                datapath=datapath, priority=1000, match=match, instructions=inst,
                idle_timeout=60, hard_timeout=0
            )
            datapath.send_msg(mod)
            return

        # If authorized, just ignore it and let the static proactive routing handle it
