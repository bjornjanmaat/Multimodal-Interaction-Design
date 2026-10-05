import React from 'react';
import { Trophy, TrendingUp, Users, LayoutGrid, ListOrdered, RotateCcw } from 'lucide-react';

export default function StatsOverview({
  poll,
  viewMode,
  setViewMode,
  onResetVotes
}) {
  const sortedOptions = [...poll.options].sort((a, b) => b.votes - a.votes);
  const leader = sortedOptions[0];
  const leaderPercentage = poll.totalVotes > 0 
    ? Math.round((leader.votes / poll.totalVotes) * 100) 
    : 0;

  return (
    <section className="stats-hero" aria-label="Poll Statistics and Details">
      <div className="stats-hero-top">
        <div className="hero-header-content">
          <div className="hero-pill-badge">
            <span className="live-bullet" />
            <span>{poll.badge || poll.category}</span>
          </div>
          <h1 className="hero-title">{poll.title}</h1>
          <p className="hero-description">{poll.description}</p>
        </div>

        {/* View mode toggle */}
        <div className="view-mode-toggle" role="group" aria-label="Display style">
          <button
            id="view-grid-btn"
            className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => setViewMode('grid')}
            title="Card Grid View"
          >
            <LayoutGrid size={16} />
            <span>Cards</span>
          </button>
          <button
            id="view-leaderboard-btn"
            className={`toggle-btn ${viewMode === 'leaderboard' ? 'active' : ''}`}
            onClick={() => setViewMode('leaderboard')}
            title="Ranked Leaderboard"
          >
            <ListOrdered size={16} />
            <span>Ranking</span>
          </button>
        </div>
      </div>

      {/* Highlights metrics cards */}
      <div className="metrics-strip">
        <div className="metric-card">
          <div className="metric-icon total">
            <Users size={20} />
          </div>
          <div className="metric-data">
            <span className="metric-label">Total Votes Cast</span>
            <span className="metric-value mono-num">{poll.totalVotes.toLocaleString()}</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon leader">
            <Trophy size={20} />
          </div>
          <div className="metric-data">
            <span className="metric-label">Current Leader</span>
            <div className="leader-preview">
              <span className="leader-name" title={leader?.label}>{leader?.label}</span>
              <span className="leader-lead-percent mono-num" style={{ color: leader?.color }}>
                {leaderPercentage}%
              </span>
            </div>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon trending">
            <TrendingUp size={20} />
          </div>
          <div className="metric-data">
            <span className="metric-label">Options Available</span>
            <span className="metric-value mono-num">{poll.options.length} Choices</span>
          </div>
        </div>

        <div className="metric-action-card">
          <button
            id="reset-poll-votes-btn"
            className="btn-reset"
            onClick={onResetVotes}
            title="Reset votes for this poll"
          >
            <RotateCcw size={15} />
            <span>Reset Poll</span>
          </button>
        </div>
      </div>
    </section>
  );
}
