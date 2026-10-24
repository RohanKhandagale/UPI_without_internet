from pydantic import BaseModel, Field
from typing import Optional

class MeshPacket(BaseModel):
    packetId: str
    ttl: int = Field(ge=0, le=255)
    createdAt: int
    ciphertext: str

class SendRequest(BaseModel):
    senderVpa: str
    receiverVpa: str
    amount: float = Field(gt=0, le=1000000)
    pin: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")
    ttl: int = Field(default=5, ge=1, le=20)
    startDevice: str = "phone-alice"

class IngestResponse(BaseModel):
    outcome: str
    packetHash: str
    reason: Optional[str] = None
    transactionId: Optional[int] = None
