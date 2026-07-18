import { useEffect, useMemo, useState } from "react";

import { ApiError, api, type Session } from "./api";
import { cacheDraft, readDraft, removeDraft } from "./draftCache";
import type { GeneralSection, Readiness, Report, SaveState } from "./types";

const EMPTY_GENERAL: GeneralSection = {
  operation_mode: "",
  interval_id: "",
  fluid_system_id: "",
  present_activity: "",
};

interface AppProps {
  initialReport?: Report;
  session?: Session;
}

function StateBadge({ value }: { value: string }) {
  return <span className={`state-badge state-${value}`}>{value.replaceAll("_", " ")}</span>;
}

export default function App({ initialReport, session }: AppProps) {
  const [report, setReport] = useState<Report | undefined>(initialReport);
  const [general, setGeneral] = useState<GeneralSection>(initialReport?.revision.data.general ?? EMPTY_GENERAL);
  const [readiness, setReadiness] = useState<Readiness>();
  const [saveState, setSaveState] = useState<SaveState>("Saved");
  const [error, setError] = useState<string>();

  const mutable = report?.revision.state === "draft" || report?.revision.state === "ready_for_review";
  const checksum = report?.revision.checksum?.slice(0, 12);
  const sections = useMemo(
    () => [
      { label: "General", state: readiness?.state ?? "incomplete" },
      { label: "Readiness", state: readiness?.can_submit ? "ready" : "incomplete" },
      { label: "Frozen report", state: report?.revision.checksum ? "ready" : "unavailable" },
    ],
    [readiness, report],
  );

  useEffect(() => {
    if (!report || !mutable) return;
    readDraft(report.id).then((cached) => {
      if (cached && cached.baseVersion === report.revision.version) {
        setGeneral(cached.general);
        setSaveState("Offline draft");
      }
    });
  }, [report, mutable]);

  function update<K extends keyof GeneralSection>(field: K, value: GeneralSection[K]) {
    const next = { ...general, [field]: value };
    setGeneral(next);
    if (report) {
      void cacheDraft({
        reportId: report.id,
        baseVersion: report.revision.version,
        mutationId: crypto.randomUUID(),
        savedAt: new Date().toISOString(),
        general: next,
      });
      setSaveState(navigator.onLine ? "Sync pending" : "Offline draft");
    }
  }

  async function run(action: () => Promise<Report>) {
    setError(undefined);
    try {
      const next = await action();
      setReport(next);
      setGeneral(next.revision.data.general ?? EMPTY_GENERAL);
      setSaveState("Saved");
      await removeDraft(next.id);
      if (session) setReadiness(await api.validate(session, next.revision.id));
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "REPORT_VERSION_CONFLICT") setSaveState("Conflict");
      else setSaveState("Failed");
      setError(caught instanceof Error ? caught.message : "Action failed");
    }
  }

  if (!report || !session) {
    return (
      <main className="empty-shell">
        <div className="brand-mark">V</div>
        <h1>Vantix foundation workspace</h1>
        <p>Connect an authenticated organisation and open a configured project day to begin.</p>
        <span className="state-badge state-incomplete">No active report</span>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>V</span> Vantix</div>
        <nav aria-label="Project sections">
          <p className="nav-caption">Daily report</p>
          {sections.map((section) => (
            <button className={section.label === "General" ? "nav-item active" : "nav-item"} key={section.label}>
              <span>{section.label}</span><i className={`status-dot ${section.state}`} aria-label={section.state} />
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="eyebrow">Report</span>
          <strong>{report.report_number}</strong>
          <small>{report.report_date}</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div>
            <span className="eyebrow">Daily operations / Foundation</span>
            <h1>Daily general record</h1>
          </div>
          <div className="header-status">
            <span className={`save-state save-${saveState.toLowerCase().replace(" ", "-")}`}>{saveState}</span>
            <StateBadge value={report.revision.state} />
          </div>
        </header>

        <section className="context-strip" aria-label="Report context">
          <div><span>Revision</span><strong>{report.revision.number}</strong></div>
          <div><span>Version</span><strong>{report.revision.version}</strong></div>
          <div><span>Payload</span><strong>{checksum ?? "Not frozen"}</strong></div>
          <div><span>Basis</span><strong>Configuration snapshot</strong></div>
        </section>

        {error && <div className="error-panel" role="alert">{error}</div>}

        <div className="content-grid">
          <section className="panel form-panel">
            <div className="panel-heading">
              <div><span className="eyebrow">Required section</span><h2>Operational context</h2></div>
              <StateBadge value={mutable ? "draft" : "locked"} />
            </div>
            <div className="form-grid">
              <label>Operation mode<input disabled={!mutable} value={general.operation_mode} onChange={(e) => update("operation_mode", e.target.value)} placeholder="e.g. Drilling" /></label>
              <label>Present activity<input disabled={!mutable} value={general.present_activity} onChange={(e) => update("present_activity", e.target.value)} placeholder="Current wellsite activity" /></label>
              <label>Interval ID<input disabled={!mutable} value={general.interval_id} onChange={(e) => update("interval_id", e.target.value)} placeholder="Configured interval UUID" /></label>
              <label>Fluid system ID<input disabled={!mutable} value={general.fluid_system_id} onChange={(e) => update("fluid_system_id", e.target.value)} placeholder="Configured fluid system UUID" /></label>
            </div>
            <div className="button-row">
              <button className="button secondary" disabled={!mutable} onClick={() => void run(() => api.saveGeneral(session, report, general))}>Save draft</button>
              <button className="button ghost" onClick={() => void api.validate(session, report.revision.id).then(setReadiness)}>Validate readiness</button>
              <button className="button primary" disabled={!mutable || readiness?.can_submit !== true} onClick={() => void run(() => api.submit(session, report))}>Submit immutable revision</button>
            </div>
          </section>

          <aside className="panel readiness-panel">
            <div className="panel-heading"><div><span className="eyebrow">Server evaluation</span><h2>Readiness</h2></div><StateBadge value={readiness?.state ?? "incomplete"} /></div>
            {!readiness ? <p className="muted">Run validation to see blocking issues and caveats.</p> : readiness.issues.length === 0 ? <div className="ready-message"><strong>Ready to submit</strong><span>All foundation requirements are satisfied.</span></div> : <ul className="issue-list">{readiness.issues.map((issue) => <li key={`${issue.code}-${issue.field}`}><strong>{issue.field?.replaceAll("_", " ") ?? issue.section}</strong><span>{issue.message}</span></li>)}</ul>}
          </aside>
        </div>

        {report.revision.state === "submitted" && (
          <section className="decision-bar">
            <div><strong>Immutable submission awaiting decision</strong><span>Decisions are bound to revision {report.revision.number} and checksum {checksum}.</span></div>
            <button className="button danger" onClick={() => void run(() => api.reject(session, report, "Reviewer correction requested"))}>Reject and create revision</button>
            <button className="button primary" onClick={() => void run(() => api.approve(session, report))}>Approve revision</button>
          </section>
        )}
      </main>
    </div>
  );
}
