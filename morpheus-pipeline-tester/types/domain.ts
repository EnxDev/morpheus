export interface FieldDefinition {
  name: string;
  label: string;
  description: string;
  threshold: number;
  weight: number;
  priority: number;
  default_value: string | null;
  fallback_question: string;
  examples: string[];
}

export interface CapabilityDefinition {
  action: string;
  field_weights: Record<string, number>;
  min_score: number;
}

export interface ExecutionStep {
  step: string;
  type: "pure" | "reversible" | "side_effect";
  timeout_ms: number;
  retry: number;
}

export interface DomainConfig {
  name: string;
  domain_description: string;
  fields: FieldDefinition[];
  capabilities: CapabilityDefinition[];
  execution_plans: Record<string, ExecutionStep[]>;
  parser_prompt_template: string;
  validation_prompt_template: string;
  clarification_policy: {
    max_iterations: number;
    ask_one_field_at_a_time: boolean;
    fallback_on_max_iterations: string;
  };
}

export interface DomainSummaryField {
  name: string;
  label: string;
  description: string;
  threshold: number;
  ambiguity_threshold: number;
}

export interface DomainSummary {
  description: string;
  fields: DomainSummaryField[];
  capabilities: string[];
}
