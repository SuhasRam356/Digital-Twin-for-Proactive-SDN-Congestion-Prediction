from ryu.base import app_manager  # type: ignore
from ryu.controller import ofp_event  # type: ignore
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER  # type: ignore
from ryu.controller.handler import set_ev_cls  # type: ignore
from ryu.lib import hub  # type: ignore
import zmq  # type: ignore
import json

class TelemetryStreamer(app_manager.RyuApp):
    def __init__(self, *args, **kwargs):
        super(TelemetryStreamer, self).__init__(*args, **kwargs)
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        
        # ZeroMQ Publisher Setup
        context = zmq.Context()
        self.zmq_socket = context.socket(zmq.PUB)
        self.zmq_socket.bind("tcp://*:5555")
        self.logger.info("Telemetry Streamer (ZMQ PUB) listening on tcp://*:5555")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info(f"Registering datapath: {datapath.id}")
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info(f"Unregistering datapath: {datapath.id}")
                del self.datapaths[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            # Sub-second polling (500ms)
            hub.sleep(0.5)

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Request Port Stats
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
        
        # Request Flow Stats (for heavy flow tracking)
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        msg = ev.msg
        dpid = msg.datapath.id
        
        stats = []
        for stat in msg.body:
            # Ignore local port
            if stat.port_no == 4294967294:
                continue
            stats.append({
                "port_no": stat.port_no,
                "tx_bytes": stat.tx_bytes,
                "rx_bytes": stat.rx_bytes
            })
            
        payload = {
            "type": "port_stats",
            "dpid": dpid,
            "stats": stats
        }
        self.zmq_socket.send_string("telemetry " + json.dumps(payload, default=str))

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        msg = ev.msg
        dpid = msg.datapath.id
        
        flows = []
        for stat in msg.body:
            flows.append({
                "match": stat.match,
                "instructions": stat.instructions, # Might be complex to serialize, we just need actions really
                "byte_count": stat.byte_count
            })
            
        # Due to serialization complexity of Ryu match/instructions, 
        # for this PoC we will keep using REST API for heavy flow parsing,
        # or we serialize carefully:
        
        serializable_flows = []
        for stat in msg.body:
            actions = []
            for inst in stat.instructions:
                if type(inst).__name__ == 'OFPInstructionActions':
                    for action in inst.actions:
                        if type(action).__name__ == 'OFPActionOutput':
                            actions.append(f"OUTPUT:{action.port}")
            
            match_dict = dict(stat.match.items())
            if "eth_dst" in match_dict and "dl_dst" not in match_dict:
                match_dict["dl_dst"] = match_dict["eth_dst"]
            if "eth_src" in match_dict and "dl_src" not in match_dict:
                match_dict["dl_src"] = match_dict["eth_src"]
            if "vlan_vid" in match_dict and "dl_vlan" not in match_dict:
                vid = match_dict["vlan_vid"]
                if isinstance(vid, (list, tuple)):
                    vid = vid[0]
                match_dict["dl_vlan"] = str(vid & ~0x1000) if isinstance(vid, int) else str(vid)
            
            serializable_flows.append({
                "match": match_dict,
                "actions": actions,
                "byte_count": stat.byte_count
            })
            
        payload = {
            "type": "flow_stats",
            "dpid": dpid,
            "flows": serializable_flows
        }
        self.zmq_socket.send_string("telemetry " + json.dumps(payload, default=str))

