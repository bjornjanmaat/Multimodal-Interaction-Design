package dji.sampleV5.aircraft.macbridge

import android.util.Log
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean

/**
 * High-performance, low-latency TCP bridge server for Mac <-> DJI Drone communication.
 * Communicates using newline-delimited JSON messages.
 */
class MacBridgeServer(
    val port: Int = 9090,
    private val deadmanTimeoutMs: Long = 500L
) {
    private val TAG = "MacBridgeServer"

    interface Listener {
        fun onServerStarted(ip: String, port: Int)
        fun onServerStopped()
        fun onClientConnected(clientIp: String)
        fun onClientDisconnected(clientIp: String)
        fun onStickCommand(pitch: Float, roll: Float, yaw: Float, throttle: Float)
        fun onActionCommand(action: String, params: JSONObject)
        fun onDeadmanSwitchTriggered()
        fun onError(message: String)
    }

    var listener: Listener? = null

    private var serverSocket: ServerSocket? = null
    private val isRunning = AtomicBoolean(false)
    private val clientWriters = CopyOnWriteArrayList<PrintWriter>()
    private val activeClients = ConcurrentHashMap<Socket, String>()

    @Volatile
    private var lastCommandTimestamp = 0L

    @Volatile
    var isWatchdogActive = false

    private var serverThread: Thread? = null
    private var watchdogThread: Thread? = null

    @Synchronized
    fun start() {
        if (isRunning.get()) return

        isRunning.set(true)
        serverThread = Thread({
            try {
                serverSocket = ServerSocket(port)
                val ip = getLocalIpAddress() ?: "127.0.0.1"
                Log.i(TAG, "Mac Bridge Server listening on $ip:$port")
                listener?.onServerStarted(ip, port)

                startWatchdog()

                while (isRunning.get() && serverSocket != null && !serverSocket!!.isClosed) {
                    try {
                        val clientSocket = serverSocket!!.accept()
                        handleNewClient(clientSocket)
                    } catch (e: SocketException) {
                        if (!isRunning.get()) break
                        Log.e(TAG, "Socket accept exception: ${e.message}")
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start server: ${e.message}", e)
                listener?.onError("Server start error: ${e.message}")
            } finally {
                stop()
            }
        }, "MacBridge-ServerThread").apply { start() }
    }

    @Synchronized
    fun stop() {
        if (!isRunning.getAndSet(false)) return

        try {
            watchdogThread?.interrupt()
            watchdogThread = null

            for ((sock, _) in activeClients) {
                try {
                    sock.close()
                } catch (_: Exception) {}
            }
            activeClients.clear()
            clientWriters.clear()

            serverSocket?.close()
            serverSocket = null
        } catch (e: Exception) {
            Log.e(TAG, "Error closing server: ${e.message}")
        }

        listener?.onServerStopped()
    }

    private fun handleNewClient(clientSocket: Socket) {
        val clientIp = clientSocket.remoteSocketAddress.toString()
        Log.i(TAG, "New client connected: $clientIp")
        activeClients[clientSocket] = clientIp

        Thread({
            var writer: PrintWriter? = null
            var reader: BufferedReader? = null
            try {
                clientSocket.tcpNoDelay = true // minimize latency
                writer = PrintWriter(clientSocket.getOutputStream(), true)
                clientWriters.add(writer)

                reader = BufferedReader(InputStreamReader(clientSocket.getInputStream()))
                listener?.onClientConnected(clientIp)

                // Send welcome message
                val welcome = JSONObject().apply {
                    put("type", "welcome")
                    put("status", "connected")
                    put("port", port)
                    put("timestamp", System.currentTimeMillis())
                }
                writer.println(welcome.toString())

                var line: String? = null
                while (isRunning.get()) {
                    val read = reader.readLine() ?: break
                    val msg = read.trim()
                    if (msg.isEmpty()) continue

                    handleClientMessage(msg)
                }
            } catch (e: Exception) {
                Log.d(TAG, "Client $clientIp disconnected: ${e.message}")
            } finally {
                if (writer != null) clientWriters.remove(writer)
                activeClients.remove(clientSocket)
                try {
                    clientSocket.close()
                } catch (_: Exception) {}
                listener?.onClientDisconnected(clientIp)
            }
        }, "MacBridge-Client-$clientIp").start()
    }

    private fun handleClientMessage(jsonStr: String) {
        try {
            val json = JSONObject(jsonStr)
            val cmd = json.optString("cmd", json.optString("type", ""))

            lastCommandTimestamp = System.currentTimeMillis()

            when (cmd) {
                "stick" -> {
                    val pitch = json.optDouble("pitch", 0.0).toFloat()
                    val roll = json.optDouble("roll", 0.0).toFloat()
                    val yaw = json.optDouble("yaw", 0.0).toFloat()
                    val throttle = json.optDouble("throttle", 0.0).toFloat()
                    listener?.onStickCommand(pitch, roll, yaw, throttle)
                }
                "heartbeat" -> {
                    // Just refreshes lastCommandTimestamp
                }
                else -> {
                    listener?.onActionCommand(cmd, json)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse message: $jsonStr - ${e.message}")
        }
    }

    private fun startWatchdog() {
        watchdogThread = Thread({
            while (isRunning.get()) {
                try {
                    Thread.sleep(100)
                    if (isWatchdogActive && lastCommandTimestamp > 0) {
                        val elapsed = System.currentTimeMillis() - lastCommandTimestamp
                        if (elapsed > deadmanTimeoutMs) {
                            listener?.onDeadmanSwitchTriggered()
                            lastCommandTimestamp = System.currentTimeMillis() // avoid repeating every 100ms
                        }
                    }
                } catch (e: InterruptedException) {
                    break
                }
            }
        }, "MacBridge-Watchdog").apply { start() }
    }

    fun broadcastTelemetry(json: JSONObject) {
        val line = json.toString()
        for (w in clientWriters) {
            try {
                w.println(line)
            } catch (e: Exception) {
                Log.w(TAG, "Failed sending telemetry to client: ${e.message}")
            }
        }
    }

    fun getConnectedClientCount(): Int = clientWriters.size

    companion object {
        fun getLocalIpAddress(): String? {
            try {
                val interfaces = NetworkInterface.getNetworkInterfaces()
                val candidateList = mutableListOf<Pair<String, String>>()
                while (interfaces.hasMoreElements()) {
                    val intf = interfaces.nextElement()
                    if (intf.isLoopback || !intf.isUp) continue
                    val name = intf.name.lowercase()
                    val addresses = intf.inetAddresses
                    while (addresses.hasMoreElements()) {
                        val addr = addresses.nextElement()
                        if (!addr.isLoopbackAddress && addr.address.size == 4) {
                            val ip = addr.hostAddress ?: continue
                            // Prioritize wlan (Wi-Fi client) or ap/softap (Android Hotspot)
                            if (name.contains("wlan") || name.contains("ap") || name.contains("swlan")) {
                                return ip
                            }
                            candidateList.add(Pair(name, ip))
                        }
                    }
                }
                // If no wlan/ap found, return first non-cellular if possible
                val nonCellular = candidateList.firstOrNull { !it.first.startsWith("rmnet") && !it.first.startsWith("ccmni") }
                if (nonCellular != null) return nonCellular.second
                if (candidateList.isNotEmpty()) return candidateList.first().second
            } catch (e: Exception) {
                Log.e("MacBridgeServer", "Could not get IP: ${e.message}")
            }
            return null
        }
    }
}
