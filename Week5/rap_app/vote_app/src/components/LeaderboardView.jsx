import React from 'react';
import { Award, Check, ChevronRight } from 'lucide-react';
import confetti from 'canvas-confetti';

export default function LeaderboardView({
  options,
  totalVotes,
  userVotedOptionId,
  onVote
}) {
  const sorted = [...options].sort((a, b) => b.votes - a.votes);

  const handleVote = (e, option) => {
    const rect = e.currentTarget.getBoundingClientRect();
    try {
      const x = (rect.left + rect.width / 2) / window.innerWidth;
      const y = (rect.top + rect.height / 2) / window.innerHeight;
      confetti({
        particleCount: 25,
        spread: 45,
        origin: { x, y },
        colors: [option.color, '#ffffff']
      });
    } catch (err) {}
    onVote(option.id);
  };

  return (
    <div className="leaderboard-container" id="leaderboard-view">
      <div className="leaderboard-list">
        {sorted.map((option, index) => {
          const rank = index + 1;
          const percentage = totalVotes > 0 
            ? Math.round((option.votes / totalVotes) * 100) 
            : 0;
          const isVoted = userVotedOptionId === option.id;

          return (
            <div
              key={option.id}
              className={`leaderboard-row ${isVoted ? 'voted' : ''} ${rank === 1 ? 'gold-rank' : ''}`}
              style={{ '--row-color': option.color }}
            >
              <div className="rank-indicator">
                {rank === 1 ? (
                  <span className="rank-badge gold" title="1st Place Leader">
                    <Award size={16} /> 1
                  </span>
                ) : (
                  <span className="rank-badge default">#{rank}</span>
                )}
              </div>

              <div className="row-content">
                <div className="row-header">
                  <div className="row-titles">
                    <h3 className="row-label">{option.label}</h3>
                    {option.tag && <span className="option-badge">{option.tag}</span>}
                  </div>
                  <div className="row-stats">
                    <span className="row-votes mono-num">
                      <strong>{option.votes.toLocaleString()}</strong> votes
                    </span>
                    <span className="row-percentage mono-num" style={{ color: option.color }}>
                      {percentage}%
                    </span>
                  </div>
                </div>

                <div className="row-progress-track">
                  <div
                    className="row-progress-fill"
                    style={{
                      width: `${percentage}%`,
                      backgroundColor: option.color,
                      boxShadow: `0 0 12px ${option.color}55`
                    }}
                  />
                </div>
              </div>

              <div className="row-action">
                <button
                  className={`btn-vote-compact ${isVoted ? 'voted' : ''}`}
                  onClick={(e) => handleVote(e, option)}
                  style={{
                    borderColor: isVoted ? option.color : undefined,
                    backgroundColor: isVoted ? `${option.color}25` : undefined
                  }}
                >
                  {isVoted ? (
                    <>
                      <Check size={14} />
                      <span>Voted</span>
                    </>
                  ) : (
                    <>
                      <span>Vote</span>
                      <ChevronRight size={14} />
                    </>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
