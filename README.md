# UPI Without Internet — Python Edition

An educational Python/FastAPI port of the offline mesh payment demo concept. It simulates encrypted payment instructions moving between nearby virtual devices while offline, then being uploaded by an internet-connected bridge node.

> **Safety note:** This is only a simulation. It does not connect to UPI, NPCI, a bank, or any real payment network. Use fake demo data only. Do not enter real UPI PINs or account details.

## Features
- Offline virtual-device mesh with gossip forwarding and TTL.
- Hybrid encryption: AES-256-GCM for payload encryption and RSA-OAEP/SHA-256 to wrap the one-time AES key.
- Bridge ingestion endpoint for when connectivity returns.
- SHA-256 ciphertext idempotency to drop duplicate bridge deliveries.
- Replay freshness checks for old or future-dated packets.
- Atomic debit/credit settlement using SQLite transactions.
- Browser dashboard for composing payments, gossip, bridge upload, balances and recent transactions.
- pytest coverage and Docker Compose setup.

## Architecture
```text
Sender -> AES-GCM encrypted MeshPacket -> virtual phones gossip packet
                                      -> internet bridge -> ingestion API
                                      -> idempotency + decrypt + replay check
                                      -> atomic SQLite demo ledger
```

## Requirements
- Python 3.11+
- FastAPI, Uvicorn, cryptography, pydantic-settings

## Run on Windows PowerShell
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```
Open http://127.0.0.1:8080 for the dashboard and http://127.0.0.1:8080/docs for interactive API docs.

## Run on macOS/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

The app creates a local RSA keypair on first start and seeds demo accounts: Alice ₹5,000, Bob ₹1,000, Carol ₹2,500, Dave ₹500. Key files and the local SQLite database are ignored by Git.

## Demo flow
1. Choose sender/receiver, amount, and a fake demo PIN; click **Inject into Mesh**.
2. Click **Run Gossip Round** to forward the encrypted packet to devices that have not seen it.
3. Click **Bridges Upload to Backend** to submit packets held by the simulated internet bridge.
4. Check balances and recent transactions. Delivering identical ciphertext again should be dropped.
5. Reset mesh/cache to clear held packets and idempotency records.

## API endpoints
| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/public-key` | Server public key and crypto description |
| POST | `/api/payment` | Encrypt payment instruction and inject packet |
| GET | `/api/mesh/devices` | View devices and packets held |
| POST | `/api/mesh/gossip` | Run one gossip round |
| POST | `/api/mesh/flush` | Upload packets held by bridge devices |
| POST | `/api/mesh/reset` | Clear mesh and idempotency cache |
| POST | `/api/bridge/ingest` | Ingest one packet; accepts `X-Bridge-Node-Id` and `X-Hop-Count` headers |
| GET | `/api/accounts` | Demo balances |
| GET | `/api/transactions` | Latest 20 transactions |

## Tests
```bash
pytest -q
```

## Docker
```bash
docker compose up --build
```
Then open http://127.0.0.1:8080.

## Project layout
```text
app/
  main.py                  FastAPI routes and ingestion pipeline
  config.py                Environment settings
  crypto.py                RSA-OAEP + AES-GCM hybrid encryption
  mesh.py                  Virtual devices and gossip simulator
  models.py                Pydantic request/packet schemas
  store.py                 SQLite ledger and idempotency persistence
  templates/dashboard.html Live dashboard
 tests/test_api.py          API and resilience tests
 Dockerfile, compose.yaml, requirements.txt, pyproject.toml
```

## Limitations and security
This is not production payment software. It does not validate a real bank PIN, authenticate a real user, integrate with NPCI/UPI, or use a bank ledger. The mesh is in-memory, and the server key lifecycle is simplified for learning. A real deployment needs a formal threat model, secure device/key management, fraud controls, transaction limits, regulated settlement integration, and security review. Never commit generated private keys or real financial data.

## Credits
Inspired by the offline mesh payment demonstration concept in [perryvegehan/UPI_Without_Internet](https://github.com/perryvegehan/UPI_Without_Internet). This repository is an independently written Python/FastAPI implementation.