import React, { useState } from 'react';
import {
  Send,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Bot,
  User,
  Trophy
} from 'lucide-react';
import confetti from 'canvas-confetti';
import { supabase, isConfigured } from './supabaseClient';
import { playVoteSound } from './utils/audio';
import './App.css';

const CHOICES = [
  {
    id: 'machine',
    label: 'Machine',
    subtitle: 'AI Rapper',
    icon: Bot,
    tag: 'Machine'
  },
  {
    id: 'man',
    label: 'Man',
    subtitle: 'Human MC',
    icon: User,
    tag: 'Man'
  }
];

export default function App() {
  const [selectedWinner, setSelectedWinner] = useState(null);
  const [hoverWinner, setHoverWinner] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  const handleSelectWinner = (winnerId) => {
    setSelectedWinner(winnerId);
    setErrorMessage('');
    playVoteSound();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedWinner) {
      setErrorMessage("Please pick either 'machine' or 'man'.");
      return;
    }

    if (!isConfigured || !supabase) {
      setErrorMessage('Supabase is not configured. Please add your credentials to the .env file.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');

    try {
      const { error } = await supabase
        .from('ratings')
        .insert([{ winner: selectedWinner }]);

      if (error) throw error;

      const votedFor = selectedWinner;
      setSubmitSuccess(votedFor);
      playVoteSound();

      try {
        confetti({
          particleCount: 55,
          spread: 65,
          origin: { y: 0.65 },
          colors: votedFor === 'machine' ? ['#0284c7', '#38bdf8', '#0f172a'] : ['#f59e0b', '#fbbf24', '#111827']
        });
      } catch { }
    } catch (err) {
      console.error('Submission failed:', err);
      setErrorMessage(err.message || 'Failed to submit vote to Supabase.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setSelectedWinner(null);
    setSubmitSuccess(null);
    setErrorMessage('');
  };

  const activeWinner = hoverWinner || selectedWinner;
  const activeChoice = CHOICES.find((c) => c.id === activeWinner);

  return (
    <div className="rating-app-container">
      <main className="rating-main">
        {/* Warning if .env is missing */}
        {!isConfigured && (
          <div className="alert-box env-warning" id="env-warning">
            <AlertCircle size={20} />
            <div>
              <strong>Missing .env configuration</strong>
              <p>
                Open <code>vote_app/.env</code> and set your <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code>.
              </p>
            </div>
          </div>
        )}

        <div className="rating-card">
          <div className="badge-header">
            <Trophy size={16} />
            <span>Rap Battle Vote</span>
          </div>

          <h1 className="rating-title">Who Won the Battle?</h1>
          <p className="rating-subtitle">
            Choose who had the best flow and bars: the Machine or the Man.
          </p>

          {/* Feedback Label Banner */}
          <div className="rating-feedback-display">
            {activeChoice ? (
              <div className="feedback-pill">
                <span className="feedback-score">{activeChoice.label}</span>
                <span className="feedback-text">— {activeChoice.subtitle}</span>
              </div>
            ) : (
              <span className="feedback-placeholder">Select a contender below</span>
            )}
          </div>

          {/* Success State or Selection Grid */}
          {submitSuccess !== null ? (
            <div className="vote-success-view">
              <div className="success-icon-wrap">
                <CheckCircle2 size={42} className="success-check-icon" />
              </div>
              <h2 className="success-title">Vote Recorded!</h2>
              <p className="success-desc">
                You voted for <strong>{submitSuccess === 'machine' ? 'Machine' : 'Man'}</strong>. Your vote has been saved to Supabase.
              </p>

              <button
                type="button"
                id="vote-again-btn"
                className="btn-submit btn-secondary-action"
                onClick={handleReset}
              >
                <RefreshCw size={18} />
                <span>Vote Again</span>
              </button>
            </div>
          ) : (
            <>
              {/* Machine or Man Choice Buttons */}
              <div
                className="winner-selection-grid"
                role="radiogroup"
                aria-label="Pick winner: Machine or Man"
              >
                {CHOICES.map((choice) => {
                  const isSelected = selectedWinner === choice.id;
                  const IconComponent = choice.icon;

                  return (
                    <button
                      key={choice.id}
                      id={`winner-btn-${choice.id}`}
                      type="button"
                      className={`winner-card-btn ${isSelected ? 'selected' : ''} ${choice.id}-card`}
                      onClick={() => handleSelectWinner(choice.id)}
                      onMouseEnter={() => setHoverWinner(choice.id)}
                      onMouseLeave={() => setHoverWinner(null)}
                      disabled={isSubmitting}
                      aria-checked={isSelected}
                      role="radio"
                    >
                      <div className="card-top-row">
                        <span className="choice-tag">{choice.tag}</span>
                        {isSelected && <span className="selection-indicator">✓</span>}
                      </div>

                      <div className="card-icon-wrapper">
                        <IconComponent size={38} strokeWidth={1.8} />
                      </div>

                      <span className="choice-label">{choice.label}</span>
                      <span className="choice-subtitle">{choice.subtitle}</span>
                    </button>
                  );
                })}
              </div>

              {/* Error Message */}
              {errorMessage && (
                <div className="alert-box error" id="error-message">
                  <AlertCircle size={18} />
                  <span>{errorMessage}</span>
                </div>
              )}

              {/* Submit Action */}
              <div className="rating-actions">
                <button
                  type="button"
                  id="submit-vote-btn"
                  className="btn-submit"
                  onClick={handleSubmit}
                  disabled={isSubmitting || !selectedWinner}
                >
                  {isSubmitting ? (
                    <>
                      <RefreshCw size={18} className="spinner" />
                      <span>Submitting...</span>
                    </>
                  ) : (
                    <>
                      <Send size={18} />
                      <span>
                        {selectedWinner
                          ? `Vote for ${selectedWinner === 'machine' ? 'Machine' : 'Man'}`
                          : 'Submit Vote'}
                      </span>
                    </>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
