import { useEffect, useRef, useState } from "react";

import { ApiError, api, type Session } from "./api";
import ProductPricingGrid from "./ProductPricingGrid";
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
  const [dirty, setDirty] = useState(false);
  const [productDirty, setProductDirty] = useState(false);
  const [pending, setPending] = useState<"create" | "save" | "validate" | "activate" | "product">();
  const pendingRef = useRef(false);
  const productDirtyRef = useRef(false);
  const createKey = useRef(crypto.randomUUID());
  const activationKey = useRef(crypto.randomUUID());
  const mutable = configuration?.state === "draft";
  const busy = pending !== undefined;
  const projectDepthUnit: "m" | "ft" = project?.unit_set === "Field" ? "ft" : "m";

  function beginPending(operation: "create" | "save" | "validate" | "activate" | "product") {
    if (pendingRef.current) return false;
    pendingRef.current = true;
    setPending(operation);
    return true;
  }

  function endPending() {
    pendingRef.current = false;
    setPending(undefined);
  }

  function setProductPending(value: boolean) {
    if (value) {
      pendingRef.current = true;
      setPending("product");
    } else {
      endPending();
    }
  }

  function productSaved(rowVersion: number) {
    setConfiguration((current) => current ? { ...current, row_version: rowVersion } : current);
    activationKey.current = crypto.randomUUID();
    setReadiness(undefined);
    setMessage("Saved");
  }

  function productDirtyChanged(value: boolean) {
    productDirtyRef.current = value;
    setProductDirty(value);
    if (value) {
      setReadiness(undefined);
      setMessage("Unsaved product or price changes");
    }
  }

  useEffect(() => {
    Promise.all([api.getProject(session, projectId), api.listConfigurations(session, projectId)])
      .then(([nextProject, versions]) => {
        setProject(nextProject);
        setConfiguration(versions.find((item) => item.state === "draft") ?? versions[0]);
        setDirty(false);
        setMessage(versions.length ? "Saved" : "Create a draft configuration to begin.");
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Unable to load."));
  }, [projectId, session]);

  function updateInterval(id: string, patch: Partial<BasicInterval>) {
    if (!configuration || !mutable || pendingRef.current) return;
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
    setDirty(true);
    setMessage("Unsaved changes");
  }

  function updateConfiguration(next: Configuration) {
    if (!mutable || pendingRef.current) return;
    setConfiguration(next);
    setReadiness(undefined);
    setDirty(true);
    setMessage("Unsaved changes");
  }

  async function createDraft() {
    if (!beginPending("create")) return;
    setMessage("Creating draft…");
    try {
      setConfiguration(await api.createConfiguration(session, projectId, createKey.current));
      createKey.current = crypto.randomUUID();
      activationKey.current = crypto.randomUUID();
      setReadiness(undefined);
      setDirty(false);
      setMessage("Draft created");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to create draft.");
    } finally {
      endPending();
    }
  }

  async function save() {
    if (!configuration || !dirty || !beginPending("save")) return;
    setMessage("Saving…");
    try {
      const saved = await api.saveConfiguration(session, configuration);
      setConfiguration(saved);
      activationKey.current = crypto.randomUUID();
      setDirty(false);
      setMessage("Saved");
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.code === "CONFIGURATION_VERSION_CONFLICT"
          ? "Conflict — reload before saving"
          : error instanceof Error ? error.message : "Save failed",
      );
    } finally {
      endPending();
    }
  }

  async function validate() {
    if (!configuration || dirty || productDirtyRef.current || !beginPending("validate")) return;
    setMessage("Validating…");
    try {
      setReadiness(await api.validateConfiguration(session, configuration));
      setMessage("Validation complete");
    } catch (error) {
      setReadiness(undefined);
      setMessage(error instanceof Error ? error.message : "Validation failed");
    } finally {
      endPending();
    }
  }

  async function activate() {
    if (!configuration || !readiness || dirty || productDirtyRef.current || !beginPending("activate")) return;
    setMessage("Activating…");
    try {
      const next = await api.activateConfiguration(
        session,
        configuration,
        readiness,
        activationKey.current,
      );
      setConfiguration(next);
      setReadiness(undefined);
      setDirty(false);
      setMessage("Active snapshot frozen");
    } catch (error) {
      if (error instanceof ApiError && error.code === "CONFIGURATION_VERSION_CONFLICT") {
        setReadiness(undefined);
      }
      setMessage(error instanceof Error ? error.message : "Activation failed");
    } finally {
      endPending();
    }
  }

  function removeInterval(id: string) {
    if (!configuration || !mutable || pendingRef.current) return;
    const intervals = configuration.data.intervals.filter((item) => item.id !== id);
    updateConfiguration({
      ...configuration,
      data: {
        ...configuration.data,
        intervals,
        default_interval_id:
          configuration.data.default_interval_id === id
            ? (intervals[0]?.id ?? null)
            : configuration.data.default_interval_id,
      },
    });
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
          <section className="panel form-panel"><h2>No configuration revision</h2><p className="muted">Create the first draft. Activation remains unavailable until the server confirms readiness.</p><button className="button primary" disabled={busy} onClick={() => void createDraft()}>Create draft configuration</button></section>
        ) : (
          <div className="content-grid">
            <section className="panel form-panel">
              <div className="panel-heading"><div><span className="eyebrow">Version {configuration.version}</span><h2>Basic drilling intervals</h2></div><span className={`state-badge state-${mutable ? "draft" : "locked"}`}>{mutable ? "editable" : "immutable"}</span></div>
              <p className="muted">Only confirmed foundation fields are recorded. Leave measured depths blank when unavailable; Vantix will not infer them.</p>
              {configuration.data.intervals.map((interval) => (
                <fieldset className="interval-card" key={interval.id} disabled={!mutable || busy}>
                  <legend>{interval.name || "New interval"}</legend>
                  <div className="form-grid">
                    <label>Interval name<input value={interval.name} onChange={(event) => updateInterval(interval.id, { name: event.target.value })} /></label>
                    <label>Operation mode<select value={interval.operation_mode} onChange={(event) => updateInterval(interval.id, { operation_mode: event.target.value as BasicInterval["operation_mode"] })}><option value="drilling">Drilling</option><option value="completion">Completion</option><option value="workover">Workover</option></select></label>
                    <label>Top MD (optional)<span className="unit-input"><input inputMode="decimal" min="0" value={interval.top_md?.value ?? ""} onChange={(event) => updateInterval(interval.id, { top_md: event.target.value ? { value: event.target.value, unit: interval.top_md?.unit ?? projectDepthUnit, provenance: "entered" } : undefined })} placeholder="Unavailable" /><select aria-label={`Top MD unit for ${interval.name || "new interval"}`} value={interval.top_md?.unit ?? projectDepthUnit} onChange={(event) => interval.top_md && updateInterval(interval.id, { top_md: { ...interval.top_md, unit: event.target.value as "m" | "ft" } })}><option value="m">m</option><option value="ft">ft</option></select></span></label>
                    <label>Bottom MD (optional)<span className="unit-input"><input inputMode="decimal" min="0" value={interval.bottom_md?.value ?? ""} onChange={(event) => updateInterval(interval.id, { bottom_md: event.target.value ? { value: event.target.value, unit: interval.bottom_md?.unit ?? interval.top_md?.unit ?? projectDepthUnit, provenance: "entered" } : undefined })} placeholder="Unavailable" /><select aria-label={`Bottom MD unit for ${interval.name || "new interval"}`} value={interval.bottom_md?.unit ?? interval.top_md?.unit ?? projectDepthUnit} onChange={(event) => interval.bottom_md && updateInterval(interval.id, { bottom_md: { ...interval.bottom_md, unit: event.target.value as "m" | "ft" } })}><option value="m">m</option><option value="ft">ft</option></select></span></label>
                  </div>
                  <label className="default-choice"><input type="radio" name="default-interval" checked={configuration.data.default_interval_id === interval.id} onChange={() => updateConfiguration({ ...configuration, data: { ...configuration.data, default_interval_id: interval.id } })} /> Default interval for new report days</label>
                  <button className="button danger remove-interval" type="button" disabled={!mutable || busy} onClick={() => removeInterval(interval.id)}>Remove interval</button>
                </fieldset>
              ))}
              <div className="button-row">
                <button className="button ghost" disabled={!mutable || busy} onClick={() => updateConfiguration({ ...configuration, data: { ...configuration.data, intervals: [...configuration.data.intervals, newInterval()] } })}>Add interval</button>
                <button className="button secondary" disabled={!mutable || !dirty || busy} onClick={() => void save()}>Save draft</button>
                <button className="button ghost" disabled={dirty || productDirty || busy} onClick={() => void validate()}>Validate readiness</button>
                <button className="button primary" disabled={!mutable || dirty || productDirty || busy || readiness?.can_activate !== true || readiness.validated_version !== configuration.row_version} onClick={() => void activate()}>Activate and freeze snapshot</button>
                {!mutable && <button className="button secondary" disabled={busy} onClick={() => void createDraft()}>Create revised draft</button>}
              </div>
              <ProductPricingGrid
                configuration={configuration}
                currency={project.currency}
                session={session}
                disabled={!mutable || busy || dirty}
                onPendingChange={setProductPending}
                onSaved={productSaved}
                onDirtyChange={productDirtyChanged}
              />
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
