"""In-memory virtual-device network with TTL-limited epidemic gossip."""
from dataclasses import dataclass, field
from threading import RLock
from typing import Dict
from .models import NetworkPacket

@dataclass
class VirtualDevice:
    device_id: str
    has_internet: bool = False
    packets: dict[str, NetworkPacket] = field(default_factory=dict)

class NetworkSimulator:
    def __init__(self):
        self._lock = RLock()
        self.devices: Dict[str, VirtualDevice] = {}
        self.reset()

    def reset(self):
        with self._lock:
            self.devices = {
                "phone-alice": VirtualDevice("phone-alice"),
                "phone-bob": VirtualDevice("phone-bob"),
                "phone-carol": VirtualDevice("phone-carol"),
                "phone-dave": VirtualDevice("phone-dave"),
                "phone-bridge": VirtualDevice("phone-bridge", has_internet=True),
            }

    def inject(self, device_id: str, packet: NetworkPacket):
        with self._lock:
            if device_id not in self.devices:
                raise ValueError("unknown_start_device")
            self.devices[device_id].packets.setdefault(packet.packetId, packet)

    def gossip_round(self):
        with self._lock:
            transfers = 0
            snapshots = {name: list(device.packets.values()) for name, device in self.devices.items()}
            for source_id, packets in snapshots.items():
                for packet in packets:
                    if packet.ttl <= 0:
                        continue
                    for target_id, target in self.devices.items():
                        if target_id == source_id or packet.packetId in target.packets:
                            continue
                        target.packets[packet.packetId] = packet.model_copy(update={"ttl": packet.ttl - 1})
                        transfers += 1
            return {"transfers": transfers, "deviceCounts": {name: len(d.packets) for name, d in self.devices.items()}}

    def state(self, cache_size: int):
        with self._lock:
            return {"devices": [{"deviceId": d.device_id, "hasInternet": d.has_internet,
                                 "packetCount": len(d.packets), "packetIds": list(d.packets.keys())}
                                for d in self.devices.values()], "idempotencyCacheSize": cache_size}

    def bridge_packets(self):
        with self._lock:
            return [(d.device_id, list(d.packets.values())) for d in self.devices.values() if d.has_internet]
