// src/components/ClarificationPanel/ClarificationPanel.tsx

import { useState, useEffect, useRef } from "react";
import { Card, Alert, Input, Button, Progress, Typography, Space } from "antd";
import type { InputRef } from "antd";
import { QuestionCircleOutlined, ForwardOutlined } from "@ant-design/icons";
import type { ClarificationRequest } from "@/types/intent";
import { FIELD_LABELS } from "@/types/intent";
import styles from "./ClarificationPanel.module.css";

const { Text } = Typography;

interface ClarificationPanelProps {
  request:       ClarificationRequest;
  iteration:     number;
  maxIterations: number;
  onAnswer:      (answer: string) => void;
  onSkip:        () => void;
  fieldLabels?:  Record<string, string>;  // from domain config, falls back to defaults
}

export function ClarificationPanel({
  request,
  iteration,
  maxIterations,
  onAnswer,
  onSkip,
  fieldLabels,
}: ClarificationPanelProps) {
  const labels = fieldLabels ?? FIELD_LABELS;
  const [value, setValue] = useState("");
  const inputRef = useRef<InputRef>(null);

  useEffect(() => {
    setValue("");
    inputRef.current?.focus();
  }, [request.field]);

  const handleConfirm = () => {
    if (value.trim()) onAnswer(value.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleConfirm();
  };

  const progressPercent = Math.round(((iteration - 1) / maxIterations) * 100);

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Clarification needed</span>}
    >
      <div className={styles.iterationRow}>
        <Text type="secondary" className={styles.iterationLabel}>
          Field: <span className={styles.fieldBadge}>{labels[request.field] ?? request.field}</span>
        </Text>
        <Text type="secondary" className={styles.iterationCount}>
          {iteration} / {maxIterations}
        </Text>
      </div>

      <Progress
        percent={progressPercent}
        size="small"
        showInfo={false}
        strokeColor="var(--color-warning)"
        className={styles.progress}
      />

      <Alert
        type="warning"
        icon={<QuestionCircleOutlined />}
        message={<span className={styles.question}>{request.question}</span>}
        className={styles.alert}
        showIcon
      />

      <div className={styles.inputRow}>
        <Input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Your answer..."
          className={styles.input}
          aria-label="Answer to the clarification question"
        />
        <Space>
          <Button
            icon={<ForwardOutlined />}
            onClick={onSkip}
            aria-label="Skip this field"
          >
            Skip
          </Button>
          <Button
            type="primary"
            onClick={handleConfirm}
            disabled={!value.trim()}
            aria-label="Confirm answer"
          >
            Confirm
          </Button>
        </Space>
      </div>
    </Card>
  );
}
