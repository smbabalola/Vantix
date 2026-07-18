import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type Session } from "./api";
import type {
  InventoryPosting,
  OpeningStockAuthority,
  OpeningStockAuthorityProduct,
  OpeningStockPreview,
  ProductUnitCode,
} from "./types";

interface Props { projectId: string; session: Session }
interface Entry { quantity: string; unit: ProductUnitCode }
interface Attempt { signature: string; key: string }

function compatibleUnits(product: OpeningStockAuthorityProduct): ProductUnitCode[] {
  const groups: ProductUnitCode[][] = [
    ["kg", "t", "lb"], ["L", "m3", "gal_us", "bbl"], ["each"],
  ];
  return ["package", ...(groups.find((group) => group.includes(product.package_unit_code)) ?? [])];
}

function retryKey(reference: React.MutableRefObject<Attempt | undefined>, signature: string): string {
  if (reference.current?.signature !== signature) {
    reference.current = { signature, key: crypto.randomUUID() };
  }
  return reference.current.key;
}

export default function OpeningStockWorkspace({ projectId, session }: Props) {
  const [postingDate, setPostingDate] = useState("");
  const [authority, setAuthority] = useState<OpeningStockAuthority>();
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [history, setHistory] = useState<InventoryPosting[]>([]);
  const [preview, setPreview] = useState<OpeningStockPreview>();
  const [previewSignature, setPreviewSignature] = useState<string>();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const openingAttemptRef = useRef<Attempt | undefined>(undefined);
  const reversalAttemptRef = useRef<Attempt | undefined>(undefined);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [reversalReason, setReversalReason] = useState("");
  const [reversalDate, setReversalDate] = useState("");

  const loadHistory = useCallback(async () => {
    setHistory(await api.listInventoryPostings(session, projectId));
  }, [projectId, session]);

  const loadAuthority = useCallback(async (date: string) => {
    if (!date) { setAuthority(undefined); setEntries({}); return; }
    const next = await api.openingStockAuthority(session, projectId, date);
    setAuthority(next);
    setEntries(Object.fromEntries(next.products.map((product) => [
      product.product_definition_id,
      { quantity: "", unit: product.inventory_unit_code },
    ])));
  }, [projectId, session]);

  useEffect(() => {
    let active = true;
    void api.listInventoryPostings(session, projectId).then((postings) => {
      if (active) setHistory(postings);
    }).catch((caught) => active && setError(
      caught instanceof ApiError ? caught.message : "Unable to load inventory history.",
    ));
    return () => { active = false; };
  }, [projectId, session]);

  useEffect(() => {
    if (!postingDate) return;
    let active = true;
    void api.openingStockAuthority(session, projectId, postingDate).then((next) => {
      if (!active) return;
      setAuthority(next);
      setEntries(Object.fromEntries(next.products.map((product) => [
        product.product_definition_id,
        { quantity: "", unit: product.inventory_unit_code },
      ])));
    }).catch((caught) => active && setError(
      caught instanceof ApiError ? caught.message : "Unable to load opening-stock authority.",
    ));
    return () => { active = false; };
  }, [postingDate, projectId, session]);

  const selectedLines = useMemo(() => authority?.products.flatMap((product) => {
    const entry = entries[product.product_definition_id];
    return !product.opened_by_posting_id && entry?.quantity && Number(entry.quantity) > 0 ? [{
      product_definition_id: product.product_definition_id,
      entered_quantity: entry.quantity,
      entered_unit_code: entry.unit,
    }] : [];
  }) ?? [], [authority, entries]);
  const requestSignature = useMemo(() => JSON.stringify({
    snapshot: authority?.configuration_snapshot_id, postingDate, lines: selectedLines,
  }), [authority?.configuration_snapshot_id, postingDate, selectedLines]);
  const activeOpenings = history.filter((posting) =>
    posting.posting_type === "opening_stock" && !posting.reversal_posting_id);
  const previewIsCurrent = previewSignature === requestSignature;

  function setPending(value: boolean) { busyRef.current = value; setBusy(value); }
  function invalidatePreview() { setPreview(undefined); setPreviewSignature(undefined); }

  async function previewOpening() {
    if (busyRef.current || !authority || selectedLines.length === 0 || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const result = await api.previewOpeningStock(
        session, projectId, postingDate, authority.configuration_snapshot_id, selectedLines,
      );
      setPreview(result); setPreviewSignature(requestSignature);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "INVENTORY_AUTHORITY_CHANGED") {
        await loadAuthority(postingDate); openingAttemptRef.current = undefined;
        setError("Configuration authority changed. Review the reloaded products and preview again.");
      } else {
        setError(caught instanceof ApiError ? caught.message : "Opening preview could not be calculated.");
      }
    } finally { setPending(false); }
  }

  async function postOpening() {
    if (busyRef.current || !authority || !previewIsCurrent || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const posted = await api.postOpeningStock(
        session, projectId, postingDate, authority.configuration_snapshot_id, selectedLines,
        retryKey(openingAttemptRef, requestSignature),
      );
      openingAttemptRef.current = undefined; invalidatePreview();
      await Promise.all([loadHistory(), loadAuthority(postingDate)]);
      setNotice(`Opening stock ${posted.id} posted. Quantity and cost are now immutable.`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "INVENTORY_AUTHORITY_CHANGED") {
        await loadAuthority(postingDate); openingAttemptRef.current = undefined; invalidatePreview();
        setError("Configuration authority changed. Review the reloaded products and preview again.");
      } else {
        setError(caught instanceof ApiError ? caught.message : "Opening stock could not be posted.");
      }
    } finally { setPending(false); }
  }

  async function reverseOpening(posting: InventoryPosting) {
    if (busyRef.current || !reversalReason.trim() || !reversalDate || !navigator.onLine) return;
    const signature = JSON.stringify({ id: posting.id, date: reversalDate, reason: reversalReason.trim() });
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const reversal = await api.reverseInventoryPosting(
        session, projectId, posting.id, reversalDate, reversalReason.trim(),
        retryKey(reversalAttemptRef, signature),
      );
      reversalAttemptRef.current = undefined; setReversalReason(""); setReversalDate("");
      await Promise.all([loadHistory(), postingDate ? loadAuthority(postingDate) : Promise.resolve()]);
      setNotice(`Reversal ${reversal.id} posted using the original frozen authority.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Reversal could not be posted.");
    } finally { setPending(false); }
  }

  return <main className="workspace inventory-workspace">
    <header className="workspace-header">
      <div><p className="eyebrow">Inventory authority</p><h1>Opening stock</h1>
        <p className="muted">Review the server-calculated conversion and value before creating an immutable posting.</p></div>
      <label>Posting date<input type="date" value={postingDate} disabled={busy}
        onChange={(event) => { setError(undefined); invalidatePreview(); setPostingDate(event.target.value); }} /></label>
    </header>
    {error && <div className="error-panel" role="alert">{error}</div>}
    {notice && <div className="ready-message" role="status">{notice}</div>}
    <section className="panel form-panel">
      <div className="panel-heading"><div><p className="eyebrow">Controlled products</p><h2>Opening quantities</h2></div>
        <span className="state-badge state-ready">Append-only</span></div>
      {!postingDate && <p className="muted">Choose and confirm an explicit posting date to load authority.</p>}
      {postingDate && !authority && <p className="muted">Loading inventory authority…</p>}
      {authority && <div className="context-strip inventory-context"><div><span>Source snapshot</span>
        <strong title={authority.configuration_snapshot_id}>{authority.configuration_snapshot_id}</strong></div>
        <div><span>Posting date</span><strong>{postingDate}</strong></div></div>}
      {authority?.products.length === 0 && <p className="muted">No active inventory products are available.</p>}
      {authority && authority.products.length > 0 && <div className="inventory-grid" role="table" aria-label="Opening stock entries">
        <div className="inventory-grid-header" role="row"><span>Product</span><span>Package</span><span>Quantity</span><span>Unit</span><span>Effective price</span></div>
        {authority.products.map((product) => {
          const entry = entries[product.product_definition_id]; const locked = !!product.opened_by_posting_id;
          return <div className="inventory-grid-row" role="row" key={product.product_definition_id}>
            <div><strong>{product.item_code}</strong><small>{product.item_name}</small>{locked && <small>Opened by {product.opened_by_posting_id}</small>}</div>
            <span>{product.package_size} {product.package_unit_code} / package</span>
            <label><span className="sr-only">{product.item_name} quantity</span><input type="number" min="0" step="any"
              value={entry?.quantity ?? ""} disabled={busy || locked}
              onChange={(event) => { invalidatePreview(); setEntries((current) => ({ ...current,
                [product.product_definition_id]: { ...entry, quantity: event.target.value },
              })); }} /></label>
            <label><span className="sr-only">{product.item_name} unit</span><select value={entry?.unit ?? product.inventory_unit_code}
              disabled={busy || locked} onChange={(event) => { invalidatePreview(); setEntries((current) => ({ ...current,
                [product.product_definition_id]: { ...entry, unit: event.target.value as ProductUnitCode },
              })); }}>{compatibleUnits(product).map((unit) => <option key={unit}>{unit}</option>)}</select></label>
            {locked ? <span className="state-badge state-locked">Already opened</span>
              : product.price ? <div><span className="state-badge state-ready">Ready</span><small>
                {product.price.currency} {product.price.unit_price} / {product.price.price_basis_unit_code}</small><small>
                {product.price.effective_from} → {product.price.effective_to ?? "open"}</small></div>
                : <div><span className="state-badge state-incomplete">Unavailable</span><small>Quantity posts without cost</small></div>}
          </div>;
        })}
      </div>}
      <div className="button-row"><button className="button secondary" disabled={busy || selectedLines.length === 0 || !navigator.onLine}
        onClick={() => void previewOpening()}>Preview frozen posting</button>
        <button className="button primary" disabled={busy || !previewIsCurrent || !navigator.onLine}
          onClick={() => void postOpening()}>{busy ? "Working…" : "Post opening stock"}</button>
        {!navigator.onLine && <span className="muted">Preview and posting require an online server.</span>}</div>
    </section>
    {preview && previewIsCurrent && <section className="panel readiness-panel inventory-preview">
      <p className="eyebrow">Server-authoritative preview</p><h2>Values that will be frozen</h2>
      {preview.lines.map((line) => <article key={line.product_definition_id}>
        <strong>{line.item_code} · {line.item_name}</strong>
        <span>{line.entered_quantity} {line.entered_unit_code} × {line.package_size} {line.package_unit_code}/package</span>
        <span>= {line.canonical_quantity} {line.canonical_unit_code} canonical ({line.package_count} packages)</span>
        {line.price_status === "ready" ? <span>{line.currency} {line.applied_unit_price}/{line.price_basis_unit_code}
          {` = ${line.currency} ${line.line_amount}`} · effective {line.price_effective_from} → {line.price_effective_to ?? "open"}</span>
          : <span className="state-badge state-incomplete">Cost unavailable — monetary fields remain null</span>}
      </article>)}
      {Object.entries(preview.currencies).map(([currency, total]) => <p key={currency}><strong>Total: {currency} {total}</strong></p>)}
    </section>}
    {activeOpenings.length > 0 && <section className="panel readiness-panel reversal-panel">
      <p className="eyebrow">Controlled correction</p><h2>Reverse an opening posting</h2>
      <label>Reversal date<input type="date" value={reversalDate} disabled={busy}
        onChange={(event) => { reversalAttemptRef.current = undefined; setReversalDate(event.target.value); }} /></label>
      <label>Reason<input value={reversalReason} disabled={busy}
        onChange={(event) => { reversalAttemptRef.current = undefined; setReversalReason(event.target.value); }} /></label>
      {activeOpenings.map((posting) => <button key={posting.id} className="button danger"
        disabled={busy || !reversalDate || !reversalReason.trim() || reversalDate < posting.posting_date}
        onClick={() => void reverseOpening(posting)}>Reverse posting {posting.id.slice(0, 8)}</button>)}
    </section>}
    <section className="panel readiness-panel inventory-history"><p className="eyebrow">Audit history</p><h2>Posted entries</h2>
      {history.length === 0 ? <p className="muted">No inventory postings yet.</p> : history.map((posting) =>
        <article className="inventory-history-card" key={posting.id}><header><strong>{posting.posting_type === "opening_stock" ? "Opening stock" : "Reversal"}</strong>
          <span>{posting.posting_date}</span><span className="state-badge state-locked">Immutable</span></header>
          <small>Snapshot {posting.source_configuration_snapshot_id}</small>
          {posting.reversal_of_posting_id && <small>Reverses {posting.reversal_of_posting_id}</small>}
          {posting.reversal_posting_id && <small>Reversed by {posting.reversal_posting_id}</small>}
          {posting.reason && <small>Reason: {posting.reason}</small>}
          {posting.lines.map((line) => <div className="history-line" key={line.id}><strong>{String(line.frozen_product.item_code)} · {String(line.frozen_product.item_name)}</strong>
            <span>{line.entered_quantity} {line.entered_unit_code} → {line.canonical_signed_quantity} {line.canonical_unit_code}</span>
            {line.price_status === "ready" ? <span>{line.currency} {line.applied_unit_price}/{line.price_basis_unit_code} = {line.currency} {line.posted_line_amount}
              {` · ${line.price_effective_from} → ${line.price_effective_to ?? "open"}`}</span>
              : <span>Cost unavailable</span>}</div>)}</article>)}</section>
  </main>;
}
