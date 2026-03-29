import type { SupersetIntent, IntentField, DecisionResult } from "@/types/intent";

export const delay = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

const MOCK_INTENTS: Record<string, SupersetIntent> = {
  default: {
    measure:     [{ value: "revenue", confidence: 0.92 }],
    dimension:   [{ value: "region", confidence: 0.88 }],
    time_range:  [{ value: "Q1 2025", confidence: 0.95 }],
    filters:     [{ value: null, confidence: 0.3 }],
    granularity: [{ value: "monthly", confidence: 0.85 }],
    comparison:  [{ value: null, confidence: 0.2 }],
  },
  vague: {
    measure:     [{ value: null, confidence: 0.15 }],
    dimension:   [{ value: null, confidence: 0.1 }],
    time_range:  [{ value: null, confidence: 0.2 }],
    filters:     [{ value: null, confidence: 0.05 }],
    granularity: [{ value: null, confidence: 0.1 }],
    comparison:  [{ value: null, confidence: 0.05 }],
  },
  complete: {
    measure:     [{ value: "sales", confidence: 0.97 }, { value: "revenue", confidence: 0.6 }],
    dimension:   [{ value: "region", confidence: 0.93 }],
    time_range:  [{ value: "Q1 2025", confidence: 0.96 }],
    filters:     [{ value: "online channel only", confidence: 0.91 }],
    granularity: [{ value: "monthly", confidence: 0.88 }],
    comparison:  [{ value: "vs Q1 2024", confidence: 0.94 }],
  },
};

export function selectMockIntent(query: string): SupersetIntent {
  const q = query.toLowerCase();
  if (q.includes("how are we doing") || q.includes("enterprise only")) {
    return MOCK_INTENTS.vague;
  }
  if (q.includes("monthly") || q.includes("comparison") || q.includes("by region")) {
    return MOCK_INTENTS.complete;
  }
  return MOCK_INTENTS.default;
}

export const MOCK_DECISION_RESULT: DecisionResult = {
  action:    "generate_chart",
  score:     0.91,
  explained: {
    measure_clarity:  0.95,
    dimension_match:  0.88,
    time_specificity: 0.90,
  },
  dryRun: true,
};

export const MOCK_CLARIFICATION_QUESTIONS: Partial<Record<IntentField, string>> = {
  measure:     "Which metric do you want to analyze? (e.g. sales, revenue, margin)",
  dimension:   "How do you want to group the data? (e.g. by region, by product)",
  time_range:  "What time period are you interested in?",
  filters:     "Do you want to filter the data in any way? (e.g. online channel only)",
  granularity: "At what level of detail? (daily, weekly, monthly)",
  comparison:  "Do you want to compare with another period or segment?",
};
