package dji.sampleV5.aircraft.macbridge

import android.os.Handler
import android.os.Looper
import androidx.lifecycle.MutableLiveData
import dji.sampleV5.aircraft.models.DJIViewModel
import dji.sdk.keyvalue.key.BatteryKey
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.et.action
import dji.v5.et.cancelListen
import dji.v5.et.create
import dji.v5.et.listen
import dji.v5.manager.aircraft.virtualstick.Stick
import dji.v5.manager.aircraft.virtualstick.VirtualStickManager
import dji.v5.manager.aircraft.virtualstick.VirtualStickState
import dji.v5.manager.aircraft.virtualstick.VirtualStickStateListener
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.datacenter.livestream.LiveStreamSettings
import dji.v5.manager.datacenter.livestream.LiveStreamStatus
import dji.v5.manager.datacenter.livestream.LiveStreamStatusListener
import dji.v5.manager.datacenter.livestream.LiveStreamType
import dji.v5.manager.datacenter.livestream.settings.RtspSettings
import dji.v5.manager.interfaces.ILiveStreamManager
import dji.sdk.keyvalue.value.flightcontroller.FlightControlAuthorityChangeReason
import dji.v5.utils.common.LogUtils
import org.json.JSONObject
import java.util.Timer
import java.util.TimerTask
import kotlin.math.max
import kotlin.math.min

/**
 * ViewModel managing the bridge between Mac input/video and DJI drone SDK.
 */
class MacBridgeVM : DJIViewModel(), MacBridgeServer.Listener {

    private val tag = LogUtils.getTag(this)
    private val mainHandler = Handler(Looper.getMainLooper())

    val serverStatus = MutableLiveData("Stopped")
    val serverIpAndPort = MutableLiveData("Not running")
    val clientCount = MutableLiveData(0)
    val rtspUrl = MutableLiveData("")
    val isRtspStreaming = MutableLiveData(false)
    val isVirtualStickEnabled = MutableLiveData(false)
    val lastStickValues = MutableLiveData("Pitch: 0.00  Roll: 0.00  Yaw: 0.00  Throttle: 0.00")
    val logMessages = MutableLiveData<List<String>>(emptyList())

    // Drone telemetry cache
    private var altitude: Double = 0.0
    private var compassHeading: Double = 0.0
    private var isFlying: Boolean = false
    private var areMotorsOn: Boolean = false
    private var batteryPercent: Int = 0
    private var isConnected: Boolean = false

    private val liveStreamManager: ILiveStreamManager = MediaDataCenter.getInstance().liveStreamManager
    private val server = MacBridgeServer(port = 9090, deadmanTimeoutMs = 500L)
    private var telemetryTimer: Timer? = null

    private val liveStreamStatusListener = object : LiveStreamStatusListener {
        override fun onLiveStreamStatusUpdate(status: LiveStreamStatus?) {
            mainHandler.post {
                isRtspStreaming.value = status?.isStreaming ?: false
            }
        }

        override fun onError(error: IDJIError?) {
            error?.let {
                addLog("RTSP Stream error: ${it.description()}")
            }
        }
    }

    private val virtualStickListener = object : VirtualStickStateListener {
        override fun onVirtualStickStateUpdate(stickState: VirtualStickState) {
            mainHandler.post {
                isVirtualStickEnabled.value = stickState.isVirtualStickEnable
                server.isWatchdogActive = stickState.isVirtualStickEnable
            }
        }

        override fun onChangeReasonUpdate(reason: FlightControlAuthorityChangeReason) {
            addLog("Flight control authority reason: $reason")
        }
    }

    init {
        server.listener = this
        initDroneListeners()
        VirtualStickManager.getInstance().setVirtualStickStateListener(virtualStickListener)
        liveStreamManager.addLiveStreamStatusListener(liveStreamStatusListener)
    }

    fun startBridge(rtspPort: Int = 8554) {
        server.start()
        startRtspStream(rtspPort)
        startTelemetryLoop()
        addLog("Mac Bridge started.")
    }

    fun stopBridge() {
        resetSticks()
        server.stop()
        stopRtspStream()
        stopTelemetryLoop()
        addLog("Mac Bridge stopped.")
    }

    fun startRtspStream(port: Int = 8554, username: String = "admin", pass: String = "123456") {
        val rtspSettings = RtspSettings.Builder()
            .setUserName(username)
            .setPassWord(pass)
            .setPort(port)
            .build()

        val settings = LiveStreamSettings.Builder()
            .setLiveStreamType(LiveStreamType.RTSP)
            .setRtspSettings(rtspSettings)
            .build()

        liveStreamManager.liveStreamSettings = settings
        liveStreamManager.startStream(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                val ip = MacBridgeServer.getLocalIpAddress() ?: "127.0.0.1"
                val url = "rtsp://$username:$pass@$ip:$port/streaming/live/1"
                mainHandler.post {
                    rtspUrl.value = url
                    isRtspStreaming.value = true
                }
                addLog("RTSP Stream started: $url")
            }

            override fun onFailure(error: IDJIError) {
                addLog("RTSP Stream start failed: ${error.description()}")
            }
        })
    }

    fun stopRtspStream() {
        liveStreamManager.stopStream(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                mainHandler.post {
                    isRtspStreaming.value = false
                    rtspUrl.value = ""
                }
                addLog("RTSP Stream stopped.")
            }

            override fun onFailure(error: IDJIError) {
                addLog("RTSP Stream stop failed: ${error.description()}")
            }
        })
    }

    fun enableVirtualStick() {
        VirtualStickManager.getInstance().enableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                mainHandler.post { isVirtualStickEnabled.value = true }
                server.isWatchdogActive = true
                addLog("Virtual Stick enabled.")
            }

            override fun onFailure(error: IDJIError) {
                addLog("Enable Virtual Stick failed: ${error.description() ?: error.toString()} (code: ${error.errorCode()})")
            }
        })
    }

    fun disableVirtualStick() {
        resetSticks()
        VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                mainHandler.post { isVirtualStickEnabled.value = false }
                server.isWatchdogActive = false
                addLog("Virtual Stick disabled.")
            }

            override fun onFailure(error: IDJIError) {
                addLog("Disable Virtual Stick failed: ${error.description() ?: error.toString()} (code: ${error.errorCode()})")
            }
        })
    }

    fun takeOff() {
        FlightControllerKey.KeyStartTakeoff.create().action({
            addLog("Takeoff initiated successfully.")
        }, { error ->
            val code = error.errorCode()
            val desc = error.description() ?: error.toString()
            addLog("Takeoff failed: $desc [code: $code]")
        })
    }

    fun land() {
        FlightControllerKey.KeyStartAutoLanding.create().action({
            addLog("Auto landing initiated.")
        }, { error ->
            val code = error.errorCode()
            val desc = error.description() ?: error.toString()
            addLog("Landing failed: $desc [code: $code]")
        })
    }

    fun armMotorsCSC() {
        addLog("Attempting CSC (Stick Arm) to start motors...")
        val stickManager = VirtualStickManager.getInstance()
        stickManager.leftStick.verticalPosition = -Stick.MAX_STICK_POSITION_ABS
        stickManager.leftStick.horizontalPosition = Stick.MAX_STICK_POSITION_ABS
        stickManager.rightStick.verticalPosition = -Stick.MAX_STICK_POSITION_ABS
        stickManager.rightStick.horizontalPosition = -Stick.MAX_STICK_POSITION_ABS

        mainHandler.postDelayed({
            resetSticks()
            addLog("CSC finished. Returned sticks to neutral.")
        }, 1500L)
    }

    fun resetSticks() {
        val stickManager = VirtualStickManager.getInstance()
        stickManager.leftStick.horizontalPosition = 0
        stickManager.leftStick.verticalPosition = 0
        stickManager.rightStick.horizontalPosition = 0
        stickManager.rightStick.verticalPosition = 0

        mainHandler.post {
            lastStickValues.value = "Pitch: 0.00  Roll: 0.00  Yaw: 0.00  Throttle: 0.00 (Neutral)"
        }
    }

    // --- MacBridgeServer.Listener Implementations ---

    override fun onServerStarted(ip: String, port: Int) {
        mainHandler.post {
            serverStatus.value = "Running"
            serverIpAndPort.value = "$ip:$port"
        }
    }

    override fun onServerStopped() {
        mainHandler.post {
            serverStatus.value = "Stopped"
            serverIpAndPort.value = "Not running"
            clientCount.value = 0
        }
    }

    override fun onClientConnected(clientIp: String) {
        mainHandler.post {
            clientCount.value = server.getConnectedClientCount()
        }
        addLog("Mac connected from $clientIp")
    }

    override fun onClientDisconnected(clientIp: String) {
        mainHandler.post {
            clientCount.value = server.getConnectedClientCount()
        }
        addLog("Mac disconnected: $clientIp")
        if (server.getConnectedClientCount() == 0) {
            resetSticks()
        }
    }

    override fun onStickCommand(pitch: Float, roll: Float, yaw: Float, throttle: Float) {
        val clampedPitch = max(-1.0f, min(1.0f, pitch))
        val clampedRoll = max(-1.0f, min(1.0f, roll))
        val clampedYaw = max(-1.0f, min(1.0f, yaw))
        val clampedThrottle = max(-1.0f, min(1.0f, throttle))

        val stickManager = VirtualStickManager.getInstance()
        stickManager.rightStick.verticalPosition = (clampedPitch * Stick.MAX_STICK_POSITION_ABS).toInt()
        stickManager.rightStick.horizontalPosition = (clampedRoll * Stick.MAX_STICK_POSITION_ABS).toInt()
        stickManager.leftStick.horizontalPosition = (clampedYaw * Stick.MAX_STICK_POSITION_ABS).toInt()
        stickManager.leftStick.verticalPosition = (clampedThrottle * Stick.MAX_STICK_POSITION_ABS).toInt()

        mainHandler.post {
            lastStickValues.value = String.format(
                "Pitch: %.2f  Roll: %.2f  Yaw: %.2f  Throttle: %.2f",
                clampedPitch, clampedRoll, clampedYaw, clampedThrottle
            )
        }
    }

    override fun onActionCommand(action: String, params: JSONObject) {
        when (action) {
            "takeoff" -> takeOff()
            "land" -> land()
            "enable_virtual_stick" -> enableVirtualStick()
            "disable_virtual_stick" -> disableVirtualStick()
            "emergency" -> resetSticks()
            "arm_motors", "csc" -> armMotorsCSC()
            "start_rtsp" -> {
                val p = params.optInt("port", 8554)
                startRtspStream(p)
            }
            "stop_rtsp" -> stopRtspStream()
            else -> addLog("Unknown action: $action")
        }
    }

    override fun onDeadmanSwitchTriggered() {
        resetSticks()
        addLog("Deadman switch triggered! Sticks set to neutral.")
    }

    override fun onError(message: String) {
        addLog("Error: $message")
    }

    private fun startTelemetryLoop() {
        telemetryTimer?.cancel()
        telemetryTimer = Timer("TelemetryTimer", true).apply {
            scheduleAtFixedRate(object : TimerTask() {
                override fun run() {
                    try {
                        val json = JSONObject().apply {
                            put("type", "telemetry")
                            put("connected", isConnected)
                            put("battery", batteryPercent)
                            put("altitude", altitude)
                            put("heading", compassHeading)
                            put("isFlying", isFlying)
                            put("isMotorsOn", areMotorsOn)
                            put("virtualStickEnabled", isVirtualStickEnabled.value ?: false)
                            put("rtspStreaming", isRtspStreaming.value ?: false)
                            put("rtspUrl", rtspUrl.value ?: "")
                            put("timestamp", System.currentTimeMillis())
                        }
                        server.broadcastTelemetry(json)
                    } catch (e: Exception) {
                        LogUtils.e(tag, "Telemetry error: ${e.message}")
                    }
                }
            }, 0, 100) // 10 Hz
        }
    }

    private fun stopTelemetryLoop() {
        telemetryTimer?.cancel()
        telemetryTimer = null
    }

    private fun initDroneListeners() {
        FlightControllerKey.KeyConnection.create().listen(this) { conn ->
            isConnected = conn ?: false
        }
        FlightControllerKey.KeyAltitude.create().listen(this) { alt ->
            altitude = alt ?: 0.0
        }
        FlightControllerKey.KeyCompassHeading.create().listen(this) { heading ->
            compassHeading = heading ?: 0.0
        }
        FlightControllerKey.KeyAreMotorsOn.create().listen(this) { motors ->
            areMotorsOn = motors ?: false
        }
        FlightControllerKey.KeyIsFlying.create().listen(this) { flying ->
            isFlying = flying ?: false
        }
        BatteryKey.KeyChargeRemainingInPercent.create().listen(this) { pct ->
            batteryPercent = pct ?: 0
        }
    }

    private fun addLog(msg: String) {
        mainHandler.post {
            val list = logMessages.value?.toMutableList() ?: mutableListOf()
            if (list.size > 50) list.removeAt(0)
            list.add(msg)
            logMessages.value = list
        }
        try {
            val json = JSONObject().apply {
                put("type", "log")
                put("message", msg)
                put("timestamp", System.currentTimeMillis())
            }
            server.broadcastTelemetry(json)
        } catch (_: Exception) {}
    }

    override fun onCleared() {
        super.onCleared()
        stopBridge()
        FlightControllerKey.KeyConnection.create().cancelListen(this)
        FlightControllerKey.KeyAltitude.create().cancelListen(this)
        FlightControllerKey.KeyCompassHeading.create().cancelListen(this)
        FlightControllerKey.KeyAreMotorsOn.create().cancelListen(this)
        FlightControllerKey.KeyIsFlying.create().cancelListen(this)
        BatteryKey.KeyChargeRemainingInPercent.create().cancelListen(this)
        VirtualStickManager.getInstance().clearAllVirtualStickStateListener()
        liveStreamManager.removeLiveStreamStatusListener(liveStreamStatusListener)
    }
}
