import React from 'react';
import './KeyRequiredModal.css';

export default function KeyRequiredModal({ onConfigure, onCancel, message }) {
  return (
    <div className="modal-overlay key-required-overlay">
      <div className="modal-content key-required-modal">
        <div className="modal-icon">
          ⚠️
        </div>
        <h2>API Key Required</h2>
        <p className="modal-message">
          {message || 'You need to configure your Cursor API key to use AI-powered features.'}
        </p>
        <p className="modal-details">
          Your personal API key enables secure access to AI analysis, chat, and other advanced features.
          Keys are encrypted and stored securely.
        </p>
        <div className="modal-actions">
          <button className="btn-primary" onClick={onConfigure}>
            Configure Keys
          </button>
          <button className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
