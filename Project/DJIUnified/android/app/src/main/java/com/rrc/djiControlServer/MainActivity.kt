package com.rrc.djiControlServer

import android.Manifest
import android.content.Context
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.format.Formatter
import android.util.Log
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Collections

import dji.sdk.keyvalue.key.BatteryKey
import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.GimbalKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.key.DJIKeyInfo
import dji.sdk.keyvalue.key.DJIActionKeyInfo
import dji.sdk.keyvalue.value.common.Attitude
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.sdk.keyvalue.value.common.EmptyMsg
import dji.sdk.keyvalue.value.common.Velocity3D
import dji.sdk.keyvalue.value.flightcontroller.*
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotation
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotationMode
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.common.register.DJISDKInitEvent
import dji.v5.manager.KeyManager
import dji.v5.manager.SDKManager
import dji.v5.manager.aircraft.virtualstick.VirtualStickManager
import dji.v5.manager.interfaces.SDKManagerCallback
import dji.v5.utils.inner.SDKConfig
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.datacenter.livestream.LiveStreamSettings
import dji.v5.manager.datacenter.livestream.LiveStreamType
import dji.v5.manager.datacenter.livestream.settings.RtspSettings

import io.ktor.application.*
import io.ktor.features.*
import io.ktor.gson.*
import io.ktor.http.*
import io.ktor.response.*
import io.ktor.routing.*
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import io.ktor.websocket.*

import kotlinx.coroutines.delay
import java.util.Timer
import java.util.TimerTask
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine
import kotlin.math.min
import kotlin.math.pow

data class CommandCompleted(val completed: Boolean, val errorDescription: String?)

data class DroneState<T>(val state: T)

data class IMUState(
    val velX: Float,
    val velY: Float,
    val velZ: Float,
    val roll: Float,
    val pitch: Float,
    val yaw: Float
)

data class VelocityCommand(
    val velX: Float,
    val velY: Float,
    val velZ: Float,
    val yawRate: Float
)

class DJIControlException(message: String) : Exception(message)

enum class VelocityProfile {
    CONSTANT, TRAPEZOIDAL, S_CURVE
}

enum class Direction {
    FORWARD, BACKWARD, LEFT, RIGHT, UP, DOWN, CLOCKWISE, COUNTER_CLOCKWISE
}

enum class ControlMode {
    POSITION, VELOCITY
}

class MainActivity : AppCompatActivity() {

    companion object {
        private const val PORT: Int = 8080
        private const val TAG = "DJIControlServer"
        private val REQUIRED_PERMISSIONS: Array<String> = arrayOf(
            Manifest.permission.VIBRATE,
            Manifest.permission.INTERNET,
            Manifest.permission.ACCESS_WIFI_STATE,
            Manifest.permission.WAKE_LOCK,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_NETWORK_STATE,
            Manifest.permission.CHANGE_WIFI_STATE,
            Manifest.permission.BLUETOOTH,
            Manifest.permission.BLUETOOTH_ADMIN,
        )
    }

    private lateinit var ipText: TextView
    private lateinit var regText: TextView
    private lateinit var droneNameText: TextView
    private lateinit var batteryText: TextView
    private lateinit var rtspText: TextView

    private val RTSP_PORT = 8554
    private val RTSP_USER = "admin"
    private val RTSP_PASS = "123456"
    private var isRtspStreaming = false

    private val mainHandler = Handler(Looper.getMainLooper())

    // Drone Telemetry & Status
    private var isConnected = false
    private var altitude = 0.0
    private var compassHeading = 0.0
    private var batteryPercent = 0
    private var roll = 0f
    private var pitch = 0f
    private var yaw = 0f
    private var velX = 0f
    private var velY = 0f
    private var velZ = 0f
    private var landingProtectionEnabled = true

    // IMU State Collection
    private val imuStates = mutableListOf<IMUState>()
    private var imuTimer: Timer? = null

    // Control Configuration
    private var controlMode = ControlMode.POSITION
    private var maxSpeed = 0.5f // 50 cm/s
    private var maxAngularSpeed = 30.0f // 30 deg/s
    private var maxAcceleration = 0.2f // 20 cm/s^2
    private var maxAngularAcceleration = 15.0f // 15 deg/s^2
    private var maxJerk = 0.2f
    private var maxAngularJerk = 30.0f
    private var flightCommandInterval = 40L // 40 ms = 25 Hz
    private var velocityProfile: VelocityProfile = VelocityProfile.CONSTANT

    // Velocity Control Mode States
    private var velocityModeXVel = 0f
    private var velocityModeYVel = 0f
    private var velocityModeZVel = 0f
    private var velocityModeYawVel = 0f
    private var followingVelocityCommands = false
    private var velocityControlRunnable: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        ipText = findViewById(R.id.ipText)
        regText = findViewById(R.id.regText)
        droneNameText = findViewById(R.id.droneNameText)
        batteryText = findViewById(R.id.batteryText)
        rtspText = findViewById(R.id.rtspText)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            ActivityCompat.requestPermissions(this, REQUIRED_PERMISSIONS, 1)
        }

        displayIP()
        startServer()
        initMSDKV5()
    }

    override fun onDestroy() {
        super.onDestroy()
        stopCollectingIMU()
        stopVelocityControlLoop()
    }

    // --- Embedded Ktor Server ---

    private fun getDeviceIpAddress(): String {
        try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            // Prefer wlan or ap interfaces
            for (intf in interfaces) {
                if (intf.name.contains("wlan") || intf.name.contains("ap")) {
                    for (addr in Collections.list(intf.inetAddresses)) {
                        if (!addr.isLoopbackAddress && addr is Inet4Address) {
                            return addr.hostAddress ?: ""
                        }
                    }
                }
            }
            // Fallback to any non-loopback IPv4 address
            for (intf in interfaces) {
                for (addr in Collections.list(intf.inetAddresses)) {
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        return addr.hostAddress ?: ""
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error resolving IP address", e)
        }
        return "127.0.0.1"
    }

    private fun displayIP() {
        val ipString = getDeviceIpAddress()
        ipText.text = getString(R.string.ip_format, ipString, PORT)
        updateRtspUI()
    }

    private fun updateRtspUI() {
        if (isRtspStreaming) {
            val ip = getDeviceIpAddress()
            val url = "rtsp://$RTSP_USER:$RTSP_PASS@$ip:$RTSP_PORT/streaming/live/1"
            rtspText.text = getString(R.string.rtsp_streaming, url)
        } else {
            rtspText.text = getString(R.string.rtsp_stopped)
        }
    }

    // --- RTSP Live Video Streaming ---

    private fun startLiveStream(port: Int = RTSP_PORT, username: String = RTSP_USER, pass: String = RTSP_PASS, callback: ((Boolean, String?) -> Unit)? = null) {
        val liveStreamManager = MediaDataCenter.getInstance().liveStreamManager
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
                isRtspStreaming = true
                val ip = getDeviceIpAddress()
                val url = "rtsp://$username:$pass@$ip:$port/streaming/live/1"
                Log.i(TAG, "RTSP Live Stream started successfully: $url")
                runOnUiThread { updateRtspUI() }
                callback?.invoke(true, url)
            }

            override fun onFailure(error: IDJIError) {
                isRtspStreaming = false
                val msg = "RTSP Start Failed: ${error.description()} (${error.errorCode()})"
                Log.e(TAG, msg)
                runOnUiThread { updateRtspUI() }
                callback?.invoke(false, msg)
            }
        })
    }

    private fun stopLiveStream(callback: ((Boolean, String?) -> Unit)? = null) {
        val liveStreamManager = MediaDataCenter.getInstance().liveStreamManager
        liveStreamManager.stopStream(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                isRtspStreaming = false
                Log.i(TAG, "RTSP Live Stream stopped")
                runOnUiThread { updateRtspUI() }
                callback?.invoke(true, null)
            }

            override fun onFailure(error: IDJIError) {
                val msg = "RTSP Stop Failed: ${error.description()} (${error.errorCode()})"
                Log.e(TAG, msg)
                callback?.invoke(false, msg)
            }
        })
    }

    private fun startServer() {
        embeddedServer(Netty, port = PORT, host = "0.0.0.0") {
            install(WebSockets)
            install(CallLogging)
            install(ContentNegotiation) {
                gson {}
            }
            routing {
                meta()
                getState()
                setState()
                cameraControl()
                liveStreamControl()
                takeoffAndLandControl()
                velocityControl()
                throttleControl()
                yawControl()
                rollPitchControl()
            }
        }.start(wait = false)
        Log.i(TAG, "Embedded Ktor Server started on port $PORT on 0.0.0.0")
    }

    // --- DJI Mobile SDK V5 Initialization & Listeners ---

    private fun initMSDKV5() {
        regText.text = getString(R.string.registering)

        SDKManager.getInstance().init(this, object : SDKManagerCallback {
            override fun onRegisterSuccess() {
                runOnUiThread {
                    val ver = SDKConfig.getInstance().registrationSDKVersion
                    regText.text = getString(R.string.registered, ver)
                }
                Log.i(TAG, "DJI MSDK V5 Registered successfully!")
                setupTelemetryListeners()
            }

            override fun onRegisterFailure(error: IDJIError) {
                runOnUiThread {
                    regText.text = getString(R.string.register_failed)
                    showToast("SDK Register Failed: ${error.description()}")
                }
                Log.e(TAG, "DJI MSDK V5 Register failed: ${error.description()} (${error.errorCode()})")
            }

            override fun onProductConnect(productId: Int) {
                runOnUiThread { updateDroneConnectionUI(true) }
                startLiveStream()
            }

            override fun onProductDisconnect(productId: Int) {
                runOnUiThread { updateDroneConnectionUI(false) }
                stopLiveStream()
            }

            override fun onProductChanged(productId: Int) {
                runOnUiThread { updateDroneConnectionUI(true) }
            }

            override fun onInitProcess(event: DJISDKInitEvent, totalProcess: Int) {
                if (event == DJISDKInitEvent.INITIALIZE_COMPLETE) {
                    SDKManager.getInstance().registerApp()
                }
            }

            override fun onDatabaseDownloadProgress(current: Long, total: Long) {}
        })
    }

    private fun setupTelemetryListeners() {
        KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyConnection), this) { _, conn ->
            isConnected = conn ?: false
            runOnUiThread { updateDroneConnectionUI(isConnected) }
        }

        KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAltitude), this) { _, alt ->
            altitude = alt ?: 0.0
        }

        KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyCompassHeading), this) { _, hdg ->
            compassHeading = hdg ?: 0.0
        }

        KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAircraftAttitude), this) { _, att ->
            att?.let {
                pitch = it.pitch.toFloat()
                roll = it.roll.toFloat()
                yaw = it.yaw.toFloat()
            }
        }

        KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyAircraftVelocity), this) { _, vel ->
            vel?.let {
                velX = it.x.toFloat()
                velY = it.y.toFloat()
                velZ = it.z.toFloat()
            }
        }

        KeyManager.getInstance().listen(KeyTools.createKey(BatteryKey.KeyChargeRemainingInPercent), this) { _, pct ->
            batteryPercent = pct ?: 0
            runOnUiThread {
                batteryText.text = getString(R.string.battery_percentage, batteryPercent, "%")
            }
        }
    }

    private fun updateDroneConnectionUI(connected: Boolean) {
        if (connected) {
            droneNameText.text = "DJI Drone Connected"
            batteryText.text = getString(R.string.battery_percentage, batteryPercent, "%")
        } else {
            droneNameText.text = getString(R.string.drone_disconnected)
            batteryText.text = ""
        }
    }

    // --- KeyManager Generic Helpers ---

    private suspend fun performAction(keyInfo: DJIActionKeyInfo<EmptyMsg, EmptyMsg>): IDJIError? =
        suspendCoroutine { cont ->
            KeyManager.getInstance().performAction(
                KeyTools.createKey(keyInfo),
                object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                    override fun onSuccess(t: EmptyMsg?) { cont.resume(null) }
                    override fun onFailure(error: IDJIError) { cont.resume(error) }
                }
            )
        }

    private suspend fun <T> setValue(keyInfo: DJIKeyInfo<T>, value: T): IDJIError? =
        suspendCoroutine { cont ->
            KeyManager.getInstance().setValue(
                KeyTools.createKey(keyInfo),
                value,
                object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { cont.resume(null) }
                    override fun onFailure(error: IDJIError) { cont.resume(error) }
                }
            )
        }

    private fun <T> getValue(keyInfo: DJIKeyInfo<T>): T? =
        KeyManager.getInstance().getValue(KeyTools.createKey(keyInfo))

    // --- Server Routes ---

    private fun Route.meta() {
        get("/") {
            call.respondText(text = "Connected", contentType = ContentType.Text.Plain)
        }

        get("/reboot") {
            try {
                val err = performAction(FlightControllerKey.KeyRebootDevice)
                call.respond(CommandCompleted(err == null, err?.description()))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/startCollectingIMUState/{interval}") {
            try {
                val interval = call.parameters["interval"]?.toLongOrNull() ?: 1000L
                startCollectingIMU(interval)
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/stopCollectingIMUState") {
            try {
                stopCollectingIMU()
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/getCurrentIMUState") {
            val currState = IMUState(velX, velY, velZ, roll, pitch, yaw)
            call.respond(DroneState(currState))
        }

        get("/getCollectedIMUStates") {
            call.respond(DroneState(imuStates))
        }

        get("/clearCollectedIMUStates") {
            imuStates.clear()
            call.respond(CommandCompleted(true, null))
        }
    }

    private fun Route.getState() {
        get("/getAltitude") {
            call.respond(DroneState(altitude))
        }

        get("/getHeading") {
            call.respond(DroneState(compassHeading))
        }

        get("/getControlMode") {
            call.respond(DroneState(controlMode.name))
        }

        get("/getMaxSpeed") {
            call.respond(DroneState(maxSpeed))
        }

        get("/getMaxAngularSpeed") {
            call.respond(DroneState(maxAngularSpeed))
        }

        get("/getVelocityProfile") {
            call.respond(DroneState(velocityProfile.name))
        }

        get("/isLandingProtectionEnabled") {
            call.respond(DroneState(landingProtectionEnabled))
        }
    }

    private fun Route.setState() {
        get("/setControlMode/{mode}") {
            try {
                val modeStr = call.parameters["mode"]!!.uppercase()
                controlMode = ControlMode.valueOf(modeStr)
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, "Invalid Control Mode: ${e.message}"))
            }
        }

        get("/setMaxSpeed/{speed}") {
            try {
                val spd = call.parameters["speed"]!!.toFloat()
                if (spd <= 0) throw NumberFormatException("Speed must be positive")
                maxSpeed = spd
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/setMaxAngularSpeed/{speed}") {
            try {
                val spd = call.parameters["speed"]!!.toFloat()
                if (spd <= 0) throw NumberFormatException("Angular speed must be positive")
                maxAngularSpeed = spd
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/setVelocityProfile/{profile}") {
            try {
                val prof = call.parameters["profile"]!!.uppercase()
                velocityProfile = VelocityProfile.valueOf(prof)
                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, "Invalid Velocity Profile: ${e.message}"))
            }
        }

        get("/enableLandingProtection") {
            landingProtectionEnabled = true
            call.respond(CommandCompleted(true, null))
        }

        get("/disableLandingProtection") {
            landingProtectionEnabled = false
            call.respond(CommandCompleted(true, null))
        }
    }

    private fun Route.liveStreamControl() {
        get("/startLiveStream") {
            try {
                val result = suspendCoroutine<Pair<Boolean, String?>> { cont ->
                    startLiveStream { success, res ->
                        cont.resume(Pair(success, res))
                    }
                }
                call.respond(CommandCompleted(result.first, result.second))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/stopLiveStream") {
            try {
                val result = suspendCoroutine<Pair<Boolean, String?>> { cont ->
                    stopLiveStream { success, err ->
                        cont.resume(Pair(success, err))
                    }
                }
                call.respond(CommandCompleted(result.first, result.second))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/getLiveStreamUrl") {
            val ip = getDeviceIpAddress()
            val url = "rtsp://$RTSP_USER:$RTSP_PASS@$ip:$RTSP_PORT/streaming/live/1"
            call.respond(DroneState(mapOf(
                "streaming" to isRtspStreaming,
                "url" to url,
                "ip" to ip,
                "port" to RTSP_PORT
            )))
        }
    }

    private fun Route.takeoffAndLandControl() {
        get("/takeoff") {
            // In MSDK V5, auto-takeoff requires Virtual Stick to be disabled first
            suspendCoroutine<Unit> { cont ->
                VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { cont.resume(Unit) }
                    override fun onFailure(error: IDJIError) { cont.resume(Unit) }
                })
            }

            delay(200)

            val takeoffError = performAction(FlightControllerKey.KeyStartTakeoff)
            call.respond(CommandCompleted(takeoffError == null, takeoffError?.description()))
        }

        get("/land") {
            val landError = performAction(FlightControllerKey.KeyStartAutoLanding)
            call.respond(CommandCompleted(landError == null, landError?.description()))
        }

        get("/confirmLanding") {
            val confirmError = performAction(FlightControllerKey.KeyConfirmLanding)
            call.respond(CommandCompleted(confirmError == null, confirmError?.description()))
        }
    }

    private fun Route.velocityControl() {
        get("/startVelocityControl") {
            try {
                if (controlMode == ControlMode.POSITION) {
                    throw DJIControlException("Cannot use VELOCITY command in POSITION control mode")
                }

                enableVirtualStickSync()
                VirtualStickManager.getInstance().setVirtualStickAdvancedModeEnabled(true)

                followingVelocityCommands = true
                startVelocityControlLoop()

                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/setVelocityCommand/{xVel}/{yVel}/{zVel}/{yawVel}") {
            try {
                if (controlMode == ControlMode.POSITION) {
                    throw DJIControlException("Cannot use VELOCITY command in POSITION control mode")
                }
                if (!followingVelocityCommands) {
                    throw DJIControlException("Cannot set velocity commands before starting Velocity Control")
                }

                velocityModeXVel = call.parameters["xVel"]!!.toFloat()
                velocityModeYVel = call.parameters["yVel"]!!.toFloat()
                velocityModeZVel = call.parameters["zVel"]!!.toFloat()
                velocityModeYawVel = call.parameters["yawVel"]!!.toFloat()

                call.respond(CommandCompleted(true, null))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/stopVelocityControl") {
            stopVelocityControlLoop()
            disableVirtualStickSync()
            call.respond(CommandCompleted(true, null))
        }

        get("/getCurrentVelocityCommand") {
            call.respond(DroneState(VelocityCommand(velocityModeXVel, velocityModeYVel, velocityModeZVel, velocityModeYawVel)))
        }
    }

    private fun startVelocityControlLoop() {
        stopVelocityControlLoop()
        velocityControlRunnable = object : Runnable {
            override fun run() {
                if (followingVelocityCommands) {
                    sendVelocityParam(velocityModeXVel, velocityModeYVel, velocityModeZVel, velocityModeYawVel)
                    mainHandler.postDelayed(this, flightCommandInterval)
                }
            }
        }
        mainHandler.postDelayed(velocityControlRunnable as Runnable, flightCommandInterval)
    }

    private fun stopVelocityControlLoop() {
        followingVelocityCommands = false
        velocityModeXVel = 0f
        velocityModeYVel = 0f
        velocityModeZVel = 0f
        velocityModeYawVel = 0f
        velocityControlRunnable?.let { mainHandler.removeCallbacks(it) }
        velocityControlRunnable = null
        sendVelocityParam(0f, 0f, 0f, 0f)
    }

    private fun sendVelocityParam(vx: Float, vy: Float, vz: Float, yawRate: Float) {
        val param = VirtualStickFlightControlParam().apply {
            rollPitchCoordinateSystem = FlightCoordinateSystem.BODY
            verticalControlMode = VerticalControlMode.VELOCITY
            yawControlMode = YawControlMode.ANGULAR_VELOCITY
            rollPitchControlMode = RollPitchControlMode.VELOCITY
            pitch = vx.toDouble()
            roll = vy.toDouble()
            verticalThrottle = vz.toDouble()
            yaw = yawRate.toDouble()
        }
        VirtualStickManager.getInstance().sendVirtualStickAdvancedParam(param)
    }

    // --- Positional Movement Routes (6DOF) ---

    private fun Route.throttleControl() {
        get("/moveUp/{dist}") {
            handlePositionMove(call, Direction.UP)
        }
        get("/moveDown/{dist}") {
            handlePositionMove(call, Direction.DOWN)
        }
    }

    private fun Route.yawControl() {
        get("/rotateClockwise/{angle}") {
            handlePositionMove(call, Direction.CLOCKWISE)
        }
        get("/rotateCounterClockwise/{angle}") {
            handlePositionMove(call, Direction.COUNTER_CLOCKWISE)
        }
    }

    private fun Route.rollPitchControl() {
        get("/moveForward/{dist}") {
            handlePositionMove(call, Direction.FORWARD)
        }
        get("/moveBackward/{dist}") {
            handlePositionMove(call, Direction.BACKWARD)
        }
        get("/moveLeft/{dist}") {
            handlePositionMove(call, Direction.LEFT)
        }
        get("/moveRight/{dist}") {
            handlePositionMove(call, Direction.RIGHT)
        }
    }

    private suspend fun handlePositionMove(call: ApplicationCall, direction: Direction) {
        val paramKey = if (direction == Direction.CLOCKWISE || direction == Direction.COUNTER_CLOCKWISE) "angle" else "dist"
        val rawVal = call.parameters[paramKey]
        if (rawVal == null) {
            call.respond(CommandCompleted(false, "Missing $paramKey value"))
            return
        }
        try {
            if (controlMode == ControlMode.VELOCITY) {
                throw DJIControlException("Cannot use POSITION command in VELOCITY control mode")
            }
            val distanceOrAngle = getNumVal(rawVal)

            enableVirtualStickSync()
            VirtualStickManager.getInstance().setVirtualStickAdvancedModeEnabled(true)

            createMotionPlanAndExecute(distanceOrAngle, direction)

            sendVelocityParam(0f, 0f, 0f, 0f)
            call.respond(CommandCompleted(true, null))
        } catch (e: Exception) {
            call.respond(CommandCompleted(false, e.message))
        }
    }

    // --- Motion Planning Implementation ---

    private suspend fun createMotionPlanAndExecute(dist: Float, direction: Direction) {
        val commands = when (velocityProfile) {
            VelocityProfile.CONSTANT -> generateConstantVelocityProfile(dist, direction)
            VelocityProfile.TRAPEZOIDAL -> generateTrapezoidalVelocityProfile(dist, direction)
            VelocityProfile.S_CURVE -> generateSCurveVelocityProfile(dist, direction)
        }
        for (cmd in commands) {
            sendVelocityParam(cmd.vx, cmd.vy, cmd.vz, cmd.yawRate)
            delay(flightCommandInterval)
        }
    }

    data class VelocityStep(val vx: Float, val vy: Float, val vz: Float, val yawRate: Float)

    private fun generateVelocitiesFromFunction(v: (Float) -> Float, tTotal: Float, direction: Direction): List<VelocityStep> {
        val tSteps = arange(0f, tTotal, flightCommandInterval / 1000f)
        val steps = mutableListOf<VelocityStep>()

        for (t in tSteps) {
            val speed = v(t)
            val step = when (direction) {
                Direction.FORWARD -> VelocityStep(speed, 0f, 0f, 0f)
                Direction.BACKWARD -> VelocityStep(-speed, 0f, 0f, 0f)
                Direction.RIGHT -> VelocityStep(0f, speed, 0f, 0f)
                Direction.LEFT -> VelocityStep(0f, -speed, 0f, 0f)
                Direction.UP -> VelocityStep(0f, 0f, speed, 0f)
                Direction.DOWN -> VelocityStep(0f, 0f, -speed, 0f)
                Direction.CLOCKWISE -> VelocityStep(0f, 0f, 0f, speed)
                Direction.COUNTER_CLOCKWISE -> VelocityStep(0f, 0f, 0f, -speed)
            }
            steps.add(step)
        }
        steps.add(VelocityStep(0f, 0f, 0f, 0f))
        return steps
    }

    private fun generateConstantVelocityProfile(D: Float, direction: Direction): List<VelocityStep> {
        val isRot = direction == Direction.CLOCKWISE || direction == Direction.COUNTER_CLOCKWISE
        val v = if (isRot) maxAngularSpeed else maxSpeed
        val tTotal = D / v
        return generateVelocitiesFromFunction({ v }, tTotal, direction)
    }

    private fun generateTrapezoidalVelocityProfile(D: Float, direction: Direction): List<VelocityStep> {
        val isRot = direction == Direction.CLOCKWISE || direction == Direction.COUNTER_CLOCKWISE
        val a = if (isRot) maxAngularAcceleration else maxAcceleration
        val vMax = min(D / 2, if (isRot) maxAngularSpeed else maxSpeed)

        val tp1 = vMax / a
        val tp2 = (a * D - vMax.pow(2)) / (a * vMax)
        val tp3 = vMax / a
        val tTotal = tp1 + tp2 + tp3

        val vFn = fun(t: Float): Float {
            return when {
                t <= tp1 -> a * t
                t <= tp1 + tp2 -> vMax
                else -> vMax - a * (t - tp1 - tp2)
            }
        }
        return generateVelocitiesFromFunction(vFn, tTotal, direction)
    }

    private fun generateSCurveVelocityProfile(D: Float, direction: Direction): List<VelocityStep> {
        val isRot = direction == Direction.CLOCKWISE || direction == Direction.COUNTER_CLOCKWISE
        val j = if (isRot) maxAngularJerk else maxJerk
        val vMax = min(D / 2, if (isRot) maxAngularSpeed else maxSpeed)
        val aMax = min(0.75f * vMax, if (isRot) maxAngularAcceleration else maxAcceleration)

        val vf1 = aMax.pow(2) / (2 * j)
        val vf2 = vMax - aMax.pow(2) / (2 * j)
        val vf3 = vMax
        val vf4 = vMax
        val vf5 = vMax - aMax.pow(2) / (2 * j)
        val vf6 = aMax.pow(2) / (2 * j)

        val tp1 = aMax / j
        val tp2 = (vf2 - vf1) / aMax
        val tp3 = aMax / j
        val tp4 = ((aMax * j * D) - (vMax * aMax.pow(2)) - (j * vMax.pow(2))) / (j * aMax * vMax)
        val tp5 = aMax / j
        val tp6 = (vf5 - vf6) / aMax
        val tp7 = aMax / j
        val tTotal = tp1 + tp2 + tp3 + tp4 + tp5 + tp6 + tp7

        val vFn = fun(t: Float): Float {
            return when {
                t <= tp1 -> j * t.pow(2) / 2
                t <= tp1 + tp2 -> vf1 + (aMax * (t - tp1))
                t <= tp1 + tp2 + tp3 -> {
                    val tc = t - tp1 - tp2
                    vf2 + aMax * tc - (j * tc.pow(2)) / 2
                }
                t <= tp1 + tp2 + tp3 + tp4 -> vf3
                t <= tp1 + tp2 + tp3 + tp4 + tp5 -> {
                    val tc = t - tp1 - tp2 - tp3 - tp4
                    vf4 - (j * tc.pow(2)) / 2
                }
                t <= tp1 + tp2 + tp3 + tp4 + tp5 + tp6 -> {
                    val tc = t - tp1 - tp2 - tp3 - tp4 - tp5
                    vf5 - aMax * tc
                }
                else -> {
                    val tc = t - tp1 - tp2 - tp3 - tp4 - tp5 - tp6
                    vf6 - aMax * tc + (j * tc.pow(2)) / 2
                }
            }
        }
        return generateVelocitiesFromFunction(vFn, tTotal, direction)
    }

    // --- Camera & Gimbal Routes ---

    private fun Route.cameraControl() {
        get("/captureShot") {
            try {
                val err = suspendCoroutine<IDJIError?> { cont ->
                    KeyManager.getInstance().performAction(
                        KeyTools.createKey(CameraKey.KeyStartShootPhoto, ComponentIndexType.LEFT_OR_MAIN),
                        object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                            override fun onSuccess(t: EmptyMsg?) { cont.resume(null) }
                            override fun onFailure(error: IDJIError) { cont.resume(error) }
                        }
                    )
                }
                call.respond(CommandCompleted(err == null, err?.description()))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/startVideoRecording") {
            try {
                val err = suspendCoroutine<IDJIError?> { cont ->
                    KeyManager.getInstance().performAction(
                        KeyTools.createKey(CameraKey.KeyStartRecord, ComponentIndexType.LEFT_OR_MAIN),
                        object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                            override fun onSuccess(t: EmptyMsg?) { cont.resume(null) }
                            override fun onFailure(error: IDJIError) { cont.resume(error) }
                        }
                    )
                }
                call.respond(CommandCompleted(err == null, err?.description()))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/stopVideoRecording") {
            try {
                val err = suspendCoroutine<IDJIError?> { cont ->
                    KeyManager.getInstance().performAction(
                        KeyTools.createKey(CameraKey.KeyStopRecord, ComponentIndexType.LEFT_OR_MAIN),
                        object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                            override fun onSuccess(t: EmptyMsg?) { cont.resume(null) }
                            override fun onFailure(error: IDJIError) { cont.resume(error) }
                        }
                    )
                }
                call.respond(CommandCompleted(err == null, err?.description()))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }

        get("/pitchGimbal/{angle}") {
            try {
                val angle = call.parameters["angle"]!!.toDouble()
                val rotation = GimbalAngleRotation().apply {
                    mode = GimbalAngleRotationMode.ABSOLUTE_ANGLE
                    pitch = angle
                }
                val err = suspendCoroutine<IDJIError?> { cont ->
                    KeyManager.getInstance().performAction(
                        KeyTools.createKey(GimbalKey.KeyRotateByAngle, ComponentIndexType.LEFT_OR_MAIN),
                        rotation,
                        object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                            override fun onSuccess(t: EmptyMsg?) { cont.resume(null) }
                            override fun onFailure(error: IDJIError) { cont.resume(error) }
                        }
                    )
                }
                call.respond(CommandCompleted(err == null, err?.description()))
            } catch (e: Exception) {
                call.respond(CommandCompleted(false, e.message))
            }
        }
    }

    // --- Helper & Utility Methods ---

    private suspend fun enableVirtualStickSync() {
        suspendCoroutine<Unit> { cont ->
            VirtualStickManager.getInstance().enableVirtualStick(object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() { cont.resume(Unit) }
                override fun onFailure(error: IDJIError) { cont.resume(Unit) }
            })
        }
    }

    private suspend fun disableVirtualStickSync() {
        suspendCoroutine<Unit> { cont ->
            VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
                override fun onSuccess() { cont.resume(Unit) }
                override fun onFailure(error: IDJIError) { cont.resume(Unit) }
            })
        }
    }

    private fun startCollectingIMU(interval: Long) {
        stopCollectingIMU()
        imuTimer = Timer("IMU_Collector", true).apply {
            scheduleAtFixedRate(object : TimerTask() {
                override fun run() {
                    imuStates.add(IMUState(velX, velY, velZ, roll, pitch, yaw))
                }
            }, 0, interval)
        }
    }

    private fun stopCollectingIMU() {
        imuTimer?.cancel()
        imuTimer = null
    }

    private fun getNumVal(numStr: String): Float {
        val num = numStr.toFloat()
        if (num <= 0) throw NumberFormatException("Non-Positive Float not allowed: $num")
        return num
    }

    private fun arange(start: Float, stop: Float, step: Float): List<Float> {
        val a = mutableListOf<Float>()
        var i = start
        while (i < stop) {
            a.add(i)
            i += step
        }
        return a
    }

    private fun showToast(msg: String) {
        mainHandler.post {
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        }
    }
}