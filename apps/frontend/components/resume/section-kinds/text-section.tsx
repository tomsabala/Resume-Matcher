import React from 'react';
import type { Section } from '@/lib/types/document';
import baseStyles from '../styles/_base.module.css';

/** `text` sections render a single justified paragraph (summary, objective, ...). */
export const TextSection: React.FC<{ section: Section }> = ({ section }) => {
  const text = section.text.trim();
  if (!text) return null;

  return <p className={`text-justify ${baseStyles['resume-text']}`}>{text}</p>;
};
