import React, { useState } from 'react';
import { X, Plus, Trash2, CheckCircle2 } from 'lucide-react';

const PRESET_COLORS = [
  '#6366f1', // Indigo
  '#06b6d4', // Cyan
  '#10b981', // Emerald
  '#f43f5e', // Rose
  '#f59e0b', // Amber
  '#a855f7'  // Purple
];

const PRESET_ICONS = ['Sparkles', 'Mic', 'Zap', 'Globe', 'Activity', 'ShieldCheck', 'Radio'];

export default function CreatePollModal({ isOpen, onClose, onCreatePoll }) {
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('');
  const [description, setDescription] = useState('');
  const [options, setOptions] = useState([
    { label: '', description: '', color: PRESET_COLORS[0], icon: PRESET_ICONS[0] },
    { label: '', description: '', color: PRESET_COLORS[1], icon: PRESET_ICONS[1] }
  ]);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleAddOption = () => {
    if (options.length >= 6) {
      setError('Maximum 6 options allowed.');
      return;
    }
    const nextColor = PRESET_COLORS[options.length % PRESET_COLORS.length];
    const nextIcon = PRESET_ICONS[options.length % PRESET_ICONS.length];
    setOptions([...options, { label: '', description: '', color: nextColor, icon: nextIcon }]);
  };

  const handleRemoveOption = (index) => {
    if (options.length <= 2) {
      setError('A poll must have at least 2 options.');
      return;
    }
    setOptions(options.filter((_, i) => i !== index));
  };

  const handleOptionChange = (index, field, value) => {
    const updated = [...options];
    updated[index][field] = value;
    setOptions(updated);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError('');

    if (!title.trim()) {
      setError('Please provide a poll title or question.');
      return;
    }

    const validOptions = options.filter((opt) => opt.label.trim().length > 0);
    if (validOptions.length < 2) {
      setError('Please enter labels for at least 2 options.');
      return;
    }

    const newPoll = {
      id: `poll-${Date.now()}`,
      title: title.trim(),
      category: category.trim() || 'General Interaction',
      badge: 'CUSTOM POLL',
      description: description.trim() || 'Community casted interaction vote.',
      totalVotes: 0,
      userVotedOptionId: null,
      options: validOptions.map((opt, index) => ({
        id: `opt-${Date.now()}-${index}`,
        label: opt.label.trim(),
        description: opt.description.trim(),
        votes: 0,
        color: opt.color,
        icon: opt.icon,
        tag: `Option ${index + 1}`
      }))
    };

    onCreatePoll(newPoll);
    onClose();
  };

  return (
    <div className="modal-overlay" onClick={onClose} id="create-poll-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 className="modal-title">Create New Poll</h2>
            <p className="modal-subtitle">Design a custom multimodal interaction voting question</p>
          </div>
          <button className="btn-close" onClick={onClose} aria-label="Close dialog">
            <X size={20} />
          </button>
        </div>

        {error && <div className="modal-error-banner">{error}</div>}

        <form onSubmit={handleSubmit} className="modal-form">
          <div className="form-group">
            <label htmlFor="poll-title-input" className="form-label">Poll Question / Title *</label>
            <input
              id="poll-title-input"
              type="text"
              className="form-input"
              placeholder="e.g. Which sound feedback feels best for confirmation?"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>

          <div className="form-row">
            <div className="form-group flex-1">
              <label htmlFor="poll-category-input" className="form-label">Category</label>
              <input
                id="poll-category-input"
                type="text"
                className="form-input"
                placeholder="e.g. Voice Modality"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="poll-desc-input" className="form-label">Description (Optional)</label>
            <textarea
              id="poll-desc-input"
              rows={2}
              className="form-textarea"
              placeholder="Provide background context or instructions..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="form-group">
            <div className="options-header-row">
              <label className="form-label">Voting Options (Minimum 2)</label>
              <button
                type="button"
                className="btn-add-option"
                onClick={handleAddOption}
                disabled={options.length >= 6}
              >
                <Plus size={14} />
                <span>Add Choice</span>
              </button>
            </div>

            <div className="options-inputs-list">
              {options.map((opt, idx) => (
                <div key={idx} className="option-input-item">
                  <div className="option-color-picker-wrap">
                    <input
                      type="color"
                      value={opt.color}
                      onChange={(e) => handleOptionChange(idx, 'color', e.target.value)}
                      className="color-dot-input"
                      title="Choose highlight color"
                    />
                  </div>
                  <div className="option-text-fields">
                    <input
                      type="text"
                      className="form-input option-title-input"
                      placeholder={`Option ${idx + 1} Title *`}
                      value={opt.label}
                      onChange={(e) => handleOptionChange(idx, 'label', e.target.value)}
                      required
                    />
                    <input
                      type="text"
                      className="form-input option-sub-input"
                      placeholder="Short description or technical note..."
                      value={opt.description}
                      onChange={(e) => handleOptionChange(idx, 'description', e.target.value)}
                    />
                  </div>
                  {options.length > 2 && (
                    <button
                      type="button"
                      className="btn-remove-opt"
                      onClick={() => handleRemoveOption(idx)}
                      title="Delete option"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" id="submit-poll-btn">
              <CheckCircle2 size={16} />
              <span>Launch Poll</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
