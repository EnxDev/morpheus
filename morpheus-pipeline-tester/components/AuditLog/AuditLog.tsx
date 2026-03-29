// src/components/AuditLog/AuditLog.tsx

import { useEffect, useRef } from "react";
import { Card, Tag, Typography, Button, Collapse, Empty } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import type { AuditEvent } from "@/types/intent";
import { AUDIT_EVENT_COLORS } from "@/types/intent";
import styles from "./AuditLog.module.css";

const { Text } = Typography;

function formatTime(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

interface AuditEventRowProps {
  event: AuditEvent;
  index: number;
}

function AuditEventRow({ event, index }: AuditEventRowProps) {
  const color = AUDIT_EVENT_COLORS[event.event] ?? "default";
  const hasData = event.data !== undefined;

  const rowContent = (
    <div className={styles.eventRow}>
      <Text className={styles.timestamp}>{formatTime(event.timestamp)}</Text>
      <Tag color={color} className={styles.eventTag}>
        {event.event}
      </Tag>
    </div>
  );

  if (!hasData) return rowContent;

  return (
    <Collapse
      ghost
      size="small"
      className={styles.eventCollapse}
      items={[{
        key:      String(index),
        label:    rowContent,
        children: (
          <pre className={styles.eventData}>
            {JSON.stringify(event.data, null, 2)}
          </pre>
        ),
      }]}
    />
  );
}

interface AuditLogProps {
  events: AuditEvent[];
}

export function AuditLog({ events }: AuditLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  const handleCopy = () => {
    void navigator.clipboard.writeText(JSON.stringify(events, null, 2));
  };

  return (
    <Card
      className={styles.card}
      title={<span className={styles.cardTitle}>Audit Log</span>}
      extra={
        <Button
          size="small"
          icon={<CopyOutlined />}
          onClick={handleCopy}
          disabled={events.length === 0}
          aria-label="Copy full log"
        >
          Copy JSON
        </Button>
      }
    >
      <div className={styles.logContainer}>
        {events.length === 0 ? (
          <Empty
            description={<Text type="secondary">No events yet</Text>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            className={styles.empty}
          />
        ) : (
          events.map((event, i) => (
            <AuditEventRow key={i} event={event} index={i} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </Card>
  );
}
