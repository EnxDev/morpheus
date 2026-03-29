import { Card, Progress, Tag, Typography } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { DecisionResult, DomainFieldMeta } from "@/types/intent";
import { DEFAULT_FIELD_META, buildFieldLabels } from "@/types/intent";
import styles from "./DecisionDisplay.module.css";

const { Text } = Typography;

interface DecisionDisplayProps {
  result: DecisionResult;
  fieldMeta?: DomainFieldMeta[];
}

export function DecisionDisplay({ result, fieldMeta }: DecisionDisplayProps) {
  const labels = buildFieldLabels(fieldMeta ?? DEFAULT_FIELD_META);
  const scorePct = Math.round(result.score * 100);
  const validation = result.actionValidation;
  const isBlocked = validation?.status === "blocked";

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Decision Result</span>}
    >
      <div className={styles.actionRow}>
        <ThunderboltOutlined />
        <Text className={styles.actionName}>{result.action}</Text>
        {isBlocked ? (
          <Tag icon={<CloseCircleOutlined />} color="error">BLOCKED</Tag>
        ) : (
          <Tag icon={<CheckCircleOutlined />} color="success">APPROVED</Tag>
        )}
      </div>

      <div className={styles.scoreRow}>
        <Text className={styles.scoreLabel}>Score</Text>
        <Progress
          percent={scorePct}
          size="small"
          status={scorePct >= 60 ? "success" : "exception"}
          style={{ flex: 1 }}
          showInfo={false}
        />
        <Text className={styles.scoreValue}>{scorePct}%</Text>
      </div>

      {Object.keys(result.explained).length > 0 && (
        <div className={styles.weightsSection}>
          <Text className={styles.weightsTitle}>Field weights</Text>
          {Object.entries(result.explained)
            .sort(([, a], [, b]) => b - a)
            .map(([field, weight]) => (
              <div key={field} className={styles.weightRow}>
                <Text className={styles.weightField}>
                  {labels[field] ?? field}
                </Text>
                <Progress
                  percent={Math.round(weight * 100)}
                  size="small"
                  showInfo={false}
                  className={styles.weightBar}
                />
                <Text className={styles.weightValue}>
                  {Math.round(weight * 100)}%
                </Text>
              </div>
            ))}
        </div>
      )}

      {validation && (
        <div
          className={`${styles.validationSection} ${
            isBlocked ? styles.validationBlocked : styles.validationApproved
          }`}
        >
          <Text strong>Control 2: {validation.status}</Text>
          {validation.reason && (
            <div>
              <Text type="secondary">{validation.reason}</Text>
            </div>
          )}
          {validation.risk_level && (
            <Tag
              color={
                validation.risk_level === "HIGH" ? "error"
                : validation.risk_level === "MEDIUM" ? "warning"
                : "default"
              }
              style={{ marginTop: 4 }}
            >
              Risk: {validation.risk_level}
            </Tag>
          )}
        </div>
      )}
    </Card>
  );
}
