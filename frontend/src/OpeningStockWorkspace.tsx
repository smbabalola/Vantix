import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type Session } from "./api";
import type {
  InventoryPosting,
  OpeningStockAuthority,
  OpeningStockAuthorityProduct,
  ProductUnitCode,
} from "./types";

interface Props { projectId: string; session: Session }
interface Entry { quantity: string; unit: ProductUnitCode }

function today(): string { return new Date().toISOString().slice(0, 10); }

function compatibleUnits(product: OpeningStockAuthorityProduct): ProductUnitCode[] {
  const groups: ProductUnitCode[][] = [
    ["kg", "t", "lb"], ["L", "m3", "gal_us", "bbl"], ["each"],
  ];
  return ["package" as ProductUnitCode, ...(groups.find((group) => group.includes(product.package_unit_code)) ?? [])];
}

export default function OpeningStockWorkspace({ projectId, session }: Props) {
  const [postingDate, setPostingDate] = useState(today);
  const [authority, setAuthority] = useState<OpeningStockAuthority>();
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [history, setHistory] = useState<InventoryPosting[]>([]);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [reversalReason, setReversalReason] = useState("");
  const [reversalDate, setReversalDate] = useState(today);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.openingStockAuthority(session, projectId, postingDate),
      api.listInventoryPostings(session, projectId),
    ]).then(([nextAuthority, postings]) => {
      if (!active) return;
      setAuthority(nextAuthority); setHistory(postings);
      setEntries(Object.fromEntries(nextAuthority.products.map((product) => [
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
    return entry?.quantity && Number(entry.quantity) > 0 ? [{
      product_definition_id: product.product_definition_id,
      entered_quantity: entry.quantity,
      entered_unit_code: entry.unit,
    }] : [];
  }) ?? [], [authority, entries]);
  const activeOpening = history.find((posting) =>
    posting.posting_type === "opening_stock" && !posting.reversal_posting_id);

  function setPending(value: boolean) { busyRef.current = value; setBusy(value); }

  async function postOpening() {
    if (busyRef.current || selectedLines.length === 0 || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const posted = await api.postOpeningStock(
        session, projectId, postingDate, selectedLines, crypto.randomUUID(),
      );
      setHistory((current) => [...current, posted]);
      setNotice("Opening stock posted. Quantity and cost are now immutable.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Opening stock could not be posted.");
    } finally { setPending(false); }
  }

  async function reverseOpening() {
    if (busyRef.current || !activeOpening || !reversalReason.trim() || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const reversal = await api.reverseInventoryPosting(
        session, projectId, activeOpening.id, reversalDate, reversalReason.trim(), crypto.randomUUID(),
      );
      setHistory((current) => [
        ...current.map((item) => item.id === activeOpening.id
          ? { ...item, reversal_posting_id: reversal.id } : item), reversal,
      ]);
      setReversalReason(""); setNotice("Opening stock reversed by an exact opposite posting.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Reversal could not be posted.");
    } finally { setPending(false); }
  }

  return <main className="workspace inventory-workspace">
    <header className="workspace-header">
      <div><p className="eyebrow">Inventory authority</p><h1>Opening stock</h1>
        <p className="muted">Enter a verified opening position. Posting freezes product, quantity, price, and cost authority.</p></div>
      <label>Posting date<input type="date" value={postingDate} disabled={busy || !!activeOpening}
        onChange={(event) => { setError(undefined); setPostingDate(event.target.value); }} /></label>
    </header>
    {error && <div className="error-panel" role="alert">{error}</div>}
    {notice && <div className="ready-message" role="status">{notice}</div>}
    <section className="panel form-panel">
      <div className="panel-heading"><div><p className="eyebrow">Controlled products</p><h2>Opening quantities</h2></div>
        <span className={`state-badge ${activeOpening ? "state-locked" : "state-ready"}`}>
          {activeOpening ? "Already posted" : "Draft entry"}</span></div>
      {!authority && <p className="muted">Loading inventory authority…</p>}
      {authority?.products.length === 0 && <p className="muted">No active inventory products are available.</p>}
      {authority && authority.products.length > 0 && <div className="inventory-grid" role="table" aria-label="Opening stock entries">
        <div className="inventory-grid-header" role="row"><span>Product</span><span>Package</span><span>Quantity</span><span>Unit</span><span>Effective price</span></div>
        {authority.products.map((product) => {
          const entry = entries[product.product_definition_id];
          return <div className="inventory-grid-row" role="row" key={product.product_definition_id}>
            <div><strong>{product.item_code}</strong><small>{product.item_name}</small></div>
            <span>{product.package_size} {product.package_unit_code}</span>
            <label><span className="sr-only">{product.item_name} quantity</span><input type="number" min="0" step="any"
              value={entry?.quantity ?? ""} disabled={busy || !!activeOpening}
              onChange={(event) => setEntries((current) => ({ ...current,
                [product.product_definition_id]: { ...entry, quantity: event.target.value },
              }))} /></label>
            <label><span className="sr-only">{product.item_name} unit</span><select value={entry?.unit ?? product.inventory_unit_code}
              disabled={busy || !!activeOpening} onChange={(event) => setEntries((current) => ({ ...current,
                [product.product_definition_id]: { ...entry, unit: event.target.value as ProductUnitCode },
              }))}>{compatibleUnits(product).map((unit) => <option key={unit}>{unit}</option>)}</select></label>
            {product.price ? <div><span className="state-badge state-ready">Ready</span><small>
              {product.price.currency} {product.price.unit_price} / {product.price.price_basis_unit_code}</small></div>
              : <div><span className="state-badge state-incomplete">Unavailable</span><small>Quantity posts without cost</small></div>}
          </div>;
        })}
      </div>}
      <div className="button-row"><button className="button primary" disabled={busy || !!activeOpening || selectedLines.length === 0 || !navigator.onLine}
        onClick={() => void postOpening()}>{busy ? "Posting…" : "Post opening stock"}</button>
        {!navigator.onLine && <span className="muted">Posting requires an online server.</span>}</div>
    </section>
    {activeOpening && <section className="panel readiness-panel reversal-panel">
      <p className="eyebrow">Controlled correction</p><h2>Reverse opening stock</h2>
      <p className="muted">The original remains in history. Reversal posts every frozen line with the exact opposite quantity and amount.</p>
      <label>Reversal date<input type="date" min={activeOpening.posting_date} value={reversalDate}
        disabled={busy} onChange={(event) => setReversalDate(event.target.value)} /></label>
      <label>Reason<input value={reversalReason} disabled={busy} onChange={(event) => setReversalReason(event.target.value)} /></label>
      <button className="button danger" disabled={busy || !reversalReason.trim() || reversalDate < activeOpening.posting_date}
        onClick={() => void reverseOpening()}>Post exact reversal</button>
    </section>}
    <section className="panel readiness-panel inventory-history"><p className="eyebrow">Audit history</p><h2>Posted entries</h2>
      {history.length === 0 ? <p className="muted">No inventory postings yet.</p> : history.map((posting) =>
        <article key={posting.id}><strong>{posting.posting_type === "opening_stock" ? "Opening stock" : "Reversal"}</strong>
          <span>{posting.posting_date} · {posting.lines.length} line{posting.lines.length === 1 ? "" : "s"}</span>
          <span className="state-badge state-locked">Immutable</span></article>)}</section>
  </main>;
}
