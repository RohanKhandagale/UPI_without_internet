from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class MeshPacket(BaseModel):
    model_config = ConfigDict(extra="ignore")
    packet_id: str
    ttl: int = Field(ge=0, le=32)
    created_at: int
    ciphertext: str

class PaymentRequest(BaseModel):
    sender_vpa: str
    receiver_vpa: str
    amount: float = Field(gt=0, le=1_000_000)
    pin: str = Field(min_length=4, max_length=8)
    ttl: int = Field(default=5, ge=1, le=32)
    sender_device_id: str = "phone-alice"
