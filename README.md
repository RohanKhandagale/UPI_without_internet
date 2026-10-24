# UPI Offline Network — Python Demo

A Python/FastAPI backend demo for deferred payment instructions relayed between offline phones. The Python dashboard still includes a virtual gossip simulator. The new `android-ble/` prototype adds real Android Bluetooth Low Energy (BLE) packet transfer and HTTPS bridge upload, while leaving backend processing in Python.

> **Safety note:** This is an educational simulation only. It does not connect to UPI, NPCI, a bank, or real accounts. Never use real PINs or payment data. BLE transport does not make a payment final while offline; the backend's ledger is a demo ledger.

The repository includes hybrid cryptography, a virtual network simulator, idempotency and settlement tests, plus an Android app prototype that can cache the backend public key, create an encrypted demo instruction offline, relay packets over physical BLE, and upload them later. Multi-hop forwarding and production-grade payment controls remain incomplete.

## Table of contents

1. [What this demo proves](#what-this-demo-proves)
2. [How to run it](#how-to-run-it)
3. [The demo flow](#the-demo-flow)
4. [Architecture and communication](#architecture-and-communication)
5. [The three hard problems](#the-three-hard-problems)
6. [Python project structure](#python-project-structure)
7. [API reference](#api-reference)
8. [Tests](#tests)
9. [Production changes](#whats-not-real-and-what-would-change-for-production)
10. [Honest limitations](#honest-limitations-of-the-concept)

## What this demo proves

1. An encrypted payment packet can travel through untrusted virtual intermediaries without them reading or modifying its contents undetected (**RSA-OAEP + AES-256-GCM**).
2. If the same packet reaches the backend through multiple bridge nodes at once, the ledger settles it at most once (**atomic idempotency claim + unique database constraint**).
3. A tampered packet, stale packet, or repeated delivery is rejected before it can cause a second debit.
4. Gossip propagates packets through a virtual network with a time-to-live (TTL); the bridge uploads packets when it has simulated internet access.

## How to run it

### Requirements
- Python 3.10 or newer
- pip

The Python backend requires no Java, Maven, Redis, or external database; SQLite is used for the local demo ledger. Building the separate Android BLE app requires Android Studio, an Android SDK, and a compatible JDK/Gradle setup.

### Windows PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

If PowerShell blocks activation, run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and then `.\.venv\Scripts\python.exe run.py`.

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open **http://127.0.0.1:8080** for the dashboard. Interactive API docs: **http://127.0.0.1:8080/docs**. Stop with `Ctrl+C`.

The first run creates `upi_network.db`, seeds demo accounts, and creates `data/server_private_key.pem` for the backend RSA key. The private-key file is ignored by Git. Keep this file on persistent storage across backend restarts or cached mobile public keys will stop working. Set `UPI_NETWORK_PRIVATE_KEY_PATH` to a secure persistent path in your environment. This local unencrypted key file is for the demo only; production should use a managed KMS/HSM.

### Run tests
```bash
python -m pytest -q
```

## The demo flow

### Step 1 — Compose a payment
Choose sender, receiver, amount, and a four-digit demo PIN, then click **Inject into Network**. The backend simulates the sender phone, creates a unique nonce and timestamp, hashes the PIN for the demonstration payload, encrypts the instruction, wraps it in a packet with TTL 5, and places it on `phone-alice` (or the selected start device).

### Step 2 — Run virtual gossip rounds
Click **Run Gossip Round**. Each virtual device copies packets to other simulated devices. This dashboard simulation assumes every device is in range; it is separate from the Android BLE transport prototype described below.

### Step 3 — Bridge uploads
Click **Bridges Upload to Backend**. `phone-bridge` is seeded as the only device with internet. It submits packets to `/api/bridge/ingest`. The backend hashes ciphertext, atomically claims the hash, decrypts, checks the signed timestamp, then applies debit/credit and inserts the ledger row in one SQLite transaction.

### Step 4 — Demonstrate idempotency
A packet may be delivered more than once to the bridge endpoint, including simultaneously from different bridge nodes. Only the first successful claim proceeds. Further identical ciphertext deliveries return `DUPLICATE_DROPPED`. The concurrency test exercises three threads delivering the same packet at once.

## Architecture and communication

```text
Sender (simulated, offline)
  PaymentInstruction { senderVpa, receiverVpa, amount, pinHash, nonce, signedAt }
      | fresh AES-256 key encrypts JSON with GCM; RSA-OAEP wraps AES key
      v
  NetworkPacket { packetId, ttl, createdAt, ciphertext }
      | virtual gossip rounds; intermediaries see ciphertext only
      v
  phone-alice -> phone-bob / phone-carol / phone-dave -> phone-bridge (internet)
                                                        | HTTP POST /api/bridge/ingest
                                                        v
Backend (FastAPI)
  1. SHA-256 ciphertext hash
  2. Atomic idempotency claim
  3. RSA-OAEP unwrap + AES-GCM decrypt/authenticate
  4. signedAt freshness check (24 hours; 5-minute future-clock tolerance)
  5. SQLite transaction: debit + credit + unique ledger row
```

### How connection and communication work

- **Python dashboard:** its virtual devices remain Python objects in one process; dashboard gossip does not use a radio.
- **Android BLE prototype:** `android-ble/` uses Android BLE GATT advertising, scanning, connecting, and chunked writes to move packet JSON between physical Android phones. Intermediaries store and forward the encrypted packet without decrypting it.
- **Bridge upload:** the mobile app can POST queued packets to `/api/bridge/ingest` over HTTPS when that phone has internet access.
- **Still not implemented:** robust automatic multi-hop forwarding, a background BLE service, bridge authentication, bank consensus, or real UPI integration. The current app is a prototype and needs testing on physical devices. SQLite claims coordinate requests sharing the same local DB file; multi-host deployments need shared coordination and database uniqueness.

## Physical Android BLE transport prototype

This first mobile milestone uses native Android BLE APIs for the radio layer and keeps the backend in Python/FastAPI. Android requires BLE permissions and supports separate central/client and peripheral/server roles; the app implements both so a phone can advertise a packet service and also scan/connect to another phone.

### Open and run

1. Open the repository's `android-ble/` folder in Android Studio.
2. Let Android Studio install the compatible Gradle/Android SDK components and sync the project.
3. Install and run the app on **two physical Android phones** with Bluetooth enabled. BLE peripheral/advertising support varies by device.
4. Grant the requested nearby-device/Bluetooth permissions and keep both apps open.
5. While online, enter the deployed HTTPS backend URL and tap **Fetch/cache backend public key**. Do this before the sender loses internet; the app stores the public key locally.
6. The sender can now turn off internet, enter demo sender/receiver VPAs, amount and a four-digit **demo-only** PIN, then tap **Create encrypted packet offline**. The phone generates a fresh AES-256 key and IV, encrypts the instruction with AES-GCM, wraps the AES key with the cached RSA public key using OAEP/SHA-256, and saves the packet to its local queue. The seeded demo accounts include `alice@demo`, `bob@demo`, `carol@demo` and `dave@demo`.
7. Tap **Start relay** on both phones. The receiver advertises a GATT service; the sender scans for it. Tap **Scan nearby relay and send packet** to transfer the packet in small GATT chunks.
8. The receiving phone validates the packet envelope and stores it in a local queue. It does not decrypt the ciphertext. To relay another hop, use the received packet now loaded in the input and tap send on a phone connected to another relay.
9. On the receiving/bridge phone, enter the deployed HTTPS base URL for FastAPI and tap **Upload queued packets** when internet is available. The app posts each queued packet to `/api/bridge/ingest`.

Expected packet envelope:

```json
{
  "packetId": "a-unique-packet-id",
  "ttl": 5,
  "createdAt": 1730000000000,
  "ciphertext": "base64-encoded-encrypted-payload"
}
```

Use only demo data. This initial prototype does **not** yet create and encrypt a new payment on a phone that has never had internet, automatically relay a packet through an arbitrary chain of phones, or guarantee background operation. It also does not guarantee settlement: an HTTP response of `SETTLED` refers only to this repository's demo ledger. Physical-device builds have not been executed in this repository environment, so test the app on your devices before relying on it.

## The three hard problems

### 1. Untrusted intermediaries — hybrid encryption

For every packet, the sender generates a fresh 256-bit AES key and a 12-byte random IV. JSON is encrypted with **AES-256-GCM** (including a 16-byte authentication tag); the AES key is encrypted using the server's **RSA-2048 public key with OAEP/SHA-256**. The Base64 wire payload is:

```text
[256-byte RSA-wrapped AES key][12-byte IV][AES-GCM ciphertext + 16-byte tag]
```

Only the server holding the matching RSA private key can unwrap the AES key. GCM authentication makes ciphertext modification fail during decryption. The public key is available from `GET /api/server-key`.

### 2. Duplicate storm — idempotency

The server computes `SHA-256(ciphertext)` and inserts the hash into `idempotency_claims`, whose primary key is unique. The database insert is atomic: one concurrent request wins; other copies return `DUPLICATE_DROPPED`. The `transactions.packet_hash` unique constraint is a second line of defence.

Why hash ciphertext? An outer `packetId` can be rewritten by an intermediary, and plaintext is unavailable before decryption. Identical deliveries of the same encrypted packet have identical ciphertext and therefore the same hash.

The local SQLite table stands in for Redis `SET key value NX EX 86400`. A production multi-host service should use shared atomic idempotency storage and retain database uniqueness. This demo keeps claims until reset; production needs a deliberate retention/expiry policy.

### 3. Replay attacks — timestamp and nonce

The encrypted instruction contains `signedAt` and a random UUID `nonce`. Packets older than 24 hours or more than five minutes in the future are rejected. The nonce distinguishes separately composed payments with the same parties and amount; the ciphertext hash identifies replay of the exact same packet. Timestamp and nonce are protected by AES-GCM authentication.

## Python project structure

```text
UPI_without_internet/
├── app/
│   ├── main.py          # FastAPI routes and dashboard
│   ├── models.py        # Pydantic request/wire models
│   ├── database.py      # SQLite schema, accounts, transactions and claims
│   ├── crypto.py        # RSA-OAEP + AES-256-GCM + SHA-256
│   ├── network.py          # virtual devices and gossip protocol
│   ├── services.py      # packet creation, idempotency, ingestion, settlement
│   └── templates/
│       └── dashboard.html
├── tests/
│   └── test_network.py     # crypto, tamper, concurrency and gossip tests
├── android-ble/            # Android BLE transport prototype (Kotlin; backend remains Python)
│   ├── app/src/main/AndroidManifest.xml
│   └── app/src/main/java/com/rohan/upinetwork/ble/MainActivity.kt
├── .env.example
├── Dockerfile
├── compose.yaml
├── requirements.txt
├── pyproject.toml
├── run.py
└── README.md
```

## API reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Interactive dashboard |
| `GET` | `/health` | Health check |
| `GET` | `/api/server-key` | RSA public key (Base64 DER) |
| `GET` | `/api/accounts` | Demo balances |
| `GET` | `/api/transactions` | Last 20 ledger records |
| `GET` | `/api/network/state` | Device state and idempotency count |
| `GET` | `/api/network/devices` | Dashboard-compatible device state |
| `POST` | `/api/demo/send` | Encrypt payment and inject into network |
| `POST` | `/api/payment` | Compatibility alias for the Python dashboard |
| `POST` | `/api/network/gossip` | Run one gossip round |
| `POST` | `/api/network/flush` | Upload packets held by internet-enabled bridges |
| `POST` | `/api/network/reset` | Reset network, claims, ledger and demo balances |
| `POST` | `/api/bridge/ingest` | Ingest one bridge packet |

### `POST /api/bridge/ingest` request

Headers: `X-Bridge-Node-Id: phone-bridge-42`, `X-Hop-Count: 3`.

```json
{
  "packetId": "550e8400-e29b-41d4-a716-446655440000",
  "ttl": 2,
  "createdAt": 1730000000000,
  "ciphertext": "base64-encoded-RSA-and-AES-blob"
}
```

Example response:

```json
{
  "outcome": "SETTLED",
  "packetHash": "a3f8c9...",
  "reason": null,
  "transactionId": 1
}
```

Possible outcomes: `SETTLED`, `DUPLICATE_DROPPED`, `INVALID`, and `REJECTED`. This demo endpoint has no bridge authentication and must not be exposed publicly.

## Tests

- `test_encrypt_decrypt_round_trip` — hybrid encryption round trip.
- `test_tampered_ciphertext_is_rejected` — bit changes fail GCM authentication.
- `test_same_packet_delivered_concurrently_settles_once` — three concurrent deliveries yield one settlement and two duplicate drops; balances change once.
- `test_gossip_propagates_packets` — gossip copies packets to virtual devices.

Run `python -m pytest -q`.

## What's not real and what would change for production

| Demo implementation | Production direction |
|---|---|
| SQLite local database | PostgreSQL/MySQL with carefully designed transactions and replicas |
| SQLite idempotency primary key | Redis `SET NX EX` or another shared atomic claim, plus unique ledger constraint |
| RSA key stored in a local demo PEM file | Managed key lifecycle/HSM/KMS; provision and rotate keys safely; use persistent storage for the demo key |
| Python backend simulates sender | Separate mobile client with secure public-key provisioning |
| Virtual gossip objects | Android BLE GATT transport prototype exists; robust automatic multi-hop forwarding and durable background service remain future work |
| No bridge authentication | Mutual TLS or signed bridge credentials, authorization and rate limits |
| Demo balances and PIN field | Real account systems and bank-approved authentication; never trust a client-provided PIN hash |
| No monitoring/rate limits | Structured logs, alerts, abuse detection and audit trail |

## Honest limitations of the concept

1. **The receiver cannot know the sender has sufficient funds while every device is offline.** This is a deferred instruction, not a guaranteed settled transfer. Settlement may be rejected when the packet reaches the backend.
2. **Offline double-spending is not solved.** A sender can create multiple offline instructions against the same apparent balance; the first valid instruction to settle can consume the funds.
3. **Bluetooth relay is still a prototype.** Foreground BLE packet transfer is implemented in the Android module, but automatic multi-hop forwarding, robust retry/recovery, background operation, and device compatibility need more engineering.
4. **Privacy metadata remains.** Intermediaries cannot decrypt the payload, but can observe packet existence, timing, and size.
5. **This is not a real UPI integration.** No NPCI/bank APIs, real account verification, regulatory approvals, or real settlement are included.

For a portfolio, describe this as **network-routed deferred settlement** rather than real-time offline UPI. The encryption, idempotency, replay checks, gossip simulation, and concurrency test are the core educational engineering features.

## Troubleshooting

- **Module not found:** activate the virtual environment and run `python -m pip install -r requirements.txt`.
- **Port 8080 is busy:** set `UPI_NETWORK_PORT=8081` before running.
- **Database state looks old:** stop the server, back up and remove `upi_network.db`, then restart to seed a fresh demo database.
- **Tests fail:** run `python -m pytest -vv` and inspect the first failure. Tests use a temporary database.

## License

No license specified. Use for learning and demonstration; review dependencies and add an explicit license before redistribution.
