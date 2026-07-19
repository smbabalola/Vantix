import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, type Session } from "./api";
import type {
  InventoryPosting,
  ProductUnitCode,
  ReceiptAuthority,
  ReceiptInput,
  ReceiptLineInput,
  ReceiptPreview,
} from "./types";

interface Props { projectId: string; session: Session }
interface Attempt { signature: string; key: string }
interface Entry {
  quantity: string;
  unit: ProductUnitCode;
  batch: string;
  manufactureDate: string;
  expiryDate: string;
  supplierPrice: string;
  priceBasis: ProductUnitCode;
}

function compatibleUnits(unit: ProductUnitCode): ProductUnitCode[] {
  const groups: ProductUnitCode[][] = [["kg", "t", "lb"], ["L", "m3", "gal_us", "bbl"], ["each"]];
  return ["package", ...(groups.find((group) => group.includes(unit)) ?? [])];
}

function retryKey(ref: React.MutableRefObject<Attempt | undefined>, signature: string) {
  if (ref.current?.signature !== signature) ref.current = { signature, key: crypto.randomUUID() };
  return ref.current.key;
}

export default function ReceiptWorkspace({ projectId, session }: Props) {
  const [postingDate, setPostingDate] = useState("");
  const [supplier, setSupplier] = useState("");
  const [deliveryNote, setDeliveryNote] = useState("");
  const [purchaseOrder, setPurchaseOrder] = useState("");
  const [invoice, setInvoice] = useState("");
  const [authority, setAuthority] = useState<ReceiptAuthority>();
  const [entries, setEntries] = useState<Record<string, Entry>>({});
  const [preview, setPreview] = useState<ReceiptPreview>();
  const [previewSignature, setPreviewSignature] = useState<string>();
  const [history, setHistory] = useState<InventoryPosting[]>([]);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const attemptRef = useRef<Attempt | undefined>(undefined);
  const reversalAttemptRef = useRef<Attempt | undefined>(undefined);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [reversalDate, setReversalDate] = useState("");
  const [reversalReason, setReversalReason] = useState("");

  const loadHistory = useCallback(async () => {
    setHistory(await api.listInventoryPostings(session, projectId));
  }, [projectId, session]);

  const loadAuthority = useCallback(async (value: string) => {
    if (!value) { setAuthority(undefined); setEntries({}); return; }
    const next = await api.receiptAuthority(session, projectId, value);
    setAuthority(next);
    setEntries(Object.fromEntries(next.products.map((product) => [product.product_definition_id, {
      quantity: "", unit: product.inventory_unit_code, batch: "", manufactureDate: "",
      expiryDate: "", supplierPrice: "", priceBasis: "package" as ProductUnitCode,
    }])));
  }, [projectId, session]);

  useEffect(() => {
    let active = true;
    void api.listInventoryPostings(session, projectId).then((items) => {
      if (active) setHistory(items);
    }).catch(() => { if (active) setError("Unable to load receipt history."); });
    return () => { active = false; };
  }, [projectId, session]);
  useEffect(() => {
    if (!postingDate) return;
    let active = true;
    void api.receiptAuthority(session, projectId, postingDate).then((next) => {
      if (!active) return;
      setAuthority(next);
      setEntries(Object.fromEntries(next.products.map((product) => [product.product_definition_id, {
        quantity: "", unit: product.inventory_unit_code, batch: "", manufactureDate: "",
        expiryDate: "", supplierPrice: "", priceBasis: "package" as ProductUnitCode,
      }])));
    }).catch((caught) => { if (active) setError(
      caught instanceof ApiError ? caught.message : "Unable to load receipt authority.",
    ); });
    return () => { active = false; };
  }, [postingDate, projectId, session]);

  const lines = useMemo<ReceiptLineInput[]>(() => authority?.products.flatMap((product) => {
    const entry = entries[product.product_definition_id];
    if (!entry?.quantity || Number(entry.quantity) <= 0) return [];
    return [{
      product_definition_id: product.product_definition_id,
      entered_quantity: entry.quantity,
      entered_unit_code: entry.unit,
      ...(entry.batch ? { batch_number: entry.batch } : {}),
      ...(entry.manufactureDate ? { manufacture_date: entry.manufactureDate } : {}),
      ...(entry.expiryDate ? { expiry_date: entry.expiryDate } : {}),
      ...(entry.supplierPrice ? { supplier_price: {
        unit_price: entry.supplierPrice,
        price_basis_unit_code: entry.priceBasis,
        currency: authority.project_currency,
      } } : {}),
    }];
  }) ?? [], [authority, entries]);
  const request = useMemo<ReceiptInput | undefined>(() => authority ? {
    expected_configuration_snapshot_id: authority.configuration_snapshot_id,
    posting_date: postingDate,
    supplier_name: supplier,
    delivery_note_number: deliveryNote,
    ...(purchaseOrder ? { purchase_order_reference: purchaseOrder } : {}),
    ...(invoice ? { invoice_reference: invoice } : {}),
    lines,
  } : undefined, [authority, deliveryNote, invoice, lines, postingDate, purchaseOrder, supplier]);
  const signature = JSON.stringify(request);
  const previewIsCurrent = !!preview && previewSignature === signature;
  const detailsComplete = !!postingDate && !!supplier.trim() && !!deliveryNote.trim();

  function setPending(value: boolean) { busyRef.current = value; setBusy(value); }
  function invalidate() { setPreview(undefined); setPreviewSignature(undefined); }
  function updateEntry(id: string, patch: Partial<Entry>) {
    if (busyRef.current) return;
    invalidate();
    setEntries((current) => ({ ...current, [id]: { ...current[id], ...patch } }));
  }

  async function previewReceipt() {
    if (busyRef.current || !request || !detailsComplete || lines.length === 0 || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const result = await api.previewReceipt(session, projectId, request);
      setPreview(result); setPreviewSignature(signature);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "INVENTORY_AUTHORITY_CHANGED") {
        await loadAuthority(postingDate); attemptRef.current = undefined; invalidate();
        setError("Configuration authority changed. Review the reloaded receipt and preview again.");
      } else setError(caught instanceof ApiError ? caught.message : "Receipt preview failed.");
    } finally { setPending(false); }
  }

  async function postReceipt() {
    if (busyRef.current || !request || !previewIsCurrent || !navigator.onLine) return;
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const posted = await api.postReceipt(
        session, projectId, request, retryKey(attemptRef, signature),
      );
      attemptRef.current = undefined; invalidate();
      await Promise.all([loadHistory(), loadAuthority(postingDate)]);
      setNotice(`Receipt ${posted.id} posted. Quantity and cost authority are immutable.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Receipt could not be posted.");
    } finally { setPending(false); }
  }

  async function reverseReceipt(posting: InventoryPosting) {
    if (busyRef.current || !reversalDate || !reversalReason.trim() || !navigator.onLine) return;
    const reversalSignature = JSON.stringify({
      postingId: posting.id, postingDate: reversalDate, reason: reversalReason.trim(),
    });
    setPending(true); setError(undefined); setNotice(undefined);
    try {
      const reversal = await api.reverseInventoryPosting(
        session, projectId, posting.id, reversalDate, reversalReason.trim(),
        retryKey(reversalAttemptRef, reversalSignature),
      );
      reversalAttemptRef.current = undefined; setReversalDate(""); setReversalReason("");
      await loadHistory();
      setNotice(`Reversal ${reversal.id} posted from the original frozen receipt authority.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Receipt reversal failed.");
    } finally { setPending(false); }
  }

  const receipts = history.filter((item) => item.posting_type === "receipt");
  const reversibleReceipts = receipts.filter((item) => !item.reversal_posting_id);
  return <main className="workspace inventory-workspace receipt-workspace">
    <header className="workspace-header"><div><p className="eyebrow">Inventory ledger</p><h1>Supplier receipts</h1>
      <p className="muted">Receipt details → lines → server preview → immutable posting</p></div></header>
    {error && <div className="error-panel" role="alert">{error}</div>}
    {notice && <div className="ready-message" role="status">{notice}</div>}
    <fieldset className="panel form-panel" disabled={busy}>
      <div className="panel-heading"><div><p className="eyebrow">Stage 1</p><h2>Receipt details</h2></div></div>
      <div className="form-grid">
        <label>Posting date<input type="date" value={postingDate} onChange={(event) => { invalidate(); setPostingDate(event.target.value); }} /></label>
        <label>Supplier<input value={supplier} onChange={(event) => { invalidate(); setSupplier(event.target.value); }} /></label>
        <label>Delivery note<input value={deliveryNote} onChange={(event) => { invalidate(); setDeliveryNote(event.target.value); }} /></label>
        <label>Purchase order (optional)<input value={purchaseOrder} onChange={(event) => { invalidate(); setPurchaseOrder(event.target.value); }} /></label>
        <label>Invoice (optional)<input value={invoice} onChange={(event) => { invalidate(); setInvoice(event.target.value); }} /></label>
      </div>
    </fieldset>
    <section className="panel form-panel"><div className="panel-heading"><div><p className="eyebrow">Stage 2</p><h2>Receipt lines</h2></div>
      <span className="state-badge state-ready">Append-only</span></div>
      {!postingDate && <p className="muted">Choose the explicit posting date to load controlled products.</p>}
      {authority && <div className="context-strip inventory-context"><div><span>Source snapshot</span><strong title={authority.configuration_snapshot_id}>{authority.configuration_snapshot_id}</strong></div></div>}
      {authority?.products.map((product) => { const entry = entries[product.product_definition_id]; return <fieldset disabled={busy} className="receipt-line" key={product.product_definition_id}>
        <legend><strong>{product.item_code} · {product.item_name}</strong> — {product.package_size} {product.package_unit_code}/package {product.price ? `· configured ${product.price.currency} ${product.price.unit_price}/${product.price.price_basis_unit_code}` : "· configured cost unavailable"}</legend>
        <label>Received quantity<input aria-label={`${product.item_name} received quantity`} type="number" min="0" step="any" value={entry?.quantity ?? ""} onChange={(e) => updateEntry(product.product_definition_id, { quantity: e.target.value })} /></label>
        <label>Unit<select aria-label={`${product.item_name} received unit`} value={entry?.unit ?? "package"} onChange={(e) => updateEntry(product.product_definition_id, { unit: e.target.value as ProductUnitCode })}>{compatibleUnits(product.package_unit_code).map((unit) => <option key={unit}>{unit}</option>)}</select></label>
        <label>Batch / lot<input value={entry?.batch ?? ""} onChange={(e) => updateEntry(product.product_definition_id, { batch: e.target.value })} /></label>
        <label>Manufactured<input type="date" value={entry?.manufactureDate ?? ""} onChange={(e) => updateEntry(product.product_definition_id, { manufactureDate: e.target.value })} /></label>
        <label>Expires<input type="date" value={entry?.expiryDate ?? ""} onChange={(e) => updateEntry(product.product_definition_id, { expiryDate: e.target.value })} /></label>
        <label>Supplier unit price (optional)<input type="number" min="0" step="any" value={entry?.supplierPrice ?? ""} onChange={(e) => updateEntry(product.product_definition_id, { supplierPrice: e.target.value })} /></label>
        <label>Price basis<select value={entry?.priceBasis ?? "package"} disabled={!entry?.supplierPrice} onChange={(e) => updateEntry(product.product_definition_id, { priceBasis: e.target.value as ProductUnitCode })}>{compatibleUnits(product.package_unit_code).map((unit) => <option key={unit}>{unit}</option>)}</select></label>
      </fieldset>; })}
      <div className="button-row"><button className="button secondary" disabled={busy || !detailsComplete || lines.length === 0 || !navigator.onLine} onClick={() => void previewReceipt()}>Preview receipt</button>
        <button className="button primary" disabled={busy || !previewIsCurrent || !navigator.onLine} onClick={() => void postReceipt()}>{busy ? "Working…" : "Post immutable receipt"}</button></div>
    </section>
    {previewIsCurrent && preview && <section className="panel readiness-panel inventory-preview"><p className="eyebrow">Stage 3 · Server-authoritative preview</p><h2>Frozen receipt</h2>
      {preview.lines.map((line) => <article key={`${line.product_definition_id}-${line.batch_number ?? ""}`}><strong>{line.item_code} · {line.item_name}</strong>
        <span>{line.entered_quantity} {line.entered_unit_code} × {line.package_size} {line.package_unit_code}/package</span>
        <span>= {line.canonical_quantity} {line.canonical_unit_code} canonical ({line.package_count} packages)</span>
        <span>Cost source: {line.cost_source.replaceAll("_", " ")}</span>
        {line.line_amount ? <span>{line.currency} {line.applied_unit_price}/{line.price_basis_unit_code} = {line.currency} {line.line_amount}</span>
          : <span className="state-badge state-incomplete">Cost unavailable — never recorded as zero</span>}</article>)}
      {Object.entries(preview.currencies).map(([currency, total]) => <p key={currency}><strong>Total: {currency} {total}</strong></p>)}</section>}
    {reversibleReceipts.length > 0 && <section className="panel readiness-panel reversal-panel"><p className="eyebrow">Controlled correction</p><h2>Reverse a supplier receipt</h2>
      <label>Reversal date<input type="date" value={reversalDate} disabled={busy} onChange={(event) => { reversalAttemptRef.current = undefined; setReversalDate(event.target.value); }} /></label>
      <label>Reversal reason<input value={reversalReason} disabled={busy} onChange={(event) => { reversalAttemptRef.current = undefined; setReversalReason(event.target.value); }} /></label>
      {reversibleReceipts.map((posting) => <button className="button danger" key={posting.id} disabled={busy || !reversalDate || !reversalReason.trim() || reversalDate < posting.posting_date} onClick={() => void reverseReceipt(posting)}>Reverse {posting.supplier_name} · {posting.delivery_note_number}</button>)}</section>}
    <section className="panel readiness-panel inventory-history"><p className="eyebrow">Audit history</p><h2>Supplier receipts</h2>
      {receipts.length === 0 ? <p className="muted">No supplier receipts posted.</p> : receipts.map((posting) => <details className="inventory-history-card" key={posting.id}><summary><strong>{posting.supplier_name} · {posting.delivery_note_number}</strong> — {posting.posting_date}</summary>
        <small>Snapshot {posting.source_configuration_snapshot_id}</small><small> · Received by {posting.received_by_user_id}</small>
        {posting.reversal_posting_id && <small> · Reversed by {posting.reversal_posting_id}</small>}
        {posting.lines.map((line) => <div className="history-line" key={line.id}><strong>{String(line.frozen_product.item_name)}</strong><span>{line.entered_quantity} {line.entered_unit_code} → {line.canonical_signed_quantity} {line.canonical_unit_code}</span><span>{line.cost_source.replaceAll("_", " ")} · {line.currency ? `${line.currency} ${line.posted_line_amount}` : "cost unavailable"}</span></div>)}</details>)}</section>
  </main>;
}
