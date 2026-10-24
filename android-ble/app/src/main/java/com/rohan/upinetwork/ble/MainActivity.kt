package com.rohan.upinetwork.ble

import android.Manifest
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattServer
import android.bluetooth.BluetoothGattServerCallback
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.AdvertiseCallback
import android.bluetooth.le.AdvertiseData
import android.bluetooth.le.AdvertiseSettings
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.ParcelUuid
import android.util.Base64
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Real BLE transport prototype. It relays encrypted NetworkPacket JSON without decrypting it.
 * This is a transport demo, not a real UPI/payment client.
 */
class MainActivity : Activity() {
    companion object {
        private val SERVICE_UUID: UUID = UUID.fromString("e6c40001-7a2b-4b0b-9d2a-2f3f8f0a1000")
        private val PACKET_CHAR_UUID: UUID = UUID.fromString("e6c40002-7a2b-4b0b-9d2a-2f3f8f0a1000")
        private const val PREFS = "offline_ble_queue"
        private const val QUEUE_KEY = "packets"
        private const val PERMISSION_REQUEST = 41
        // Default ATT MTU is 23 bytes, leaving 20 bytes for a characteristic value.
        private const val CHUNK_BYTES = 16
    }

    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var packetInput: EditText
    private lateinit var serverUrlInput: EditText
    private var gattServer: BluetoothGattServer? = null
    private var advertiserCallback: AdvertiseCallback? = null
    private var scannerCallback: ScanCallback? = null
    private var connectedGatt: BluetoothGatt? = null
    private var writeCharacteristic: BluetoothGattCharacteristic? = null
    private var pendingChunks: List<ByteArray> = emptyList()
    private var nextChunk = 0
    private var transferInProgress = false
    private var lastDiscovered: BluetoothDevice? = null
    private var isAdvertising = false

    private val bluetoothManager by lazy { getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager }
    private val adapter: BluetoothAdapter? get() = bluetoothManager.adapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        status("Ready. Start relay on both phones. Paste an encrypted NetworkPacket JSON to send.")
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 24, 28, 24)
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        }
        val scroll = ScrollView(this)
        val content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        content.addView(TextView(this).apply {
            text = "UPI Offline Network — Real BLE Transport"
            textSize = 22f
        })
        content.addView(TextView(this).apply {
            text = "Transport prototype: relays encrypted packet JSON over physical Bluetooth LE. No real payment is made."
            textSize = 14f
            setPadding(0, 8, 0, 16)
        })
        packetInput = EditText(this).apply {
            hint = "Paste full packet JSON: packetId, ttl, createdAt, ciphertext"
            minLines = 5
            gravity = android.view.Gravity.TOP
            setText("")
        }
        content.addView(packetInput)
        serverUrlInput = EditText(this).apply {
            hint = "Backend HTTPS base URL, e.g. https://your-service.example.com"
            setSingleLine(true)
            setText("https://your-service.example.com")
        }
        content.addView(serverUrlInput)
        content.addView(button("1. Start relay (advertise + listen)") { startRelay() })
        content.addView(button("2. Scan nearby relay and send packet") { scanAndSend() })
        content.addView(button("3. Upload queued packets (bridge with internet)") { uploadQueuedPackets() })
        content.addView(button("Show queue") { status("Queued packets: ${queuedPackets().length()}") })
        content.addView(button("Clear queue") {
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(QUEUE_KEY, "[]").apply()
            status("Local demo queue cleared.")
        })
        status = TextView(this).apply {
            textSize = 14f
            setPadding(0, 18, 0, 0)
            text = "Initializing…"
        }
        content.addView(status)
        scroll.addView(content)
        root.addView(scroll)
        setContentView(root)
    }

    private fun button(label: String, action: () -> Unit): Button =
        Button(this).apply { text = label; setOnClickListener { action() } }

    private fun status(message: String) {
        runOnUiThread { if (::status.isInitialized) status.text = message }
    }

    private fun requiredPermissions(): Array<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_ADVERTISE)
        } else {
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)
        }
    }

    private fun ensurePermissions(onGranted: () -> Unit) {
        val missing = requiredPermissions().filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) onGranted()
        else requestPermissions(missing.toTypedArray(), PERMISSION_REQUEST)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST && grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            startRelay()
        } else if (requestCode == PERMISSION_REQUEST) {
            status("Bluetooth permissions are required. Grant them and tap Start relay again.")
        }
    }

    private fun startRelay() {
        ensurePermissions {
            val bt = adapter
            if (bt == null || !bt.isEnabled) {
                status("Bluetooth is unavailable or turned off. Enable Bluetooth and retry.")
                return@ensurePermissions
            }
            startGattServer()
            startAdvertising()
            startScanningForRelay()
        }
    }

    private fun startGattServer() {
        if (gattServer != null) return
        val server = bluetoothManager.openGattServer(this, object : BluetoothGattServerCallback() {
            override fun onConnectionStateChange(device: BluetoothDevice, statusCode: Int, newState: Int) {
                status(if (newState == BluetoothProfile.STATE_CONNECTED) "Relay connected: ${device.address}" else "Relay link changed: state=$newState status=$statusCode")
            }

            override fun onCharacteristicWriteRequest(
                device: BluetoothDevice,
                requestId: Int,
                characteristic: BluetoothGattCharacteristic,
                preparedWrite: Boolean,
                responseNeeded: Boolean,
                offset: Int,
                value: ByteArray
            ) {
                if (characteristic.uuid == PACKET_CHAR_UUID && offset == 0) {
                    try {
                        acceptChunk(value)
                        if (responseNeeded) gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null)
                    } catch (ex: Exception) {
                        if (responseNeeded) gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, 0, null)
                        status("Rejected malformed BLE chunk: ${ex.message}")
                    }
                } else if (responseNeeded) {
                    gattServer?.sendResponse(device, requestId, BluetoothGatt.GATT_REQUEST_NOT_SUPPORTED, 0, null)
                }
            }
        })
        if (server == null) {
            status("Could not open BLE GATT server. This phone may not support BLE peripheral mode.")
            return
        }
        gattServer = server
        val service = BluetoothGattService(SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY)
        val characteristic = BluetoothGattCharacteristic(
            PACKET_CHAR_UUID,
            BluetoothGattCharacteristic.PROPERTY_WRITE or BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
            BluetoothGattCharacteristic.PERMISSION_WRITE
        )
        service.addCharacteristic(characteristic)
        server.addService(service)
    }

    private fun startAdvertising() {
        if (isAdvertising) return
        val advertiser = adapter?.bluetoothLeAdvertiser
        if (advertiser == null) {
            status("BLE advertising is unavailable on this phone. It can still act as a scanner/client.")
            return
        }
        val settings = AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_LOW)
            .setConnectable(true)
            .build()
        val data = AdvertiseData.Builder().addServiceUuid(ParcelUuid(SERVICE_UUID)).setIncludeDeviceName(false).build()
        val callback = object : AdvertiseCallback() {
            override fun onStartSuccess(settingsInEffect: AdvertiseSettings) {
                isAdvertising = true
                status("Relay is advertising and accepting packet writes over BLE.")
            }
            override fun onStartFailure(errorCode: Int) {
                status("BLE advertising failed (code $errorCode). Keep the app open and check device BLE support.")
            }
        }
        advertiserCallback = callback
        advertiser.startAdvertising(settings, data, callback)
    }

    private fun startScanningForRelay() {
        if (scannerCallback != null) return
        val scanner = adapter?.bluetoothLeScanner ?: run {
            status("BLE scanner unavailable.")
            return
        }
        val filter = ScanFilter.Builder().setServiceUuid(ParcelUuid(SERVICE_UUID)).build()
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                lastDiscovered = result.device
            }
            override fun onScanFailed(errorCode: Int) {
                status("BLE scan failed: $errorCode")
            }
        }
        scannerCallback = callback
        scanner.startScan(listOf(filter), settings, callback)
        status("Scanning for nearby phones running this BLE relay app…")
    }

    private fun scanAndSend() {
        ensurePermissions {
            val packetText = packetInput.text.toString().trim()
            if (packetText.isEmpty()) {
                status("Paste a complete encrypted NetworkPacket JSON before sending.")
                return@ensurePermissions
            }
            try {
                val packet = JSONObject(packetText)
                if (!packet.has("packetId") || !packet.has("ttl") || !packet.has("createdAt") || !packet.has("ciphertext")) {
                    status("Packet JSON must contain packetId, ttl, createdAt and ciphertext.")
                    return@ensurePermissions
                }
                val device = lastDiscovered
                if (device == null) {
                    startRelay()
                    status("No relay discovered yet. Keep both apps open and tap Send again after scanning.")
                    return@ensurePermissions
                }
                sendPacketTo(device, packetText)
            } catch (ex: Exception) {
                status("Invalid packet JSON: ${ex.message}")
            }
        }
    }

    private fun sendPacketTo(device: BluetoothDevice, packetJson: String) {
        if (transferInProgress) {
            status("A BLE transfer is already running.")
            return
        }
        transferInProgress = true
        val raw = packetJson.toByteArray(Charsets.UTF_8)
        val pieces = raw.toList().chunked(CHUNK_BYTES)
        if (pieces.size > 65535) {
            transferInProgress = false
            status("Packet is too large for this prototype.")
            return
        }
        pendingChunks = pieces.mapIndexed { index, piece ->
            byteArrayOf(
                ((index shr 8) and 0xff).toByte(), (index and 0xff).toByte(),
                ((pieces.size shr 8) and 0xff).toByte(), (pieces.size and 0xff).toByte()
            ) + piece.toByteArray()
        }
        nextChunk = 0
        connectedGatt = device.connectGatt(this, false, object : BluetoothGattCallback() {
            override fun onConnectionStateChange(gatt: BluetoothGatt, statusCode: Int, newState: Int) {
                if (statusCode != BluetoothGatt.GATT_SUCCESS || newState == BluetoothProfile.STATE_DISCONNECTED) {
                    transferInProgress = false
                    gatt.close()
                    status("BLE connection ended (status=$statusCode). Retry the transfer.")
                } else if (newState == BluetoothProfile.STATE_CONNECTED) {
                    gatt.requestMtu(247)
                    gatt.discoverServices()
                }
            }

            override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, statusCode: Int) {
                // The chunk protocol remains safe with the default MTU; wait for service discovery.
            }

            override fun onServicesDiscovered(gatt: BluetoothGatt, statusCode: Int) {
                val service = gatt.getService(SERVICE_UUID)
                writeCharacteristic = service?.getCharacteristic(PACKET_CHAR_UUID)
                if (statusCode != BluetoothGatt.GATT_SUCCESS || writeCharacteristic == null) {
                    transferInProgress = false
                    gatt.disconnect()
                    status("Nearby device does not expose the expected packet service.")
                    return
                }
                writeNextChunk(gatt)
            }

            override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, statusCode: Int) {
                if (statusCode != BluetoothGatt.GATT_SUCCESS) {
                    transferInProgress = false
                    gatt.disconnect()
                    status("BLE chunk write failed ($statusCode). Retry the packet.")
                } else {
                    nextChunk++
                    writeNextChunk(gatt)
                }
            }
        })
        status("Connecting to nearby relay…")
    }

    private fun writeNextChunk(gatt: BluetoothGatt) {
        if (nextChunk >= pendingChunks.size) {
            transferInProgress = false
            gatt.disconnect()
            status("Packet sent over BLE (${pendingChunks.size} chunks). Receiver should show it in its queue.")
            return
        }
        val characteristic = writeCharacteristic ?: run {
            transferInProgress = false
            gatt.disconnect()
            status("BLE packet characteristic disappeared.")
            return
        }
        val value = pendingChunks[nextChunk]
        val started = if (Build.VERSION.SDK_INT >= 33) {
            gatt.writeCharacteristic(characteristic, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothGatt.GATT_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            run {
                characteristic.value = value
                characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
                gatt.writeCharacteristic(characteristic)
            }
        }
        if (!started) {
            transferInProgress = false
            gatt.disconnect()
            status("Could not start BLE write for chunk $nextChunk.")
        }
    }

    // Wire format: 2-byte index, 2-byte total, then up to 16 bytes of packet JSON.
    private fun acceptChunk(value: ByteArray) {
        if (value.size < 5) throw IllegalArgumentException("chunk_too_short")
        val index = ((value[0].toInt() and 0xff) shl 8) or (value[1].toInt() and 0xff)
        val total = ((value[2].toInt() and 0xff) shl 8) or (value[3].toInt() and 0xff)
        if (total <= 0 || index >= total) throw IllegalArgumentException("invalid_chunk_index")
        val bytes = value.copyOfRange(4, value.size)
        synchronized(receiveChunks) {
            if (receiveTotal != total) {
                receiveChunks.clear()
                receiveTotal = total
            }
            receiveChunks[index] = bytes
            if (receiveChunks.size == receiveTotal) {
                val joined = (0 until receiveTotal).flatMap { i ->
                    receiveChunks[i]?.toList() ?: throw IllegalArgumentException("missing_chunk")
                }.toByteArray()
                val jsonText = joined.toString(Charsets.UTF_8)
                val packet = JSONObject(jsonText)
                listOf("packetId", "ttl", "createdAt", "ciphertext").forEach {
                    if (!packet.has(it)) throw IllegalArgumentException("missing_$it")
                }
                enqueuePacket(jsonText)
                runOnUiThread { packetInput.setText(jsonText) }
                receiveChunks.clear()
                receiveTotal = -1
                status("Received and queued encrypted packet ${packet.getString("packetId")}.")
            }
        }
    }

    private val receiveChunks = mutableMapOf<Int, ByteArray>()
    private var receiveTotal = -1

    private fun queuedPackets(): JSONArray {
        val text = getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(QUEUE_KEY, "[]") ?: "[]"
        return try { JSONArray(text) } catch (_: Exception) { JSONArray() }
    }

    private fun enqueuePacket(packetJson: String) {
        synchronized(this) {
            val queue = queuedPackets()
            val id = JSONObject(packetJson).getString("packetId")
            for (i in 0 until queue.length()) {
                if (queue.getJSONObject(i).optString("packetId") == id) return
            }
            queue.put(JSONObject(packetJson))
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(QUEUE_KEY, queue.toString()).apply()
        }
    }

    private fun uploadQueuedPackets() {
        val base = serverUrlInput.text.toString().trim().trimEnd('/')
        if (!base.startsWith("https://")) {
            status("Use an HTTPS backend URL. Do not send payment packets over public HTTP.")
            return
        }
        val queue = queuedPackets()
        if (queue.length() == 0) {
            status("No queued packets to upload.")
            return
        }
        status("Uploading ${queue.length()} queued packet(s) to FastAPI…")
        executor.execute {
            val remaining = JSONArray()
            val outcomes = mutableListOf<String>()
            for (i in 0 until queue.length()) {
                val packet = queue.getJSONObject(i)
                var delivered = false
                var outcome = "UPLOAD_FAILED"
                try {
                    val connection = (URL("$base/api/bridge/ingest").openConnection() as HttpURLConnection).apply {
                        requestMethod = "POST"
                        connectTimeout = 10000
                        readTimeout = 15000
                        doOutput = true
                        setRequestProperty("Content-Type", "application/json")
                        setRequestProperty("X-Bridge-Node-Id", "android-ble-bridge")
                        setRequestProperty("X-Hop-Count", "1")
                    }
                    connection.outputStream.use { output ->
                        BufferedOutputStream(output).use { it.write(packet.toString().toByteArray(Charsets.UTF_8)) }
                    }
                    val code = connection.responseCode
                    val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                    val response = stream?.bufferedReader()?.use { it.readText() } ?: ""
                    if (code in 200..299) {
                        delivered = true
                        outcome = JSONObject(response).optString("outcome", "UPLOADED")
                    } else {
                        outcome = "HTTP_$code"
                    }
                    connection.disconnect()
                } catch (ex: Exception) {
                    outcome = "UPLOAD_FAILED: ${ex.javaClass.simpleName}"
                }
                outcomes.add("${packet.optString("packetId")}: $outcome")
                if (!delivered) remaining.put(packet)
            }
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(QUEUE_KEY, remaining.toString()).apply()
            status("Bridge upload finished. Remaining queue: ${remaining.length()}. " + outcomes.joinToString(" | "))
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try { scannerCallback?.let { adapter?.bluetoothLeScanner?.stopScan(it) } } catch (_: Exception) {}
        try { advertiserCallback?.let { adapter?.bluetoothLeAdvertiser?.stopAdvertising(it) } } catch (_: Exception) {}
        try { connectedGatt?.close() } catch (_: Exception) {}
        try { gattServer?.close() } catch (_: Exception) {}
        executor.shutdown()
    }
}
