// src/components/IntentDisplay/IntentDisplay.tsx

import { Card, Progress, Tag, Collapse, Typography } from "antd";
import type { DynamicIntent, IntentField, DomainFieldMeta } from "@/types/intent";
import { DEFAULT_FIELD_META, buildFieldLabels, buildThresholds } from "@/types/intent";
import styles from "./IntentDisplay.module.css";

const { Text } = Typography;

interface IntentDisplayProps {
  intent:        DynamicIntent;
  lowConfidence: IntentField[];
  fieldMeta?:    DomainFieldMeta[];  // from domain config, falls back to defaults
}

export function IntentDisplay({ intent, lowConfidence, fieldMeta }: IntentDisplayProps) {
  const meta     = fieldMeta ?? DEFAULT_FIELD_META;
  const labels   = buildFieldLabels(meta);
  const thresholds = buildThresholds(meta);

  // Show fields in the order defined by the domain, or fall back to intent keys
  const fieldOrder = meta.length > 0
    ? meta.map(f => f.name)
    : Object.keys(intent);

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Parsed Intent</span>}
    >
      <div className={styles.fieldList}>
        {fieldOrder.map((field) => {
          const hypotheses = intent[field];
          if (!hypotheses) return null;
          const top        = hypotheses[0];
          const threshold  = thresholds[field] ?? 0.7;
          const isLow      = lowConfidence.includes(field);
          const confidence = top?.confidence ?? 0;
          const status     = confidence >= threshold ? "success" : "exception";

          return (
            <div key={field} className={`${styles.fieldRow} ${isLow ? styles.fieldRowLow : ""}`}>
              <div className={styles.fieldHeader}>
                <Text className={styles.fieldLabel}>{labels[field] ?? field}</Text>
                {isLow && <Tag color="error" className={styles.lowTag}>low confidence</Tag>}
              </div>

              <div className={styles.fieldValue}>
                <Text className={styles.topValue}>
                  {top?.value ?? <span className={styles.nullValue}>—</span>}
                </Text>
                <Progress
                  percent={Math.round(confidence * 100)}
                  size="small"
                  status={status}
                  className={styles.progress}
                  showInfo={false}
                />
                <Text type="secondary" className={styles.confidenceLabel}>
                  {Math.round(confidence * 100)}%
                </Text>
              </div>

              {hypotheses.length > 1 && (
                <Collapse
                  ghost
                  size="small"
                  className={styles.hypothesesCollapse}
                  items={[{
                    key:      "alt",
                    label:    <Text type="secondary" className={styles.altLabel}>
                                +{hypotheses.length - 1} alternative hypotheses
                              </Text>,
                    children: (
                      <div className={styles.altList}>
                        {hypotheses.slice(1).map((h, i) => (
                          <div key={i} className={styles.altItem}>
                            <Text className={styles.altValue}>{h.value ?? "—"}</Text>
                            <Text type="secondary" className={styles.altConfidence}>
                              {Math.round(h.confidence * 100)}%
                            </Text>
                          </div>
                        ))}
                      </div>
                    ),
                  }]}
                />
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
