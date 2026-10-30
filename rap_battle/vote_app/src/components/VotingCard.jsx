import React, { useState } from 'react';
import { 
  Mic, 
  Sparkles, 
  Globe, 
  Radio, 
  Zap, 
  Volume2, 
  Activity, 
  ShieldCheck, 
  Sliders, 
  Eye, 
  Check, 
  Star,
  Award,
  ChevronRight
} from 'lucide-react';
import confetti from 'canvas-confetti';

const ICON_MAP = {
  Mic,
  Sparkles,
  Globe,
  Radio,
  Zap,
  Volume2,
  Activity,
  ShieldCheck,
  Sliders,
  Eye,
  Star,
  Award
};

export default function VotingCard({
  option,
  totalVotes,
  isVoted,
  isLeader,
  onVote,
  soundEnabled
}) {
  const [ripples, setRipples] = useState([]);
  const percentage = totalVotes > 0 ? Math.round((option.votes / totalVotes) * 100) : 0;
  
  const IconComponent = ICON_MAP[option.icon] || Star;

  const handleVoteClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    
    // Add floating particle animation
    const newRippleId = Date.now();
    setRipples((prev) => [...prev, newRippleId]);
    setTimeout(() => {
      setRipples((prev) => prev.filter((id) => id !== newRippleId));
    }, 1000);

    // Confetti burst from button position
    try {
      const x = (rect.left + rect.width / 2) / window.innerWidth;
      const y = (rect.top + rect.height / 2) / window.innerHeight;
      confetti({
        particleCount: 35,
        spread: 55,
        origin: { x, y },
        colors: [option.color, '#ffffff', '#6366f1'],
        disableForReducedMotion: true,
        ticks: 120
      });
    } catch (err) {
      // fallback safe
    }

    onVote(option.id);
  };

  return (
    <div
      id={`voting-card-${option.id}`}
      className={`voting-card ${isVoted ? 'voted' : ''} ${isLeader ? 'is-leader' : ''}`}
      style={{
        '--option-color': option.color,
      }}
    >
      {/* Floating "+1" animation items */}
      {ripples.map((id) => (
        <span key={id} className="floating-plus-one" style={{ color: option.color }}>
          +1 VOTE!
        </span>
      ))}

      {/* Card Header */}
      <div className="card-top">
        <div className="card-icon-title">
          <div
            className="option-icon-box"
            style={{
              backgroundColor: `${option.color}22`,
              color: option.color,
              borderColor: `${option.color}44`
            }}
          >
            <IconComponent size={22} />
          </div>
          <div>
            <div className="card-tag-row">
              {option.tag && <span className="option-badge">{option.tag}</span>}
              {isLeader && (
                <span className="leader-badge">
                  <Award size={12} />
                  <span>Leader</span>
                </span>
              )}
            </div>
            <h3 className="option-label">{option.label}</h3>
          </div>
        </div>
      </div>

      {/* Description */}
      {option.description && (
        <p className="option-description">{option.description}</p>
      )}

      {/* Percentage Progress Bar */}
      <div className="progress-section">
        <div className="progress-labels">
          <span className="mono-stat votes-count">
            <strong>{option.votes.toLocaleString()}</strong> votes
          </span>
          <span className="mono-stat percent-label" style={{ color: option.color }}>
            {percentage}%
          </span>
        </div>
        
        <div className="progress-bar-track">
          <div
            className="progress-bar-fill"
            style={{
              width: `${percentage}%`,
              backgroundColor: option.color,
              boxShadow: `0 0 15px ${option.color}66`
            }}
          />
        </div>
      </div>

      {/* Card Footer / Action */}
      <div className="card-footer">
        <button
          id={`btn-vote-${option.id}`}
          className={`btn-vote ${isVoted ? 'btn-voted' : ''}`}
          onClick={handleVoteClick}
          style={{
            borderColor: isVoted ? option.color : undefined,
            backgroundColor: isVoted ? `${option.color}25` : undefined
          }}
        >
          {isVoted ? (
            <>
              <Check size={16} className="voted-icon" />
              <span>Voted (Click to re-cast)</span>
            </>
          ) : (
            <>
              <span>Vote for this</span>
              <ChevronRight size={16} />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
