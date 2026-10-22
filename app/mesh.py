"""In-memory virtual BLE mesh used to demonstrate offline packet forwarding."""
from dataclasses import dataclass, field
from app.models import MeshPacket

@dataclass
class VirtualDevice:
    device_id: str
    has_internet: bool = False
    packets: dict[str, MeshPacket] = field(default_factory=dict)
    def hold(self, packet: MeshPacket): self.packets.setdefault(packet.packet_id, packet.model_copy(deep=True))
    def clear(self): self.packets.clear()
    def packet_count(self): return len(self.packets)

class MeshSimulator:
    def __init__(self): self.seed()
    def seed(self):
        self.devices={d.device_id:d for d in [VirtualDevice("phone-alice"),VirtualDevice("phone-stranger1"),VirtualDevice("phone-stranger2"),VirtualDevice("phone-stranger3"),VirtualDevice("phone-bridge",True)]}
    def inject(self, device_id, packet):
        if device_id not in self.devices: raise ValueError(f"Unknown device: {device_id}")
        self.devices[device_id].hold(packet)
    def snapshot(self): return {k:v.packet_count() for k,v in self.devices.items()}
    def gossip_once(self):
        snapshot={k:list(v.packets.values()) for k,v in self.devices.items()}; transfers=0
        for source_id, packets in snapshot.items():
            for packet in packets:
                if packet.ttl <= 0: continue
                for target_id,target in self.devices.items():
                    if target_id==source_id or packet.packet_id in target.packets: continue
                    target.hold(packet.model_copy(update={"ttl":packet.ttl-1})); transfers+=1
        return {"transfers":transfers,"device_counts":self.snapshot()}
    def bridge_uploads(self): return [(d.device_id,p) for d in self.devices.values() if d.has_internet for p in d.packets.values()]
    def reset(self):
        for device in self.devices.values(): device.clear()
