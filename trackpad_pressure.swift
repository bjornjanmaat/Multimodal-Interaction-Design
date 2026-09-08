#!/usr/bin/env swift
//
// trackpad_pressure.swift
// Multimodal Interaction Design - Mac Trackpad to Processing Bridge
//
// Simulates an Arduino FSR & Capacitive Touch sensor directly from your Mac's
// Force Touch trackpad. Streams data over a virtual serial port (PTY) in RAW mode
// to Processing with 0ms lag.
//
// Calibrated with a max force of 1200g and dynamic 0-1200 range.
// Uses macOS CFRunLoop to guarantee real-time Multitouch driver event delivery.
//
// Usage:
//   ./trackpad_pressure
//   or: swift trackpad_pressure.swift
//

import Foundation
import Darwin

// MARK: - Configuration
let maxForceLimit: Float = 1200.0 // Max physical Force Touch trackpad pressure in grams
let maxFsrOutput: Int = 1200

// MARK: - State Management
final class BridgeState {
    static let shared = BridgeState()
    
    var numTouches: Int = 0
    var rawPressure: Float = 0.0
    var rawSize: Float = 0.0
    var hadTouches: Bool = false
    var touchTriggered: Bool = false
    var fsrValue: Int = 0
    var smoothedFsr: Int = 0
    
    private var lastLiftTime: TimeInterval = Date().timeIntervalSince1970
    private var lastTouchTriggerTime: TimeInterval = 0
    private let lock = NSLock()
    
    func updateTouch(count: Int, pressure: Float, size: Float) {
        lock.lock()
        defer { lock.unlock() }
        
        let now = Date().timeIntervalSince1970
        numTouches = count
        rawPressure = pressure
        rawSize = size
        
        if count > 0 {
            if !hadTouches {
                hadTouches = true
                // Debounce touch trigger: only trigger if fingers were lifted for >= 350ms
                if (now - lastLiftTime) >= 0.35 && (now - lastTouchTriggerTime) >= 0.8 {
                    touchTriggered = true
                    lastTouchTriggerTime = now
                }
            }
            
            // Map Mac trackpad pressure (up to 1200 grams) to 0 - 1200 range:
            // - Resting finger: ~10 - 40g -> FSR ~10 - 40 (Level 1: street 3D view)
            // - Light to medium press: ~80 - 400g -> FSR ~80 - 400 (Level 2: 2D map)
            // - Firm to heavy press: ~400 - 1200g -> FSR ~400 - 1200 (Level 3: overview map)
            let effectiveForce: Float
            if pressure > 1.0 {
                // Direct grams from Apple MultitouchSupport (0 to 1200g)
                effectiveForce = min(maxForceLimit, max(0.0, pressure))
            } else if pressure > 0.001 {
                // If scaled 0.0 to 1.0+ on certain macOS versions
                effectiveForce = min(maxForceLimit, max(0.0, pressure * maxForceLimit))
            } else if size > 1.2 {
                // Fallback to contact area if pressure sensor is zero
                let areaNorm = min(1.0, max(0.0, (size - 1.2) / 5.0))
                effectiveForce = areaNorm * maxForceLimit
            } else {
                effectiveForce = 0.0
            }
            
            fsrValue = Int(effectiveForce)
        } else {
            if hadTouches {
                lastLiftTime = now
            }
            hadTouches = false
        }
    }
    
    func poll() -> (touchEvent: Bool, fsr: Int, touches: Int, rawP: Float) {
        lock.lock()
        defer { lock.unlock() }
        
        let touchEvent = touchTriggered
        touchTriggered = false
        
        if hadTouches {
            smoothedFsr = fsrValue
        } else {
            // Smooth decay back to 0 on release
            if smoothedFsr > 0 {
                smoothedFsr = Int(Float(smoothedFsr) * 0.72)
                if smoothedFsr < 5 { smoothedFsr = 0 }
            }
        }
        
        return (touchEvent, smoothedFsr, numTouches, rawPressure)
    }
}

// MARK: - Multitouch Framework Binding
let mtHandle = dlopen("/System/Library/PrivateFrameworks/MultitouchSupport.framework/MultitouchSupport", RTLD_NOW)
guard let mtHandle = mtHandle else {
    fputs("❌ Error: Unable to load macOS MultitouchSupport.framework.\n", stderr)
    exit(1)
}

typealias MTDeviceRef = UnsafeMutableRawPointer
typealias MTCallback = @convention(c) (MTDeviceRef, UnsafeRawPointer?, Int32, Double, Int32) -> Int32

let MTDeviceCreateDefault = unsafeBitCast(dlsym(mtHandle, "MTDeviceCreateDefault"), to: (@convention(c) () -> MTDeviceRef?).self)
let MTRegisterContactFrameCallback = unsafeBitCast(dlsym(mtHandle, "MTRegisterContactFrameCallback"), to: (@convention(c) (MTDeviceRef, MTCallback) -> Void).self)
let MTDeviceStart = unsafeBitCast(dlsym(mtHandle, "MTDeviceStart"), to: (@convention(c) (MTDeviceRef, Int32) -> Void).self)
let MTDeviceStop = unsafeBitCast(dlsym(mtHandle, "MTDeviceStop"), to: (@convention(c) (MTDeviceRef, Int32) -> Void).self)

guard let dev = MTDeviceCreateDefault() else {
    fputs("❌ Error: No Multitouch device detected (Force Touch trackpad required).\n", stderr)
    exit(1)
}

// MARK: - Virtual Serial Port (PTY) in RAW Mode
var masterFD: Int32 = 0
var slaveFD: Int32 = 0

if openpty(&masterFD, &slaveFD, nil, nil, nil) != 0 {
    fputs("❌ Error: Could not create virtual serial port (openpty failed).\n", stderr)
    exit(1)
}

// Configure slave PTY in RAW mode (disable ECHO, ICANON, ONLCR for clean byte stream)
var tty = termios()
if tcgetattr(slaveFD, &tty) == 0 {
    cfmakeraw(&tty)
    tcsetattr(slaveFD, TCSANOW, &tty)
}

guard let slavePathC = ttyname(slaveFD) else {
    fputs("❌ Error: Could not resolve slave TTY name.\n", stderr)
    exit(1)
}
let portName = String(cString: slavePathC)

// Auto-discovery: Write active port to /tmp/trackpad_pressure_port.txt so Processing connects automatically
let portFilePath = "/tmp/trackpad_pressure_port.txt"
try? portName.write(toFile: portFilePath, atomically: true, encoding: .utf8)

// Close slaveFD in parent process so only the connecting client holds it open
close(slaveFD)

// Configure non-blocking write on masterFD
let flags = fcntl(masterFD, F_GETFL, 0)
_ = fcntl(masterFD, F_SETFL, flags | O_NONBLOCK)

func sendSerial(_ message: String) {
    message.withCString { ptr in
        _ = write(masterFD, ptr, strlen(ptr))
    }
}

// MARK: - Multitouch Callback
let callback: MTCallback = { _, touchesPtr, numTouches, _, _ in
    if numTouches > 0, let ptr = touchesPtr {
        var maxP: Float = 0.0
        var maxS: Float = 0.0
        for i in 0..<Int(numTouches) {
            let offset = i * 96 // sizeof(MTTouch) = 96 bytes on 64-bit macOS
            let size = ptr.load(fromByteOffset: offset + 48, as: Float.self)
            let pressure = ptr.load(fromByteOffset: offset + 52, as: Float.self)
            if pressure > maxP { maxP = pressure }
            if size > maxS { maxS = size }
        }
        BridgeState.shared.updateTouch(count: Int(numTouches), pressure: maxP, size: maxS)
    } else {
        BridgeState.shared.updateTouch(count: 0, pressure: 0.0, size: 0.0)
    }
    return 0
}

MTRegisterContactFrameCallback(dev, callback)
MTDeviceStart(dev, 0)

// Send initial ready handshake
sendSerial("READY\n")

// Display banner
print(String(repeating: "=", count: 65))
print("🍏  Mac Trackpad Force & Touch -> Processing Serial Bridge")
print("📡  Virtual Serial Port: \u{001B}[1;32m\(portName)\u{001B}[0m")
print("⚡  Calibrated Range: 0 - 1200 (Max Force: 1200g)")
print(String(repeating: "-", count: 65))
print("📋  In your Processing sketch (.pde), use:")
print("    \u{001B}[1;33marduino = new Serial(this, \"\(portName)\", 9600);\u{001B}[0m")
print("    (Note: FSR_TOUCH.pde auto-detects this automatically)")
print(String(repeating: "=", count: 65))
print("Press Ctrl+C to exit.\n")

func renderBar(val: Int, maxVal: Int = 1200, width: Int = 24) -> String {
    let filled = Int((Float(val) / Float(maxVal)) * Float(width))
    let bar = String(repeating: "█", count: max(0, min(width, filled)))
    let empty = String(repeating: "░", count: max(0, width - filled))
    return "[\(bar)\(empty)]"
}

// 50Hz (20ms) transmission timer running on the CFRunLoop
var loopCount = 0
let runLoop = CFRunLoopGetCurrent()

let timer = Timer.scheduledTimer(withTimeInterval: 0.02, repeats: true) { _ in
    let (touchEvent, fsr, touches, rawP) = BridgeState.shared.poll()
    
    // 1. Send TOUCH trigger on touch-down
    if touchEvent {
        sendSerial("TOUCH\n")
    }
    
    // 2. Send continuous FSR reading (0 to 1200)
    sendSerial("\(fsr)\n")
    
    // Update live status line every 3rd iteration (~15Hz for smooth terminal view)
    loopCount += 1
    if loopCount % 3 == 0 {
        let touchStatus = touches > 0 ? "\u{001B}[32m● TOUCH\u{001B}[0m" : "\u{001B}[90m○ IDLE \u{001B}[0m"
        let bar = renderBar(val: fsr, maxVal: maxFsrOutput)
        let line = String(
            format: "\r%@ | FSR: %4d / %4d %@ | Force: %6.1fg | Port: %@   ",
            touchStatus, fsr, maxFsrOutput, bar, rawP, portName
        )
        fputs(line, stdout)
        fflush(stdout)
    }
}

// Clean shutdown signal handling via RunLoop stop
signal(SIGINT) { _ in
    CFRunLoopStop(CFRunLoopGetMain())
}
signal(SIGTERM) { _ in
    CFRunLoopStop(CFRunLoopGetMain())
}

// Run the CFRunLoop: this handles both the Multitouch driver Mach events and the 50Hz timer
CFRunLoopRun()

print("\n\nStopping trackpad listener and closing port...")
timer.invalidate()
MTDeviceStop(dev, 0)
close(masterFD)
try? FileManager.default.removeItem(atPath: portFilePath)
print("Bridge closed.")
