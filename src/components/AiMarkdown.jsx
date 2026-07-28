import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './AiMarkdown.css';

export default function AiMarkdown({ content }) {
  if (!content) return null;
  return (
    <div className="ai-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
