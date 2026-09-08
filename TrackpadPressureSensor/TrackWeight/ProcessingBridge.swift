//
//  ProcessingBridge.swift
//  TrackWeight
//
//  Direct bridge from TrackWeight Force Touch trackpad sensor to Processing.
//  Simulates an Arduino serial connection over a virtual serial port (PTY).
//

import Foundation
import Darwin
import Combine
import AppKit

@MainActor
final class ProcessingBridge: ObservableObject {
    static let shared = ProcessingBridge()
    
    @Published var portName: String = ""
    @Published var isEnabled: Bool = true
    @Published var currentFsr: Int = 0
    @Published var isTouchActive: Bool = false
    @Published var totalSent: Int = 0
    @Published var isCopied: Bool = false
    
    private var masterFD: Int32 = -1
    private var slaveFD: Int32 = -1
    private var task: Task<Void, Never>?
    private var lastTouchState: Bool = false
    private var pendingTouchPulse: Bool = false
    
    private init() {
        startSerialPort()
        startTransmissionLoop()
    }
    func startSerialPort() {
        var master: Int32 = 0
        var slave: Int32 = 0
        if openpty(&master, &slave, nil, nil, nil) == 0 {
            masterFD = master
            slaveFD = slave
            
            // Set raw mode on slave PTY
            var tty = termios()
            if tcgetattr(slave, &tty) == 0 {
                cfmakeraw(&tty)
                tcsetattr(slave, TCSANOW, &tty)
            }
            
            if let path = ttyname(slave) {
                portName = String(cString: path)
                try? portName.write(toFile: "/tmp/trackpad_pressure_port.txt", atomically: true, encoding: .utf8)
            }
            // Non-blocking writes on masterFD
            let flags = fcntl(masterFD, F_GETFL, 0)
            _ = fcntl(masterFD, F_SETFL, flags | O_NONBLOCK)
            
            // Close slave in parent process so only Processing holds it open
            close(slaveFD)
            slaveFD = -1
            
            // Send initial READY handshake
            sendRaw("READY\n")
        }
    }
    
    func update(weight: Float, hasTouch: Bool) {
        if hasTouch && !lastTouchState {
            pendingTouchPulse = true
        }
        lastTouchState = hasTouch
        isTouchActive = hasTouch
        
        if hasTouch {
            // TrackWeight weight is in grams (0 to 1200g):
            // - Resting finger: ~20 - 50g -> FSR ~20 - 50
            // - Medium press: ~300 - 650g -> FSR ~300 - 650
            // - Heavy force press: up to 1200g -> FSR up to 1200
            currentFsr = Int(min(1200.0, max(0.0, weight)))
        } else {
            // Smooth spring release decay back to 0
            if currentFsr > 0 {
                currentFsr = Int(Float(currentFsr) * 0.72)
                if currentFsr < 5 { currentFsr = 0 }
            }
        }
    }
    
    private func startTransmissionLoop() {
        task?.cancel()
        task = Task { [weak self] in
            while !Task.isCancelled {
                guard let self = self else { break }
                
                if self.isEnabled && self.masterFD >= 0 {
                    if self.pendingTouchPulse {
                        self.sendRaw("TOUCH\n")
                        self.pendingTouchPulse = false
                    }
                    
                    self.sendRaw("\(self.currentFsr)\n")
                    self.totalSent += 1
                }
                
                try? await Task.sleep(nanoseconds: 20_000_000) // 20ms = 50Hz
            }
        }
    }
    
    private func sendRaw(_ msg: String) {
        guard masterFD >= 0 else { return }
        msg.withCString { ptr in
            _ = write(masterFD, ptr, strlen(ptr))
        }
    }
    
    func copyPortToClipboard() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(portName, forType: .string)
        isCopied = true
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            self?.isCopied = false
        }
    }
    
    deinit {
        task?.cancel()
        if masterFD >= 0 { close(masterFD) }
        if slaveFD >= 0 { close(slaveFD) }
    }
}
