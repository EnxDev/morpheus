// morpheus-pipeline-tester/types/intent.ts

export type PipelineStatus =
  | "idle"
  | "running"
  | "clarifying"
  | "confirming"
  | "done"
  | "rejected";

export type StepStatus = "pending" | "running" | "success" | "error" | "skipped";

// Domain-agnostic: field names come from the backend, not hardcoded
export type IntentField = string;

export interface Hypothesis {
  value: string | null;
  confidence: number;
}

// Generic intent: any field name → list of hypotheses
export type DynamicIntent = Record<string, Hypothesis[]>;

// Backwards compat alias
export type SupersetIntent = DynamicIntent;

export interface PipelineStep {
  id:          string;
  label:       string;
  status:      StepStatus;
  output?:     unknown;
  error?:      string;
  durationMs?: number;
}

export interface ClarificationRequest {
  field:     IntentField;
  question:  string;
  iteration: number;
}

export interface AuditEvent {
  event:     string;
  timestamp: string;
  data?:     unknown;
}

export interface DecisionResult {
  action:    string;
  score:     number;
  explained: Record<string, number>;
  dryRun:    boolean;
}

export interface PipelineState {
  status:          PipelineStatus;
  steps:           PipelineStep[];
  intent:          DynamicIntent | null;
  lowConfidence:   IntentField[];
  clarifications:  ClarificationRequest[];
  currentClarification: ClarificationRequest | null;
  auditLog:        AuditEvent[];
  decisionResult:  DecisionResult | null;
}

// ── Domain metadata (loaded from backend) ──────────────────────────────────

export interface DomainFieldMeta {
  name:       string;
  label:      string;
  description: string;
  threshold:  number;
  ambiguity_threshold: number;
}

export interface DomainMeta {
  description: string;
  fields:      DomainFieldMeta[];
  capabilities: string[];
}

// ── Default BI field metadata (fallback when backend is not available) ─────

export const DEFAULT_FIELD_META: DomainFieldMeta[] = [
  { name: "measure",     label: "📊 Measure",     description: "the metric being queried",    threshold: 0.90, ambiguity_threshold: 0.15 },
  { name: "time_range",  label: "📅 Time Range",   description: "the time period",             threshold: 0.85, ambiguity_threshold: 0.15 },
  { name: "dimension",   label: "🔎 Dimension",    description: "how data should be grouped",  threshold: 0.80, ambiguity_threshold: 0.12 },
  { name: "filters",     label: "🔍 Filters",      description: "any filtering conditions",    threshold: 0.80, ambiguity_threshold: 0.12 },
  { name: "granularity", label: "🧮 Granularity",   description: "the time granularity",        threshold: 0.70, ambiguity_threshold: 0.10 },
  { name: "comparison",  label: "📈 Comparison",    description: "any comparison reference",    threshold: 0.60, ambiguity_threshold: 0.10 },
];

// Helpers to build lookup maps from domain metadata

export function buildFieldLabels(fields: DomainFieldMeta[]): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const f of fields) {
    labels[f.name] = f.label;
  }
  return labels;
}

export function buildThresholds(fields: DomainFieldMeta[]): Record<string, number> {
  const thresholds: Record<string, number> = {};
  for (const f of fields) {
    thresholds[f.name] = f.threshold;
  }
  return thresholds;
}

// Backwards compat: static constants using defaults
export const FIELD_LABELS: Record<string, string> = buildFieldLabels(DEFAULT_FIELD_META);
export const CONFIDENCE_THRESHOLDS: Record<string, number> = buildThresholds(DEFAULT_FIELD_META);

export const PIPELINE_STEPS_CONFIG: Array<{ id: string; label: string }> = [
  { id: "parse",      label: "Parser" },
  { id: "confidence", label: "Confidence Policy" },
  { id: "validate",   label: "Validator" },
  { id: "clarify",    label: "Clarifier" },
  { id: "confirm",    label: "Confirmation" },
  { id: "decide",     label: "Decision Engine" },
];

export const AUDIT_EVENT_COLORS: Record<string, string> = {
  input_received:           "blue",
  intent_parsed:            "cyan",
  confidence_checked:       "purple",
  clarification_requested:  "orange",
  clarification_resolved:   "geekblue",
  intent_confirmed:         "green",
  intent_rejected:          "red",
  decision_made:            "success",
  execution_started:        "processing",
  step_completed:           "success",
  step_failed:              "error",
  execution_finished:       "success",
};
