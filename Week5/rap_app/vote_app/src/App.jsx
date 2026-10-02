import React, { useState, useEffect } from 'react';
import { 
  Send, 
  CheckCircle2, 
  AlertCircle, 
  RefreshCw 
} from 'lucide-react';
import confetti from 'canvas-confetti';
import { supabase, isConfigured } from './supabaseClient';
import { playVoteSound } from './utils/audio';
import './App.css';

const RATING_DESCRIPTIONS = {
  1: { label: 'Poor' },
  2: { label: 'Fair' },
  3: { label: 'Average' },
  4: { label: 'Good' },
  5: { label: 'Exceptional!' }
};

export default function App() {
  const [selectedRating, setSelectedRating] = useState(null);
  const [hoverRating, setHoverRating] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [stats, setStats] = useState({ total: 0, average: null });

  // Fetch quick stats from public.ratings if Supabase is connected
  const fetchStats = async () => {
    if (!supabase) return;
    try {
      const { data, error } = await supabase
        .from('ratings')
        .select('rating');

      if (error) throw error;

      if (data && data.length > 0) {
        const total = data.length;
        const sum = data.reduce((acc, curr) => acc + Number(curr.rating || 0), 0);
        const avg = (sum / total).toFixed(1);
        setStats({ total, average: avg });
      } else {
        setStats({ total: 0, average: null });
      }
    } catch (err) {
      console.warn('Could not fetch stats:', err.message);
    }
  };

  useEffect(() => {
    if (isConfigured) {
      fetchStats();
    }
  }, []);

  const handleRatingSelect = (rating) => {
    setSelectedRating(rating);
    setErrorMessage('');
    setSubmitSuccess(null);
    playVoteSound();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedRating) {
      setErrorMessage('Please select a rating between 1 and 5.');
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
        .insert([{ rating: selectedRating }]);

      if (error) throw error;

      setSubmitSuccess(selectedRating);
      playVoteSound();

      try {
        confetti({
          particleCount: 50,
          spread: 60,
          origin: { y: 0.65 },
          colors: ['#111827', '#6b7280', '#9ca3af', '#d1d5db']
        });
      } catch (e) {}

      fetchStats();
    } catch (err) {
      console.error('Submission failed:', err);
      setErrorMessage(err.message || 'Failed to submit rating to Supabase.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setSelectedRating(null);
    setSubmitSuccess(null);
    setErrorMessage('');
  };

  const activeDisplayRating = hoverRating || selectedRating;
  const currentDetails = activeDisplayRating ? RATING_DESCRIPTIONS[activeDisplayRating] : null;

  return (
    <div className="rating-app-container">
      {/* Main Container */}
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
          <h1 className="rating-title">Rate your experience</h1>
          <p className="rating-subtitle">
            Choose a score from 1 to 5 to save directly into the Supabase database.
          </p>

          {/* Feedback Label Banner */}
          <div className="rating-feedback-display">
            {currentDetails ? (
              <div className="feedback-pill">
                <span className="feedback-score mono-num">{activeDisplayRating} / 5</span>
                <span className="feedback-text">— {currentDetails.label}</span>
              </div>
            ) : (
              <span className="feedback-placeholder">Select a score from 1 to 5</span>
            )}
          </div>

          {/* 1 - 5 Rating Buttons */}
          <div className="rating-buttons-grid" role="radiogroup" aria-label="Rating 1 to 5">
            {[1, 2, 3, 4, 5].map((num) => {
              const isSelected = selectedRating === num;

              return (
                <button
                  key={num}
                  id={`rating-btn-${num}`}
                  type="button"
                  className={`rating-number-btn ${isSelected ? 'selected' : ''}`}
                  onClick={() => handleRatingSelect(num)}
                  onMouseEnter={() => setHoverRating(num)}
                  onMouseLeave={() => setHoverRating(null)}
                  disabled={isSubmitting}
                  aria-checked={isSelected}
                  role="radio"
                >
                  <span className="number-label mono-num">{num}</span>
                </button>
              );
            })}
          </div>

          {/* Anchors */}
          <div className="scale-anchors">
            <span>1 (Poor)</span>
            <span>3 (Average)</span>
            <span>5 (Exceptional)</span>
          </div>

          {/* Error Message */}
          {errorMessage && (
            <div className="alert-box error" id="error-message">
              <AlertCircle size={18} />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Success Message Banner */}
          {submitSuccess !== null && (
            <div className="alert-box success" id="success-message">
              <CheckCircle2 size={20} />
              <div>
                <strong>Rating of {submitSuccess}/5 saved!</strong>
                <p>Recorded to Supabase table <code>public.ratings</code>.</p>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="rating-actions">
            {submitSuccess !== null ? (
              <button
                type="button"
                id="rate-again-btn"
                className="btn-submit btn-secondary-action"
                onClick={handleReset}
              >
                <RefreshCw size={18} />
                <span>Submit Another Rating</span>
              </button>
            ) : (
              <button
                type="button"
                id="submit-rating-btn"
                className="btn-submit"
                onClick={handleSubmit}
                disabled={isSubmitting || !selectedRating}
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw size={18} className="spinner" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <>
                    <Send size={18} />
                    <span>Submit Rating</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Aggregate Stats */}
        {isConfigured && stats.total > 0 && (
          <div className="stats-panel">
            <div className="stat-item">
              <span className="stat-num mono-num">{stats.average}</span>
              <span>average</span>
            </div>
            <span className="stat-divider">•</span>
            <div className="stat-item">
              <span className="stat-num mono-num">{stats.total}</span>
              <span>total ratings</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
