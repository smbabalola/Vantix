import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OpeningStockWorkspace from "./OpeningStockWorkspace";

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

function authority(price: object | null = null, openedBy: string | null = null) {
  return {
    project_id: projectId,
    posting_date: "2026-07-18",
    configuration_snapshot_id: snapshotId,
    products: [{
      product_definition_id: productId,
      configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
      item_code: "BAR-001", item_name: "Barite", package_size: "25",
      package_unit_code: "kg", inventory_unit_code: "package", price,
      opened_by_posting_id: openedBy,
    }],
  };
}

const price = {
  id: "00000000-0000-4000-8000-000000000007",
  project_product_id: "00000000-0000-4000-8000-000000000006",
  effective_from: "2026-01-01", effective_to: null, unit_price: "18.5",
  currency: "GBP", price_basis_unit_code: "package", source: null,
};

const preview = {
  project_id: projectId, posting_date: "2026-07-18", configuration_snapshot_id: snapshotId,
  lines: [{ product_definition_id: productId,
    configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
    item_code: "BAR-001", item_name: "Barite", entered_quantity: "4",
    entered_unit_code: "package", package_size: "25", package_unit_code: "kg",
    canonical_quantity: "100", canonical_unit_code: "kg", package_count: "4",
    price_status: "ready", applied_unit_price: "18.5", price_basis_unit_code: "package",
    price_effective_from: "2026-01-01", price_effective_to: null,
    currency: "GBP", currency_minor_unit_scale: 2, line_amount: "74.00" }],
  currencies: { GBP: "74.00" },
};

function posting(id = "00000000-0000-4000-8000-000000000008") {
  return {
    id, project_id: projectId, source_configuration_snapshot_id: snapshotId,
    posting_type: "opening_stock", status: "posted", posting_date: "2026-07-18",
    reversal_of_posting_id: null, reversal_posting_id: null, reason: null,
    posted_by: session.userId, posted_at: "2026-07-18T12:00:00Z", lines: [],
  };
}

async function loadDatedWorkspace(fetchMock: ReturnType<typeof vi.spyOn>) {
  render(<OpeningStockWorkspace projectId={projectId} session={session} />);
  expect(screen.getByText(/Choose and confirm an explicit posting date/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Posting date"), { target: { value: "2026-07-18" } });
  await screen.findByText("BAR-001");
  return fetchMock;
}

describe("opening-stock workspace", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("shows explicit units, unavailable cost, and locks only an already-opened lineage", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority(null, "00000000-0000-4000-8000-000000000099")));
    await loadDatedWorkspace(fetchMock);
    expect(screen.getByText("Already opened")).toBeInTheDocument();
    expect(screen.getByLabelText("Barite quantity")).toBeDisabled();
    expect(screen.getByText(/Opened by/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post opening stock" })).toBeDisabled();
  });

  it("requires and renders the exact server-authoritative conversion and cost preview", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority(price)))
      .mockImplementationOnce(() => response(preview));
    await loadDatedWorkspace(fetchMock);
    fireEvent.change(screen.getByLabelText("Barite quantity"), { target: { value: "4" } });
    expect(screen.getByRole("button", { name: "Post opening stock" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview frozen posting" }));
    expect(await screen.findByText(/100 kg canonical/)).toBeInTheDocument();
    expect(screen.getAllByText(/GBP 74.00/)).toHaveLength(2);
    expect(screen.getAllByText(/2026-01-01 → open/)).toHaveLength(2);
    expect(screen.getByText(`Source snapshot`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post opening stock" })).toBeEnabled();
  });

  it("reuses the opening idempotency key after an uncertain response", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority(price)))
      .mockImplementationOnce(() => response(preview))
      .mockImplementationOnce(() => response({ detail: { code: "NETWORK_UNCERTAIN", message: "Response lost" } }, 503))
      .mockImplementationOnce(() => response(posting(), 201))
      .mockImplementationOnce(() => response([posting()]))
      .mockImplementationOnce(() => response(authority(price, posting().id)));
    await loadDatedWorkspace(fetchMock);
    fireEvent.change(screen.getByLabelText("Barite quantity"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview frozen posting" }));
    await screen.findByText(/100 kg canonical/);
    fireEvent.click(screen.getByRole("button", { name: "Post opening stock" }));
    await screen.findByText("Response lost");
    fireEvent.click(screen.getByRole("button", { name: "Post opening stock" }));
    await screen.findByText(/Quantity and cost are now immutable/);
    const attempts = fetchMock.mock.calls.filter(([url, init]) =>
      String(url).endsWith("/inventory-postings/opening-stock") && init?.method === "POST");
    expect(attempts).toHaveLength(2);
    expect(new Headers(attempts[0][1]?.headers).get("Idempotency-Key"))
      .toBe(new Headers(attempts[1][1]?.headers).get("Idempotency-Key"));
  });

  it("reuses the reversal idempotency key after an uncertain response", async () => {
    const original = posting();
    const reversal = { ...posting("00000000-0000-4000-8000-000000000010"),
      posting_type: "reversal", posting_date: "2026-07-19",
      reversal_of_posting_id: original.id, reason: "Count correction" };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([original]))
      .mockImplementationOnce(() => response({ detail: { code: "NETWORK_UNCERTAIN", message: "Response lost" } }, 503))
      .mockImplementationOnce(() => response(reversal, 201))
      .mockImplementationOnce(() => response([]));
    render(<OpeningStockWorkspace projectId={projectId} session={session} />);
    await screen.findByText(/Reverse posting/);
    fireEvent.change(screen.getByLabelText("Reversal date"), { target: { value: "2026-07-19" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Count correction" } });
    fireEvent.click(screen.getByRole("button", { name: /Reverse posting/ }));
    await screen.findByText("Response lost");
    fireEvent.click(screen.getByRole("button", { name: /Reverse posting/ }));
    await screen.findByText(/using the original frozen authority/);
    const attempts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/reversals"));
    expect(attempts).toHaveLength(2);
    expect(new Headers(attempts[0][1]?.headers).get("Idempotency-Key"))
      .toBe(new Headers(attempts[1][1]?.headers).get("Idempotency-Key"));
  });

  it("forces an authority reload after the reviewed snapshot changes", async () => {
    const replacementSnapshot = "00000000-0000-4000-8000-000000000055";
    const replacement = {
      ...authority(price),
      configuration_snapshot_id: replacementSnapshot,
      products: [{ ...authority(price).products[0], package_size: "50" }],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(authority(price)))
      .mockImplementationOnce(() => response({
        detail: { code: "INVENTORY_AUTHORITY_CHANGED", message: "Authority changed" },
      }, 412))
      .mockImplementationOnce(() => response(replacement));
    await loadDatedWorkspace(fetchMock);
    fireEvent.change(screen.getByLabelText("Barite quantity"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview frozen posting" }));
    expect(await screen.findByText(/Review the reloaded products/)).toBeInTheDocument();
    expect(screen.getByTitle(replacementSnapshot)).toBeInTheDocument();
    expect(screen.getByText("50 kg / package")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post opening stock" })).toBeDisabled();
  });
});
