import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReceiptWorkspace from "./ReceiptWorkspace";

const session = {
  userId: "00000000-0000-4000-8000-000000000001",
  organisationId: "00000000-0000-4000-8000-000000000002",
  capabilities: ["view_inventory", "post_inventory"],
};
const projectId = "00000000-0000-4000-8000-000000000003";
const productId = "00000000-0000-4000-8000-000000000004";
const snapshotId = "00000000-0000-4000-8000-000000000005";

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

const authority = {
  project_id: projectId,
  posting_date: "2026-07-18",
  configuration_snapshot_id: snapshotId,
  project_currency: "GBP",
  products: [{
    product_definition_id: productId,
    configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
    item_code: "BAR-001", item_name: "Barite", package_size: "25",
    package_unit_code: "kg", inventory_unit_code: "package", opened_by_posting_id: null,
    price: { id: "00000000-0000-4000-8000-000000000007", project_product_id: productId,
      effective_from: "2026-01-01", effective_to: null, unit_price: "18.5", currency: "GBP",
      price_basis_unit_code: "package", source: null },
  }],
};

const preview = {
  project_id: projectId, posting_date: "2026-07-18", configuration_snapshot_id: snapshotId,
  supplier_name: "North Sea Chemicals", delivery_note_number: "DN-1001",
  purchase_order_reference: null, invoice_reference: null,
  lines: [{ product_definition_id: productId,
    configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
    item_code: "BAR-001", item_name: "Barite", entered_quantity: "40",
    entered_unit_code: "package", package_size: "25", package_unit_code: "kg",
    canonical_quantity: "1000", canonical_unit_code: "kg", package_count: "40",
    price_status: "ready", cost_source: "supplier_document", applied_unit_price: "17.8",
    price_basis_unit_code: "package", price_effective_from: null, price_effective_to: null,
    currency: "GBP", currency_minor_unit_scale: 2, line_amount: "712.00",
    batch_number: "LOT-A", manufacture_date: null, expiry_date: null }],
  currencies: { GBP: "712.00" },
};

describe("supplier receipt workspace", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("requires explicit documentary details and renders the server-frozen preview", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority))
      .mockImplementationOnce(() => response(preview));
    render(<ReceiptWorkspace projectId={projectId} session={session} />);
    expect(screen.getByText(/Choose the explicit posting date/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview receipt" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Posting date"), { target: { value: "2026-07-18" } });
    await screen.findByText(/BAR-001/);
    fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "North Sea Chemicals" } });
    fireEvent.change(screen.getByLabelText("Delivery note"), { target: { value: "DN-1001" } });
    fireEvent.change(screen.getByLabelText("Barite received quantity"), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText("Supplier unit price (optional)"), { target: { value: "17.80" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview receipt" }));
    expect(await screen.findByText(/1000 kg canonical/)).toBeInTheDocument();
    expect(screen.getByText(/Cost source: supplier document/)).toBeInTheDocument();
    expect(screen.getAllByText(/GBP 712.00/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Post immutable receipt" })).toBeEnabled();
  });

  it("keeps receipt controls disabled until a delayed preview settles", async () => {
    let completePreview!: () => void;
    const delayed = new Promise<Response>((resolve) => {
      completePreview = () => resolve(new Response(JSON.stringify(preview), { status: 200 }));
    });
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority))
      .mockImplementationOnce(() => delayed);
    render(<ReceiptWorkspace projectId={projectId} session={session} />);
    fireEvent.change(screen.getByLabelText("Posting date"), { target: { value: "2026-07-18" } });
    await screen.findByText(/BAR-001/);
    fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "Supplier A" } });
    fireEvent.change(screen.getByLabelText("Delivery note"), { target: { value: "DN-2" } });
    fireEvent.change(screen.getByLabelText("Barite received quantity"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview receipt" }));
    expect(screen.getByLabelText("Supplier")).toBeDisabled();
    expect(screen.getByLabelText("Barite received quantity")).toBeDisabled();
    completePreview();
    await screen.findByText(/1000 kg canonical/);
    expect(screen.getByLabelText("Supplier")).toBeEnabled();
  });
});
