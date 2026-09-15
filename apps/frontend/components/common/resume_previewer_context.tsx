'use client';

import React, { createContext, useContext, useState, ReactNode } from 'react';
import type { ResumeDocument } from '@/lib/types/document';
import type { DocumentDiff } from '@/lib/api/diff';

export interface ATSSubScores {
  keyword_match: number;
  skills_coverage: number;
  section_completeness: number;
}

export interface ATSScore {
  overall_score: number;
  sub_scores: ATSSubScores;
  missing_keywords: string[];
  injectable_keywords: string[];
  recommendations: string[];
}

export interface InterviewPrepQuestion {
  question: string;
  focus_area?: string | null;
  suggested_answer_points: string[];
}

export interface InterviewPrepSkillGap {
  skill: string;
  why_it_matters: string;
  preparation_suggestion: string;
}

export interface InterviewPrepData {
  role_fit_analysis: string[];
  resume_questions: InterviewPrepQuestion[];
  project_follow_ups: InterviewPrepQuestion[];
  skill_gaps: InterviewPrepSkillGap[];
  talking_points: string[];
}

export interface Data {
  request_id: string;
  preview_id?: string | null;
  preview_expires_at?: string | null;
  resume_id: string | null;
  job_id: string;
  resume_preview: ResumeDocument;
  details?: string;
  commentary?: string;
  improvements?: {
    suggestion: string;
    lineNumber?: string | number;
  }[];
  original_resume_markdown?: string;
  updated_resume_markdown?: string;
  job_description?: string;
  job_keywords?: string;
  cover_letter?: string;
  outreach_message?: string;
  interview_prep?: InterviewPrepData | null;
  /** Structured comparison of the source resume against this proposal. */
  diff?: DocumentDiff | null;
  ats_score?: ATSScore;
}

export interface ImprovedResult {
  data: Data;
}

interface ContextValue {
  improvedData: ImprovedResult | null;
  setImprovedData: (data: ImprovedResult) => void;
}

const ResumePreviewContext = createContext<ContextValue | undefined>(undefined);

export function ResumePreviewProvider({ children }: { children: ReactNode }) {
  const [improvedData, setImprovedData] = useState<ImprovedResult | null>(null);
  return (
    <ResumePreviewContext.Provider value={{ improvedData, setImprovedData }}>
      {children}
    </ResumePreviewContext.Provider>
  );
}

export function useResumePreview(): ContextValue {
  const ctx = useContext(ResumePreviewContext);
  if (!ctx) throw new Error('useResumePreview must be used within ResumePreviewProvider');
  return ctx;
}
