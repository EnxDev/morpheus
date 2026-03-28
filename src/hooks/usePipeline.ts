// src/hooks/usePipeline.ts

import { useReducer, useCallback, useRef, useState } from "react";
import type {
  PipelineState,
  PipelineStep,
  AuditEvent,
  SupersetIntent,
  IntentField,
  DecisionResult,
} from "@/types/intent";
import {
  PIPELINE_STEPS_CONFIG,
  CONFIDENCE_THRESHOLDS,
} from "@/types/intent";
import {
  delay,
  selectMockIntent,
  MOCK_DECISION_RESULT,
  MOCK_CLARIFICATION_QUESTIONS,
} from "@/mocks/pipeline";

// ─── API Helpers ──────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8000";

async function apiFetch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const text = await response.text();
    let message = `${response.status}: ${text}`;
    try {
      const json = JSON.parse(text);
      if (json.detail) message = json.detail;
    } catch { /* use raw text */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

interface ParseApiResponse {
  intent: Record<string, unknown>;
  low_confidence: IntentField[];
  valid: boolean;
  errors: string[];
}

interface ClarifyApiResponse {
  intent: Record<string, unknown>;
  low_confidence: IntentField[];
}

interface DecideApiResponse {
  action: string | null;
  score: number;
  explained: Record<string, number>;
  audit_log: unknown[];
}

function apiIntentToFrontend(raw: Record<string, unknown>): SupersetIntent {
  const result: SupersetIntent = {};
  for (const field of Object.keys(raw)) {
    const hyps = raw[field] as Array<{ value: string | null; confidence: number }> | undefined;
    result[field] = hyps ?? [{ value: null, confidence: 0 }];
  }
  return result;
}

// ─── Initial State ────────────────────────────────────────────────────────────

const buildInitialSteps = (): PipelineStep[] =>
  PIPELINE_STEPS_CONFIG.map((s) => ({
    id:     s.id,
    label:  s.label,
    status: "pending",
  }));

const INITIAL_STATE: PipelineState = {
  status:               "idle",
  steps:                buildInitialSteps(),
  intent:               null,
  lowConfidence:        [],
  clarifications:       [],
  currentClarification: null,
  auditLog:             [],
  decisionResult:       null,
};

// ─── Action Types ─────────────────────────────────────────────────────────────

type Action =
  | { type: "RESET" }
  | { type: "PIPELINE_STOPPED" }
  | { type: "PIPELINE_STARTED" }
  | { type: "STEP_RUNNING"; id: string }
  | { type: "STEP_SUCCESS"; id: string; output?: unknown; durationMs: number }
  | { type: "STEP_ERROR"; id: string; error: string }
  | { type: "INTENT_PARSED"; intent: SupersetIntent }
  | { type: "LOW_CONFIDENCE_FOUND"; fields: IntentField[] }
  | { type: "CLARIFICATION_STARTED"; field: IntentField; question: string; iteration: number }
  | { type: "CLARIFICATION_ANSWERED"; field: IntentField; updatedIntent: SupersetIntent }
  | { type: "CONFIRMING"; }
  | { type: "CONFIRMED" }
  | { type: "REJECTED" }
  | { type: "DECISION_MADE"; result: DecisionResult }
  | { type: "AUDIT"; event: string; data?: unknown };

// ─── Reducer ──────────────────────────────────────────────────────────────────

function pipelineReducer(state: PipelineState, action: Action): PipelineState {
  console.log(`[reducer] ${action.type}`, "status:", state.status, "→", action);

  const addAudit = (event: string, data?: unknown): AuditEvent => ({
    event,
    timestamp: new Date().toISOString(),
    data,
  });

  const updateStep = (id: string, patch: Partial<PipelineStep>): PipelineStep[] =>
    state.steps.map((s) => (s.id === id ? { ...s, ...patch } : s));

  switch (action.type) {
    case "RESET":
      return { ...INITIAL_STATE, steps: buildInitialSteps() };

    case "PIPELINE_STOPPED":
      return {
        ...state,
        status: "idle",
        currentClarification: null,
        steps: state.steps.map((s) =>
          s.status === "running" ? { ...s, status: "skipped" as const } : s
        ),
        auditLog: [...state.auditLog, addAudit("pipeline_stopped")],
      };

    case "PIPELINE_STARTED":
      return {
        ...state,
        status:  "running",
        auditLog: [...state.auditLog, addAudit("input_received")],
      };

    case "STEP_RUNNING":
      return { ...state, steps: updateStep(action.id, { status: "running" }) };

    case "STEP_SUCCESS":
      return {
        ...state,
        steps: updateStep(action.id, {
          status:     "success",
          output:     action.output,
          durationMs: action.durationMs,
        }),
      };

    case "STEP_ERROR":
      return {
        ...state,
        steps: updateStep(action.id, { status: "error", error: action.error }),
        auditLog: [...state.auditLog, addAudit("step_failed", { error: action.error })],
      };

    case "INTENT_PARSED":
      return {
        ...state,
        intent:  action.intent,
        auditLog: [...state.auditLog, addAudit("intent_parsed", action.intent)],
      };

    case "LOW_CONFIDENCE_FOUND":
      return {
        ...state,
        lowConfidence: action.fields,
        auditLog: [...state.auditLog, addAudit("confidence_checked", { low: action.fields })],
      };

    case "CLARIFICATION_STARTED":
      return {
        ...state,
        status: "clarifying",
        currentClarification: {
          field:     action.field,
          question:  action.question,
          iteration: action.iteration,
        },
        clarifications: [
          ...state.clarifications,
          { field: action.field, question: action.question, iteration: action.iteration },
        ],
        auditLog: [...state.auditLog, addAudit("clarification_requested", { field: action.field })],
      };

    case "CLARIFICATION_ANSWERED":
      return {
        ...state,
        intent:  action.updatedIntent,
        currentClarification: null,
        auditLog: [...state.auditLog, addAudit("clarification_resolved", { field: action.field })],
      };

    case "CONFIRMING":
      return {
        ...state,
        status: "confirming",
        steps:  updateStep("confirm", { status: "running" }),
      };

    case "CONFIRMED":
      return {
        ...state,
        status: "running",
        lowConfidence: [],
        currentClarification: null,
        steps:  updateStep("confirm", { status: "success", durationMs: 0 }),
        auditLog: [...state.auditLog, addAudit("intent_confirmed")],
      };

    case "REJECTED":
      return {
        ...state,
        status: "rejected",
        steps:  updateStep("confirm", { status: "error", error: "Rejected by user" }),
        auditLog: [...state.auditLog, addAudit("intent_rejected")],
      };

    case "DECISION_MADE":
      return {
        ...state,
        status:         "done",
        decisionResult: action.result,
        auditLog: [...state.auditLog, addAudit("decision_made", action.result)],
      };

    case "AUDIT":
      return {
        ...state,
        auditLog: [...state.auditLog, addAudit(action.event, action.data)],
      };

    default:
      return state;
  }
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

const MAX_ITERATIONS = 3;

export interface UsePipelineReturn {
  state:               PipelineState;
  submitQuery:         (query: string) => Promise<void>;
  stopPipeline:        () => void;
  answerClarification: (answer: string) => void;
  confirmIntent:       () => void;
  rejectIntent:        () => void;
  reset:               () => void;
  domain:              string | null;
  setDomain:           (domain: string | null) => void;
}

export function usePipeline(useMocks = true): UsePipelineReturn {
  const [state, dispatch] = useReducer(pipelineReducer, INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);
  const [domain, setDomain] = useState<string | null>(null);

  const runStep = useCallback(async (
    id: string,
    fn: () => Promise<unknown>,
  ): Promise<unknown> => {
    const start = Date.now();
    dispatch({ type: "STEP_RUNNING", id });
    try {
      const output = await fn();
      dispatch({ type: "STEP_SUCCESS", id, output, durationMs: Date.now() - start });
      return output;
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      dispatch({ type: "STEP_ERROR", id, error });
      throw err;
    }
  }, []);

  const stopPipeline = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    dispatch({ type: "PIPELINE_STOPPED" });
  }, []);

  const submitQuery = useCallback(async (query: string) => {
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const signal = controller.signal;

    dispatch({ type: "PIPELINE_STARTED" });

    if (useMocks) {
      // ─── Mock path ──────────────────────────────────────────────────────
      const intent = await runStep("parse", async () => {
        await delay(800);
        return selectMockIntent(query);
      }) as SupersetIntent;
      if (signal.aborted) return;

      dispatch({ type: "INTENT_PARSED", intent });

      await runStep("confidence", async () => {
        await delay(300);
        const low = (Object.keys(CONFIDENCE_THRESHOLDS) as IntentField[]).filter((field) => {
          const hyp = intent[field][0];
          return !hyp || (hyp.confidence < CONFIDENCE_THRESHOLDS[field]);
        });
        dispatch({ type: "LOW_CONFIDENCE_FOUND", fields: low });
        return { lowConfidence: low };
      });
      if (signal.aborted) return;

      await runStep("validate", async () => {
        await delay(200);
        return { valid: true };
      });
      if (signal.aborted) return;

      dispatch({ type: "STEP_RUNNING", id: "clarify" });
      const lowFields = (Object.keys(CONFIDENCE_THRESHOLDS) as IntentField[]).filter((field) => {
        const hyp = intent[field][0];
        return !hyp || (hyp.confidence < CONFIDENCE_THRESHOLDS[field]);
      });

      if (lowFields.length === 0) {
        dispatch({ type: "STEP_SUCCESS", id: "clarify", durationMs: 0, output: { skipped: true } });
        dispatch({ type: "CONFIRMING" });
      } else {
        const firstField = lowFields[0] as IntentField;
        dispatch({
          type:      "CLARIFICATION_STARTED",
          field:     firstField,
          question:  MOCK_CLARIFICATION_QUESTIONS[firstField] ?? `Specifica: ${firstField}`,
          iteration: 1,
        });
      }
    } else {
      // ─── Real API path ──────────────────────────────────────────────────
      try {
        const data = await runStep("parse", async () => {
          return apiFetch<ParseApiResponse>("/api/parse", { query, domain });
        }) as ParseApiResponse;

        const intent = apiIntentToFrontend(data.intent);
        dispatch({ type: "INTENT_PARSED", intent });

        await runStep("confidence", async () => {
          return { lowConfidence: data.low_confidence };
        });
        dispatch({ type: "LOW_CONFIDENCE_FOUND", fields: data.low_confidence });

        await runStep("validate", async () => {
          return { valid: data.valid, errors: data.errors };
        });

        dispatch({ type: "STEP_RUNNING", id: "clarify" });
        if (data.low_confidence.length === 0) {
          dispatch({ type: "STEP_SUCCESS", id: "clarify", durationMs: 0, output: { skipped: true } });
          dispatch({ type: "CONFIRMING" });
        } else {
          const firstField = data.low_confidence[0] as IntentField;
          dispatch({
            type:      "CLARIFICATION_STARTED",
            field:     firstField,
            question:  MOCK_CLARIFICATION_QUESTIONS[firstField] ?? `Please specify: ${firstField}`,
            iteration: 1,
          });
        }
      } catch (err) {
        const error = err instanceof Error ? err.message : "Network error";
        dispatch({ type: "STEP_ERROR", id: "parse", error });
      }
    }
  }, [runStep, useMocks, domain]);

  const answerClarification = useCallback(async (answer: string) => {
    if (!state.intent || !state.currentClarification) return;

    const { field, iteration } = state.currentClarification;

    if (useMocks) {
      const updatedIntent: SupersetIntent = {
        ...state.intent,
        [field]: [{ value: answer, confidence: 0.95 }],
      };
      dispatch({ type: "CLARIFICATION_ANSWERED", field, updatedIntent });

      const remaining = state.lowConfidence.filter((f) => f !== field);
      if (remaining.length === 0 || iteration >= MAX_ITERATIONS) {
        dispatch({ type: "STEP_SUCCESS", id: "clarify", durationMs: 0 });
        dispatch({ type: "CONFIRMING" });
      } else {
        const nextField = remaining[0] as IntentField;
        dispatch({
          type:      "CLARIFICATION_STARTED",
          field:     nextField,
          question:  MOCK_CLARIFICATION_QUESTIONS[nextField] ?? `Specifica: ${nextField}`,
          iteration: iteration + 1,
        });
      }
    } else {
      try {
        const intentDict: Record<string, unknown> = { ...state.intent };

        const data = await apiFetch<ClarifyApiResponse>("/api/clarify", {
          intent: intentDict,
          field,
          answer,
          domain,
        });

        const updatedIntent = apiIntentToFrontend(data.intent);
        dispatch({ type: "CLARIFICATION_ANSWERED", field, updatedIntent });

        const remaining = data.low_confidence;
        if (remaining.length === 0 || iteration >= MAX_ITERATIONS) {
          dispatch({ type: "STEP_SUCCESS", id: "clarify", durationMs: 0 });
          dispatch({ type: "CONFIRMING" });
        } else {
          const nextField = remaining[0] as IntentField;
          dispatch({
            type:      "CLARIFICATION_STARTED",
            field:     nextField,
            question:  MOCK_CLARIFICATION_QUESTIONS[nextField] ?? `Please specify: ${nextField}`,
            iteration: iteration + 1,
          });
        }
      } catch (err) {
        const error = err instanceof Error ? err.message : "Network error";
        dispatch({ type: "STEP_ERROR", id: "clarify", error });
      }
    }
  }, [state.intent, state.currentClarification, state.lowConfidence, useMocks, domain]);

  const confirmIntent = useCallback(async () => {
    console.log("[confirmIntent] called, domain:", domain, "useMocks:", useMocks);
    console.log("[confirmIntent] state.intent:", JSON.stringify(state.intent));
    dispatch({ type: "CONFIRMED" });

    if (useMocks) {
      await runStep("decide", async () => {
        await delay(600);
        dispatch({ type: "DECISION_MADE", result: MOCK_DECISION_RESULT });
        return MOCK_DECISION_RESULT;
      });
    } else {
      try {
        const intentDict: Record<string, unknown> = state.intent ? { ...state.intent } : {};
        console.log("[confirmIntent] POST /api/decide body:", JSON.stringify({ intent: intentDict, domain }));

        const data = await runStep("decide", async () => {
          return apiFetch<DecideApiResponse>("/api/decide", { intent: intentDict, domain });
        }) as DecideApiResponse;

        console.log("[confirmIntent] /api/decide response:", JSON.stringify(data));
        const result: DecisionResult = {
          action:    data.action ?? "none",
          score:     data.score,
          explained: data.explained,
          dryRun:    true,
        };
        dispatch({ type: "DECISION_MADE", result });
        console.log("[confirmIntent] DECISION_MADE dispatched:", JSON.stringify(result));
      } catch (err) {
        console.error("[confirmIntent] /api/decide FAILED:", err);
        const error = err instanceof Error ? err.message : "Network error";
        dispatch({ type: "STEP_ERROR", id: "decide", error });
      }
    }
  }, [runStep, useMocks, state.intent, domain]);

  const rejectIntent = useCallback(() => {
    dispatch({ type: "REJECTED" });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: "RESET" });
  }, []);

  return { state, submitQuery, stopPipeline, answerClarification, confirmIntent, rejectIntent, reset, domain, setDomain };
}
