import { useEffect, useState } from "react";

import { ApiError, api, type Session } from "./api";
import type {
  BasicInterval,
  ConfigurationReadiness,
  Project,
  ProjectConfiguration as Configuration,
} from "./types";

interface Props {
  projectId: string;
  session: Session;
}

function newInterval(): BasicInterval {
  return { id: crypto.randomUUID(), name: "", operation_mode: "drilling" };
}

export default function ProjectConfiguration({ projectId, session }: Props) {
  const [project, setProject] = useState<Project>();
  const [configuration, setConfiguration] = useState<Configuration>();
  const [readiness, setReadiness] = useState<ConfigurationReadiness>();
  const [message, setMessage] = useState("Loading configuration…");
  const mutable = configuration?.state === "draft";
  const projectDepthUnit = project?.unit_set.toLowerCase().includes("field") ? "ft" : "m";

  useEffect(() => {
    Promise.all([api.getProject(session, projectId), api.listConfigurations(session, projectId)])
      .then(([nextProject, versions]) => {
        setProject(nextProject);
        setConfiguration(versions.find((item) => item.state === "draft") ?? versions[0]);
        setMessage(versions.length ? "Saved" : "Create a draft configuration to begin.");
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Unable to load."));
  }, [projectId, session]);

  function updateInterval(id: string, patch: Partial<BasicInterval>) {
    if (!configuration) return;
    setConfiguration({
      ...configuration,
      data: {
        ...configuration.data,
        intervals: configuration.data.intervals.map((interval) =>
          interval.id === id ? { ...interval, ...patch } : interval,
        ),
      },
    });
    setReadiness(undefined);
    setMessage("Unsaved changes");
  }

  function updateConfiguration(next: Configuration) {
    setConfiguration(next);
    setReadiness(undefined);
    setMessage("Unsaved changes");
  }

  async function createDraft() {
    setMessage("Creating draft…");
    try {
      setConfiguration(await api.createConfiguration(session, projectId));
      setReadiness(undefined);
      setMessage("Draft created");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create draft.");
    }
  }

  async function save() {
    if (!configuration) return;
    setMessage("Saving…");
    try {
      setConfiguration(await api.saveConfiguration(session, configuration));
      setMessage("Saved");
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.code === "CONFIGURATION_VERSION_CONFLICT"
          ? "Conflict — reload before saving"
          : error instanceof Error ? error.message : "Save failed",
      );
    }
  }

  async function validate() {
    if (!configuration) return;
    setReadiness(await api.validateConfiguration(session, configuration));
  }

  async function activate() {
    if (!configuration) return;
    setMessage("Activating…");
    try {
      const next = await api.activateConfiguration(session, configuration);
      setConfiguration(next);
      setMessage("Active snapshot frozen");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Activation failed");
    }
  }

  if (!project) return <main className="empty-shell"><div className="brand-mark">V</div><p>{message}</p></main>;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span>V</span> Vantix</div>
        <nav aria-label="Configuration sections">
          <p className="nav-caption">Project setup</p>
          <button className="nav-item"><span>Identity</span><i className="status-dot ready" /></button>
          <button className="nav-item active"><span>Intervals</span><i className={`status-dot ${readiness?.state ?? "incomplete"}`} /></button>
          <button className="nav-item"><span>Activation</span><i className={`status-dot ${configuration?.state === "active" ? "ready" : "incomplete"}`} /></button>
        </nav>
        <div className="sidebar-foot"><span className="eyebrow">Project</span><strong>{project.project_code}</strong><small>{project.well_name}</small></div>
      </aside>
      <main className="workspace">
        <header className="workspace-header">
          <div><span className="eyebrow">Project configuration / Foundation</span><h1>{project.project_name}</h1></div>
          <div className="header-status"><span className="save-state">{message}</span><span className={`state-badge state-${configuration?.state ?? "incomplete"}`}>{configuration?.state ?? "not configured"}</span></div>
        </header>

        <section className="context-strip" aria-label="Project context">
          <div><span>Well</span><strong>{project.well_name}</strong></div>
          <div><span>Time zone</span><strong>{project.time_zone}</strong></div>
          <div><span>Units</span><strong>{project.unit_set}</strong></div>
          <div><span>Currency</span><strong>{project.currency}</strong></div>
        </section>

        {!configuration ? (
          <section className="panel form-panel"><h2>No configuration revision</h2><p className="muted">Create the first draft. Activation remains unavailable until the server confirms readiness.</p><button className="button primary" onClick={() => void createDraft()}>Create draft configuration</button></section>
        ) : (
          <div className="content-grid">
            <section className="panel form-panel">
              <div className="panel-heading"><div><span className="eyebrow">Version {configuration.version}</span><h2>Basic drilling intervals</h2></div><span className={`state-badge state-${mutable ? "draft" : "locked"}`}>{mutable ? "editable" : "immutable"}</span></div>
              <p className="muted">Only confirmed foundation fields are recorded. Leave measured depths blank when unavailable; Vantix will not infer them.</p>
              {configuration.data.intervals.map((interval) => (
                <fieldset className="interval-card" key={interval.id} disabled={!mutable}>
                  <legend>{interval.name || "New interval"}</legend>
                  <div className="form-grid">
                    <label>Interval name<input value={interval.name} onChange={(event) => updateInterval(interval.id, { name: event.target.value })} /></label>
                    <label>Operation mode<input value={interval.operation_mode} onChange={(event) => updateInterval(interval.id, { operation_mode: event.target.value })} /></label>
                    <label>Top MD ({interval.top_md?.unit ?? projectDepthUnit}, optional)<input inputMode="decimal" value={interval.top_md?.value ?? ""} onChange={(event) => updateInterval(interval.id, { top_md: event.target.value ? { value: event.target.value, unit: interval.top_md?.unit ?? projectDepthUnit, provenance: "entered" } : undefined })} placeholder="Unavailable" /></label>
                    <label>Bottom MD ({interval.bottom_md?.unit ?? interval.top_md?.unit ?? projectDepthUnit}, optional)<input inputMode="decimal" value={interval.bottom_md?.value ?? ""} onChange={(event) => updateInterval(interval.id, { bottom_md: event.target.value ? { value: event.target.value, unit: interval.bottom_md?.unit ?? interval.top_md?.unit ?? projectDepthUnit, provenance: "entered" } : undefined })} placeholder="Unavailable" /></label>
                  </div>
                  <label className="default-choice"><input type="radio" name="default-interval" checked={configuration.data.default_interval_id === interval.id} onChange={() => updateConfiguration({ ...configuration, data: { ...configuration.data, default_interval_id: interval.id } })} /> Default interval for new report days</label>
                </fieldset>
              ))}
              <div className="button-row">
                <button className="button ghost" disabled={!mutable} onClick={() => updateConfiguration({ ...configuration, data: { ...configuration.data, intervals: [...configuration.data.intervals, newInterval()] } })}>Add interval</button>
                <button className="button secondary" disabled={!mutable} onClick={() => void save()}>Save draft</button>
                <button className="button ghost" onClick={() => void validate()}>Validate readiness</button>
                <button className="button primary" disabled={!mutable || readiness?.can_activate !== true} onClick={() => void activate()}>Activate and freeze snapshot</button>
                {!mutable && <button className="button secondary" onClick={() => void createDraft()}>Create revised draft</button>}
              </div>
            </section>
            <aside className="panel readiness-panel">
              <div className="panel-heading"><div><span className="eyebrow">Server evaluation</span><h2>Activation readiness</h2></div><span className={`state-badge state-${readiness?.state ?? "incomplete"}`}>{readiness?.state ?? "not checked"}</span></div>
              {!readiness ? <p className="muted">Save, then validate to see exact blocking fields.</p> : readiness.issues.length === 0 ? <div className="ready-message"><strong>Ready to activate</strong><span>The next report day will bind to this immutable snapshot.</span></div> : <ul className="issue-list">{readiness.issues.map((issue) => <li key={`${issue.code}-${issue.field}`}><strong>{issue.field}</strong><span>{issue.message}</span></li>)}</ul>}
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
