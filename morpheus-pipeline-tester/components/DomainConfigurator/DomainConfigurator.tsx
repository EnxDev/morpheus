import { useState } from "react";
import {
  Card,
  Button,
  Input,
  InputNumber,
  Slider,
  Tag,
  Space,
  Typography,
  Alert,
  Tabs,
  Tooltip,
  Modal,
  Empty,
  Spin,
} from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  SaveOutlined,
  EyeOutlined,
  AppstoreOutlined,
  SettingOutlined,
  CodeOutlined,
} from "@ant-design/icons";
import { useDomains } from "@/hooks/useDomains";
import type { DomainConfig, FieldDefinition, CapabilityDefinition } from "@/types/domain";
import styles from "./DomainConfigurator.module.css";

const { TextArea } = Input;
const { Text } = Typography;

function emptyField(): FieldDefinition {
  return {
    name: "",
    label: "",
    description: "",
    threshold: 0.7,
    weight: 0.2,
    priority: 1,
    default_value: null,
    fallback_question: "",
    examples: [],
  };
}

function emptyCapability(fieldNames: string[]): CapabilityDefinition {
  const weights: Record<string, number> = {};
  fieldNames.forEach((f) => (weights[f] = 0.5));
  return { action: "", field_weights: weights, min_score: 0.6 };
}

function emptyConfig(): DomainConfig {
  return {
    name: "",
    domain_description: "",
    fields: [emptyField()],
    capabilities: [],
    execution_plans: {},
    parser_prompt_template:
      "You are an intent parser. Extract structured intent from a user query.\n\n" +
      "Fields:\n{field_definitions}\n\n" +
      "Each hypothesis: {{\"value\": string or null, \"confidence\": 0.0-1.0}}\n\n" +
      "Rules:\n- Never invent values\n- Include all {field_count} fields\n" +
      "- If unclear: {{\"value\": null, \"confidence\": 0.1}}\n- Output ONLY JSON\n\n" +
      'User: "{user_input}"',
    validation_prompt_template:
      "Is this a structurally coherent intent with key fields ({field_names}) present?\n\n" +
      "{intent_text}\n\nAnswer YES or NO.",
    clarification_policy: {
      max_iterations: 3,
      ask_one_field_at_a_time: true,
      fallback_on_max_iterations: "reject",
    },
  };
}

function FieldEditor({
  field,
  index,
  onChange,
  onRemove,
}: {
  field: FieldDefinition;
  index: number;
  onChange: (index: number, field: FieldDefinition) => void;
  onRemove: (index: number) => void;
}) {
  const update = (patch: Partial<FieldDefinition>) =>
    onChange(index, { ...field, ...patch });

  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <div className={styles.fieldRow}>
        <Input
          placeholder="Field name (e.g. measure)"
          value={field.name}
          onChange={(e) => update({ name: e.target.value })}
          size="small"
        />
        <Input
          placeholder="Label (e.g. Measure)"
          value={field.label}
          onChange={(e) => update({ label: e.target.value })}
          size="small"
        />
        <div className={styles.fieldActions}>
          <Button
            icon={<DeleteOutlined />}
            size="small"
            danger
            onClick={() => onRemove(index)}
          />
        </div>
      </div>
      <div className={styles.fieldRow}>
        <Input
          placeholder="Description"
          value={field.description}
          onChange={(e) => update({ description: e.target.value })}
          size="small"
        />
        <Input
          placeholder="Fallback question"
          value={field.fallback_question}
          onChange={(e) => update({ fallback_question: e.target.value })}
          size="small"
        />
      </div>
      <div className={styles.fieldRow}>
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            Threshold
          </Text>
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={field.threshold}
            onChange={(v) => update({ threshold: v })}
          />
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            Weight
          </Text>
          <Slider
            min={0}
            max={1}
            step={0.05}
            value={field.weight}
            onChange={(v) => update({ weight: v })}
          />
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            Priority
          </Text>
          <InputNumber
            min={1}
            max={20}
            value={field.priority}
            onChange={(v) => update({ priority: v ?? 1 })}
            size="small"
            style={{ width: "100%" }}
          />
        </div>
      </div>
      <Input
        placeholder="Examples (comma-separated)"
        value={field.examples.join(", ")}
        onChange={(e) =>
          update({
            examples: e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          })
        }
        size="small"
      />
    </Card>
  );
}

function CapabilityEditor({
  cap,
  index,
  fieldNames,
  onChange,
  onRemove,
}: {
  cap: CapabilityDefinition;
  index: number;
  fieldNames: string[];
  onChange: (index: number, cap: CapabilityDefinition) => void;
  onRemove: (index: number) => void;
}) {
  const update = (patch: Partial<CapabilityDefinition>) =>
    onChange(index, { ...cap, ...patch });

  // Sync weights with current fields
  const weights = { ...cap.field_weights };
  fieldNames.forEach((f) => {
    if (!(f in weights)) weights[f] = 0;
  });

  return (
    <div className={styles.capRow}>
      <div className={styles.capHeader}>
        <Input
          placeholder="Action name (e.g. deploy)"
          value={cap.action}
          onChange={(e) => update({ action: e.target.value })}
          size="small"
          style={{ maxWidth: 250 }}
        />
        <Space>
          <div>
            <Text type="secondary" style={{ fontSize: 11, marginRight: 8 }}>
              Min Score
            </Text>
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              value={cap.min_score}
              onChange={(v) => update({ min_score: v ?? 0.5 })}
              size="small"
              style={{ width: 80 }}
            />
          </div>
          <Button
            icon={<DeleteOutlined />}
            size="small"
            danger
            onClick={() => onRemove(index)}
          />
        </Space>
      </div>
      <Text type="secondary" style={{ fontSize: 11 }}>
        Field Importance Weights
      </Text>
      <div className={styles.weightsGrid}>
        {fieldNames.map((f) => (
          <div className={styles.weightItem} key={f}>
            <label>{f}</label>
            <Slider
              min={0}
              max={1}
              step={0.05}
              value={weights[f] ?? 0}
              onChange={(v) =>
                update({ field_weights: { ...weights, [f]: v } })
              }
              style={{ flex: 1 }}
            />
            <Text style={{ fontSize: 11, minWidth: 28 }}>
              {(weights[f] ?? 0).toFixed(2)}
            </Text>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DomainConfigurator() {
  const { domains, loading, error, registerDomain, deleteDomain } = useDomains();
  const [config, setConfig] = useState<DomainConfig>(emptyConfig());
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const fieldNames = config.fields.map((f) => f.name).filter(Boolean);

  const updateField = (index: number, field: FieldDefinition) => {
    const fields = [...config.fields];
    fields[index] = field;
    setConfig({ ...config, fields });
  };

  const removeField = (index: number) => {
    const fields = config.fields.filter((_, i) => i !== index);
    setConfig({ ...config, fields: fields.length ? fields : [emptyField()] });
  };

  const addField = () => {
    setConfig({ ...config, fields: [...config.fields, emptyField()] });
  };

  const updateCapability = (index: number, cap: CapabilityDefinition) => {
    const capabilities = [...config.capabilities];
    capabilities[index] = cap;
    setConfig({ ...config, capabilities });
  };

  const removeCapability = (index: number) => {
    setConfig({
      ...config,
      capabilities: config.capabilities.filter((_, i) => i !== index),
    });
  };

  const addCapability = () => {
    setConfig({
      ...config,
      capabilities: [...config.capabilities, emptyCapability(fieldNames)],
    });
  };

  const handleSave = async () => {
    setSaveError(null);
    setSaveSuccess(false);

    if (!config.name.trim()) {
      setSaveError("Domain name is required");
      return;
    }
    if (config.fields.every((f) => !f.name.trim())) {
      setSaveError("At least one field with a name is required");
      return;
    }

    try {
      await registerDomain(config);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    }
  };

  const handleLoadDomain = async (name: string) => {
    try {
      const resp = await fetch(`http://localhost:8000/api/domains`);
      const data = await resp.json();
      if (data[name]) {
        // We only have the summary from /api/domains, but we can pre-fill basics
        const summary = data[name];
        const fieldNames = summary.fields.map((f: { name: string }) => f.name);
        setConfig({
          ...emptyConfig(),
          name,
          domain_description: summary.description,
          fields: summary.fields.map((f: { name: string; label: string; description: string; threshold: number }, i: number) => ({
            ...emptyField(),
            name: f.name,
            label: f.label || f.name,
            description: f.description || "",
            threshold: f.threshold ?? 0.7,
            priority: i + 1,
          })),
          capabilities: summary.capabilities.map((action: string) => ({
            action,
            field_weights: Object.fromEntries(
              fieldNames.map((n: string) => [n, 0.5])
            ),
            min_score: 0.6,
          })),
        });
      }
    } catch {
      // ignore
    }
  };

  return (
    <div className={styles.page}>
      {/* Existing domains */}
      <div className={styles.section}>
        <div className={styles.sectionTitle}>Registered Domains</div>
        {loading && <Spin size="small" />}
        {!loading && Object.keys(domains).length === 0 && (
          <Empty
            description="No domains registered yet"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
        <div className={styles.domainList}>
          {Object.entries(domains).map(([name, summary]) => (
            <Card
              key={name}
              size="small"
              className={styles.domainCard}
              title={name}
              extra={
                <Space>
                  <Button size="small" onClick={() => handleLoadDomain(name)}>
                    Load
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      Modal.confirm({
                        title: `Delete domain "${name}"?`,
                        content: "This action cannot be undone.",
                        okText: "Delete",
                        okType: "danger",
                        onOk: () => deleteDomain(name),
                      });
                    }}
                  />
                </Space>
              }
            >
              <Text type="secondary">{summary.description}</Text>
              <div style={{ marginTop: 8 }}>
                {summary.fields.map((f) => (
                  <Tag key={f.name}>{f.label || f.name}</Tag>
                ))}
              </div>
              <div style={{ marginTop: 4 }}>
                {summary.capabilities.map((c) => (
                  <Tag key={c} color="blue">
                    {c}
                  </Tag>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Domain editor */}
      <Card
        title={
          <Space>
            <SettingOutlined />
            <span>Domain Configuration</span>
          </Space>
        }
        extra={
          <Space>
            <Tooltip title="Preview JSON">
              <Button
                icon={<EyeOutlined />}
                onClick={() => setPreviewOpen(true)}
              />
            </Tooltip>
            <Button
              icon={<SaveOutlined />}
              type="primary"
              onClick={handleSave}
              loading={loading}
            >
              Register Domain
            </Button>
          </Space>
        }
      >
        {saveError && (
          <Alert
            type="error"
            message={saveError}
            closable
            onClose={() => setSaveError(null)}
            style={{ marginBottom: 16 }}
          />
        )}
        {saveSuccess && (
          <Alert
            type="success"
            message="Domain registered successfully"
            closable
            style={{ marginBottom: 16 }}
          />
        )}

        <Tabs
          items={[
            {
              key: "general",
              label: (
                <span>
                  <AppstoreOutlined /> General
                </span>
              ),
              children: (
                <div className={styles.section}>
                  <div className={styles.fieldRow}>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Domain Name
                      </Text>
                      <Input
                        placeholder="e.g. devops, ecommerce, hr"
                        value={config.name}
                        onChange={(e) =>
                          setConfig({ ...config, name: e.target.value })
                        }
                      />
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Description
                      </Text>
                      <Input
                        placeholder="What this domain is about"
                        value={config.domain_description}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            domain_description: e.target.value,
                          })
                        }
                      />
                    </div>
                  </div>
                  <div className={styles.fieldRow} style={{ marginTop: 16 }}>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        Max Clarification Iterations
                      </Text>
                      <InputNumber
                        min={1}
                        max={10}
                        value={config.clarification_policy.max_iterations}
                        onChange={(v) =>
                          setConfig({
                            ...config,
                            clarification_policy: {
                              ...config.clarification_policy,
                              max_iterations: v ?? 3,
                            },
                          })
                        }
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        On Max Iterations
                      </Text>
                      <Input
                        value={
                          config.clarification_policy
                            .fallback_on_max_iterations
                        }
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            clarification_policy: {
                              ...config.clarification_policy,
                              fallback_on_max_iterations: e.target.value,
                            },
                          })
                        }
                      />
                    </div>
                  </div>
                </div>
              ),
            },
            {
              key: "fields",
              label: (
                <span>
                  <SettingOutlined /> Fields ({config.fields.length})
                </span>
              ),
              children: (
                <div className={styles.section}>
                  {config.fields.map((field, i) => (
                    <FieldEditor
                      key={i}
                      field={field}
                      index={i}
                      onChange={updateField}
                      onRemove={removeField}
                    />
                  ))}
                  <Button
                    icon={<PlusOutlined />}
                    onClick={addField}
                    type="dashed"
                    block
                  >
                    Add Field
                  </Button>
                </div>
              ),
            },
            {
              key: "capabilities",
              label: (
                <span>
                  <AppstoreOutlined /> Capabilities (
                  {config.capabilities.length})
                </span>
              ),
              children: (
                <div className={styles.section}>
                  {fieldNames.length === 0 && (
                    <Alert
                      type="info"
                      message="Define fields first — capability weights are based on your fields"
                      style={{ marginBottom: 16 }}
                    />
                  )}
                  {config.capabilities.map((cap, i) => (
                    <CapabilityEditor
                      key={i}
                      cap={cap}
                      index={i}
                      fieldNames={fieldNames}
                      onChange={updateCapability}
                      onRemove={removeCapability}
                    />
                  ))}
                  <Button
                    icon={<PlusOutlined />}
                    onClick={addCapability}
                    type="dashed"
                    block
                    disabled={fieldNames.length === 0}
                  >
                    Add Capability
                  </Button>
                </div>
              ),
            },
            {
              key: "prompts",
              label: (
                <span>
                  <CodeOutlined /> Prompts
                </span>
              ),
              children: (
                <div className={styles.section}>
                  <div style={{ marginBottom: 16 }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Parser Prompt Template
                    </Text>
                    <Text
                      type="secondary"
                      style={{ fontSize: 10, display: "block", marginBottom: 4 }}
                    >
                      Placeholders: {"{user_input}"}, {"{field_definitions}"},{" "}
                      {"{field_count}"}, {"{field_names}"}
                    </Text>
                    <TextArea
                      className={styles.promptArea}
                      rows={12}
                      value={config.parser_prompt_template}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          parser_prompt_template: e.target.value,
                        })
                      }
                    />
                  </div>
                  <div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      Validation Prompt Template
                    </Text>
                    <Text
                      type="secondary"
                      style={{ fontSize: 10, display: "block", marginBottom: 4 }}
                    >
                      Placeholders: {"{intent_text}"}, {"{field_names}"}
                    </Text>
                    <TextArea
                      className={styles.promptArea}
                      rows={4}
                      value={config.validation_prompt_template}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          validation_prompt_template: e.target.value,
                        })
                      }
                    />
                  </div>
                </div>
              ),
            },
          ]}
        />

        <div className={styles.formActions}>
          <Button onClick={() => setConfig(emptyConfig())}>Clear</Button>
          <Button
            icon={<EyeOutlined />}
            onClick={() => setPreviewOpen(true)}
          >
            Preview JSON
          </Button>
          <Button
            icon={<SaveOutlined />}
            type="primary"
            onClick={handleSave}
            loading={loading}
          >
            Register Domain
          </Button>
        </div>
      </Card>

      {/* JSON Preview Modal */}
      <Modal
        title="Domain Config JSON"
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={
          <Button
            onClick={() => {
              navigator.clipboard.writeText(
                JSON.stringify(config, null, 2)
              );
            }}
          >
            Copy to Clipboard
          </Button>
        }
        width={700}
      >
        <div className={styles.jsonPreview}>
          {JSON.stringify(config, null, 2)}
        </div>
      </Modal>
    </div>
  );
}
