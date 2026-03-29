// src/components/ConfirmationStep/ConfirmationStep.tsx

import { Card, Descriptions, Button, Space, Typography } from "antd";
import { CheckOutlined, EditOutlined } from "@ant-design/icons";
import type { DynamicIntent, DomainFieldMeta } from "@/types/intent";
import { DEFAULT_FIELD_META, buildFieldLabels } from "@/types/intent";
import styles from "./ConfirmationStep.module.css";

const { Text } = Typography;

function topValue(intent: DynamicIntent, field: string): string {
  const hyps = intent[field];
  if (!hyps || hyps.length === 0) return "—";
  return hyps[0]?.value ?? "—";
}

interface ConfirmationStepProps {
  intent:    DynamicIntent;
  onConfirm: () => void;
  onReject:  () => void;
  fieldMeta?: DomainFieldMeta[];
}

export function ConfirmationStep({ intent, onConfirm, onReject, fieldMeta }: ConfirmationStepProps) {
  const meta   = fieldMeta ?? DEFAULT_FIELD_META;
  const labels = buildFieldLabels(meta);
  const fieldOrder = meta.length > 0 ? meta.map(f => f.name) : Object.keys(intent);

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Confirm intent</span>}
    >
      <Text className={styles.intro}>
        I interpreted your request as follows. Shall I proceed?
      </Text>

      <Descriptions
        column={1}
        size="small"
        className={styles.descriptions}
        items={fieldOrder.map((field) => ({
          key:      field,
          label:    <span className={styles.descLabel}>{labels[field] ?? field}</span>,
          children: (
            <span className={styles.descValue}>
              {topValue(intent, field)}
            </span>
          ),
        }))}
      />

      <div className={styles.actions}>
        <Space>
          <Button
            icon={<EditOutlined />}
            onClick={onReject}
            danger
            aria-label="Edit intent"
          >
            Edit
          </Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            onClick={onConfirm}
            aria-label="Confirm and execute"
          >
            Proceed
          </Button>
        </Space>
      </div>
    </Card>
  );
}
