import React from 'react';
import { Vote, Volume2, VolumeX, Radio, Plus, Activity } from 'lucide-react';

export default function Header({
  soundEnabled,
  setSoundEnabled,
  simulationActive,
  setSimulationActive,
  openCreateModal,
  onlineUsers
}) {
  return (
    <header className="app-header" id="app-header">
      <div className="header-container">
        {/* Brand */}
        <div className="brand-group">
          <div className="brand-icon-wrapper">
            <Vote className="brand-icon" size={24} />
            <div className="brand-pulse"></div>
          </div>
          <div>
            <div className="brand-title-row">
              <span className="brand-name">VoxVote</span>
              <span className="brand-pill">LIVE MODALITY</span>
            </div>
            <p className="brand-subtitle">Interactive Real-Time Decision Hub</p>
          </div>
        </div>

        {/* Live Status and Actions */}
        <div className="header-actions">
          {/* Active users status indicator */}
          <div className="status-pill" title="Connected to local reactive event stream">
            <span className="pulse-dot"></span>
            <span className="status-text">
              <strong className="mono-num">{onlineUsers}</strong> active peers
            </span>
          </div>

          {/* Simulation Toggle */}
          <button
            id="simulation-toggle-btn"
            className={`btn-action ${simulationActive ? 'active-sim' : ''}`}
            onClick={() => setSimulationActive(!simulationActive)}
            title={simulationActive ? "Pause simulated live votes" : "Start simulated live network votes"}
          >
            <Radio size={16} className={simulationActive ? "icon-spin" : ""} />
            <span>{simulationActive ? "Simulating Live" : "Live Simulation"}</span>
          </button>

          {/* Audio Toggle */}
          <button
            id="sound-toggle-btn"
            className={`btn-icon ${soundEnabled ? 'active' : ''}`}
            onClick={() => setSoundEnabled(!soundEnabled)}
            title={soundEnabled ? "Tactile audio feedback on" : "Tactile audio feedback muted"}
            aria-label="Toggle tactile sound"
          >
            {soundEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>

          {/* Create Poll Button */}
          <button
            id="create-poll-btn"
            className="btn-primary"
            onClick={openCreateModal}
          >
            <Plus size={18} />
            <span>New Poll</span>
          </button>
        </div>
      </div>
    </header>
  );
}
