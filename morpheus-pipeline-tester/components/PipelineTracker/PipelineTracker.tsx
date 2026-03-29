// src/components/PipelineTracker/PipelineTracker.tsx

import { Card, Steps, Tag, Typography, Collapse } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  MinusCircleOutlined,
} from "@ant-design/icons";
import type { PipelineStep, StepStatus } from "@/types/intent";
import styles from "./PipelineTracker.module.css";

const { Text } = Typography;

const STATUS_ICON: Record<StepStatus, React.ReactNode> = {
  pending: <ClockCircleOutlined  />,
  running: <LoadingOutlined      />,
  success: <CheckCircleOutlined  />,
  error:   <CloseCircleOutlined  />,
  skipped: <MinusCircleOutlined  />,
};

const STATUS_COLOR: Record<StepStatus, string> = {
  pending: "default",
  running: "processing",
  success: "success",
  error:   "error",
  skipped: "default",
};

interface StepItemProps {
  step: PipelineStep;
}

function StepItem({ step }: StepItemProps) {
  const hasOutput = step.output !== undefined || step.error !== undefined;

  return (
    <div className={styles.stepItem}>
      <div className={styles.stepHeader}>
        <span className={styles[`stepIcon_${step.status}`]}>
          {STATUS_ICON[step.status]}
        </span>
        <span className={styles.stepLabel}>{step.label}</span>
        <Tag color={STATUS_COLOR[step.status]} className={styles.statusTag}>
          {step.status}
        </Tag>
        {step.durationMs !== undefined && (
          <Text type="secondary" className={styles.duration}>
            {step.durationMs}ms
          </Text>
        )}
      </div>

      {hasOutput && (
        <Collapse
          ghost
          size="small"
          className={styles.outputCollapse}
          items={[{
            key:      "output",
            label:    <Text type="secondary" className={styles.outputLabel}>Output</Text>,
            children: (
              <pre className={styles.outputPre}>
                {JSON.stringify(step.error ?? step.output, null, 2)}
              </pre>
            ),
          }]}
        />
      )}
    </div>
  );
}

interface PipelineTrackerProps {
  steps: PipelineStep[];
}

export function PipelineTracker({ steps }: PipelineTrackerProps) {
  const currentIndex = steps.findIndex((s) => s.status === "running");
  const stepsConfig = steps.map((step) => ({
    title:       <StepItem step={step} />,
    status:      step.status === "running" ? "process" as const
                 : step.status === "success" ? "finish" as const
                 : step.status === "error"   ? "error" as const
                 : "wait" as const,
  }));

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Pipeline</span>}
    >
      <Steps
        direction="vertical"
        size="small"
        current={currentIndex >= 0 ? currentIndex : undefined}
        items={stepsConfig}
        className={styles.steps}
      />
    </Card>
  );
}
