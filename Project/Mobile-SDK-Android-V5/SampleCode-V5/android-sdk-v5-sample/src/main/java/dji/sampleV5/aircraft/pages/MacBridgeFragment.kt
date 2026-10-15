package dji.sampleV5.aircraft.pages

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.activityViewModels
import dji.sampleV5.aircraft.databinding.FragMacBridgePageBinding
import dji.sampleV5.aircraft.macbridge.MacBridgeVM

/**
 * Fragment UI for starting and monitoring the Mac Controller & RTSP Video Bridge.
 */
class MacBridgeFragment : DJIFragment() {

    private var _binding: FragMacBridgePageBinding? = null
    private val binding get() = _binding!!

    private val macBridgeVM: MacBridgeVM by activityViewModels()

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragMacBridgePageBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        initViews()
        initObservers()
    }

    @SuppressLint("SetTextI18n")
    private fun initViews() {
        binding.btnToggleBridge.setOnClickListener {
            if (macBridgeVM.serverStatus.value == "Running") {
                macBridgeVM.stopBridge()
            } else {
                macBridgeVM.startBridge()
            }
        }

        binding.btnToggleVirtualStick.setOnClickListener {
            if (macBridgeVM.isVirtualStickEnabled.value == true) {
                macBridgeVM.disableVirtualStick()
            } else {
                macBridgeVM.enableVirtualStick()
            }
        }

        binding.btnTakeoff.setOnClickListener {
            macBridgeVM.takeOff()
        }

        binding.btnLanding.setOnClickListener {
            macBridgeVM.land()
        }

        binding.btnEmergencyStop.setOnClickListener {
            macBridgeVM.resetSticks()
        }

        binding.btnToggleRtsp.setOnClickListener {
            if (macBridgeVM.isRtspStreaming.value == true) {
                macBridgeVM.stopRtspStream()
            } else {
                macBridgeVM.startRtspStream()
            }
        }
    }

    @SuppressLint("SetTextI18n")
    private fun initObservers() {
        macBridgeVM.serverStatus.observe(viewLifecycleOwner) { status ->
            binding.tvServerStatus.text = "Server Status: $status"
            if (status == "Running") {
                binding.btnToggleBridge.text = "Stop Mac Bridge"
                binding.btnToggleBridge.setBackgroundColor(0xFFFF3B30.toInt())
            } else {
                binding.btnToggleBridge.text = "Start Mac Bridge"
                binding.btnToggleBridge.setBackgroundColor(0xFF007AFF.toInt())
            }
        }

        macBridgeVM.serverIpAndPort.observe(viewLifecycleOwner) { addr ->
            binding.tvServerAddress.text = "Control Address: $addr (TCP port 9090)"
        }

        macBridgeVM.clientCount.observe(viewLifecycleOwner) { count ->
            binding.tvConnectedClients.text = "Connected Macs: $count"
        }

        macBridgeVM.rtspUrl.observe(viewLifecycleOwner) { url ->
            binding.tvRtspUrl.text = if (url.isNullOrEmpty()) "RTSP URL: Not active" else "RTSP URL: $url"
        }

        macBridgeVM.isRtspStreaming.observe(viewLifecycleOwner) { streaming ->
            binding.btnToggleRtsp.text = if (streaming) "Stop RTSP Stream" else "Start RTSP Stream"
        }

        macBridgeVM.isVirtualStickEnabled.observe(viewLifecycleOwner) { enabled ->
            binding.tvVirtualStickStatus.text = "Virtual Stick Authority: " + if (enabled) "ENABLED" else "Disabled"
            binding.btnToggleVirtualStick.text = if (enabled) "Disable Virtual Stick" else "Enable Virtual Stick"
        }

        macBridgeVM.lastStickValues.observe(viewLifecycleOwner) { values ->
            binding.tvLastStickInputs.text = values
        }

        macBridgeVM.logMessages.observe(viewLifecycleOwner) { logs ->
            binding.tvBridgeLogs.text = logs.joinToString("\n")
            binding.scrollLogs.post {
                binding.scrollLogs.fullScroll(View.FOCUS_DOWN)
            }
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
