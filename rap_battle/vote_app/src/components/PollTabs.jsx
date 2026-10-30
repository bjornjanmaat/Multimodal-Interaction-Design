import React from 'react';
import { Layers, CheckCircle2 } from 'lucide-react';

export default function PollTabs({ polls, activePollId, onSelectPoll }) {
  return (
    <nav className="poll-tabs-container" id="poll-tabs" aria-label="Poll selection tabs">
      <div className="tabs-header">
        <div className="tabs-title">
          <Layers size={16} />
          <span>Active Topics</span>
        </div>
        <span className="tabs-count">{polls.length} Sessions</span>
      </div>

      <div className="tabs-scroll-area">
        {polls.map((poll) => {
          const isActive = poll.id === activePollId;
          const hasVoted = poll.userVotedOptionId !== null;

          return (
            <button
              key={poll.id}
              id={`tab-${poll.id}`}
              className={`poll-tab-item ${isActive ? 'active' : ''}`}
              onClick={() => onSelectPoll(poll.id)}
            >
              <div className="tab-indicator" />
              <div className="tab-content">
                <div className="tab-meta">
                  <span className="tab-category">{poll.category}</span>
                  {hasVoted && (
                    <span className="tab-voted-badge" title="You have voted on this topic">
                      <CheckCircle2 size={12} />
                      <span>Voted</span>
                    </span>
                  )}
                </div>
                <h2 className="tab-title">{poll.title}</h2>
                <div className="tab-footer">
                  <span className="mono-num">{poll.totalVotes.toLocaleString()} votes cast</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
