// src/App.tsx

import { ConfigProvider, Layout, Typography, Alert, Menu, theme } from "antd";
import {
  ExperimentOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Routes, Route, useNavigate, useLocation } from "react-router-dom";
import { QueryInput } from "@/components/QueryInput/QueryInput";
import { PipelineTracker } from "@/components/PipelineTracker/PipelineTracker";
import { IntentDisplay } from "@/components/IntentDisplay/IntentDisplay";
import { ClarificationPanel } from "@/components/ClarificationPanel/ClarificationPanel";
import { ConfirmationStep } from "@/components/ConfirmationStep/ConfirmationStep";
import { DecisionDisplay } from "@/components/DecisionDisplay/DecisionDisplay";
import { AuditLog } from "@/components/AuditLog/AuditLog";
import { DomainConfigurator } from "@/components/DomainConfigurator/DomainConfigurator";
import { usePipeline } from "@/hooks/usePipeline";
import { useDomains } from "@/hooks/useDomains";
import styles from "./App.module.css";

const { Header, Content } = Layout;
const { Title } = Typography;

function PipelineTester() {
  const {
    state,
    submitQuery,
    stopPipeline,
    answerClarification,
    confirmIntent,
    rejectIntent,
    reset,
    domain,
    setDomain,
  } = usePipeline(import.meta.env.VITE_MOCK_DATA !== "false");

  const { domains } = useDomains();
  const domainNames = Object.keys(domains);

  // Resolve field metadata from selected domain for human-readable labels
  const activeDomainMeta = domain && domains[domain]
    ? domains[domain].fields.map((f) => ({
        name:                f.name,
        label:               f.label,
        description:         f.description,
        threshold:           f.threshold,
        ambiguity_threshold: f.ambiguity_threshold,
      }))
    : undefined;

  const isLoading = state.status === "running";
  const hasError = state.steps.some((s) => s.status === "error");
  const isInputDisabled = state.status === "clarifying" || state.status === "confirming";
  const errorStep = state.steps.find((s) => s.status === "error");

  return (
    <Content className={styles.content}>
      <div className={styles.leftPanel}>
        <QueryInput
          onSubmit={submitQuery}
          onStop={stopPipeline}
          onClearError={reset}
          loading={isLoading}
          disabled={isInputDisabled}
          hasError={hasError}
          domains={domainNames}
          selectedDomain={domain}
          onDomainChange={setDomain}
        />

        {errorStep?.error && (
          <Alert
            type="error"
            showIcon
            message={`${errorStep.label} failed`}
            description={errorStep.error}
            closable
          />
        )}

        {state.intent && (
          <IntentDisplay
            intent={state.intent}
            lowConfidence={state.lowConfidence}
            fieldMeta={activeDomainMeta}
          />
        )}

        {state.status === "clarifying" && state.currentClarification && (
          <ClarificationPanel
            request={state.currentClarification}
            iteration={state.currentClarification.iteration}
            maxIterations={3}
            onAnswer={answerClarification}
            onSkip={() => answerClarification("")}
            fieldLabels={activeDomainMeta ? Object.fromEntries(activeDomainMeta.map((f) => [f.name, f.label])) : undefined}
          />
        )}

        {state.status === "confirming" && state.intent && (
          <ConfirmationStep
            intent={state.intent}
            onConfirm={confirmIntent}
            onReject={rejectIntent}
            fieldMeta={activeDomainMeta}
          />
        )}

        {state.status === "done" && state.decisionResult && (
          <DecisionDisplay
            result={state.decisionResult}
            fieldMeta={activeDomainMeta}
          />
        )}
      </div>

      <div className={styles.rightPanel}>
        <PipelineTracker steps={state.steps} />
        <AuditLog events={state.auditLog} />
      </div>
    </Content>
  );
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  const currentKey = location.pathname === "/config" ? "config" : "tester";

  return (
    <ConfigProvider theme={{ algorithm: theme.darkAlgorithm }}>
      <Layout className={styles.layout}>
        <Header className={styles.header}>
          <Title level={4} className={styles.headerTitle}>
            Morpheus Pipeline Tester
          </Title>
          <div className={styles.headerNav}>
            <Menu
              mode="horizontal"
              selectedKeys={[currentKey]}
              onClick={({ key }) =>
                navigate(key === "config" ? "/config" : "/")
              }
              style={{ background: "transparent", borderBottom: "none" }}
              items={[
                {
                  key: "tester",
                  icon: <ExperimentOutlined />,
                  label: "Pipeline Tester",
                },
                {
                  key: "config",
                  icon: <SettingOutlined />,
                  label: "Domain Config",
                },
              ]}
            />
          </div>
        </Header>

        <Routes>
          <Route path="/" element={<PipelineTester />} />
          <Route path="/config" element={<DomainConfigurator />} />
        </Routes>
      </Layout>
    </ConfigProvider>
  );
}
