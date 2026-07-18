import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OpeningStockWorkspace from "./OpeningStockWorkspace";

const session = {
  userId: "00000000-0000-4000-8000-000000000001",
  organisationId: "00000000-0000-4000-8000-000000000002",
  capabilities: ["view_inventory", "post_inventory"],
};
const projectId = "00000000-0000-4000-8000-000000000003";
const productId = "00000000-0000-4000-8000-000000000004";

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("opening-stock workspace", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("VTX-PRO-005 shows explicit units and honest unavailable-price state", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({
        project_id: projectId, posting_date: "2026-07-18",
        configuration_snapshot_id: "00000000-0000-4000-8000-000000000005",
        products: [{ product_definition_id: productId,
          configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
          item_code: "BAR-001", item_name: "Barite", package_size: "25",
          package_unit_code: "kg", inventory_unit_code: "package", price: null }],
      }))
      .mockImplementationOnce(() => response([]));
    render(<OpeningStockWorkspace projectId={projectId} session={session} />);
    expect(await screen.findByText("BAR-001")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Quantity posts without cost")).toBeInTheDocument();
    expect(screen.getByLabelText("Barite unit")).toHaveTextContent("package");
    expect(screen.getByRole("button", { name: "Post opening stock" })).toBeDisabled();
  });

  it("keeps all entry controls disabled until transactional posting settles", async () => {
    let finish!: (value: Response) => void;
    const deferred = new Promise<Response>((resolve) => { finish = resolve; });
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({
        project_id: projectId, posting_date: "2026-07-18",
        configuration_snapshot_id: "00000000-0000-4000-8000-000000000005",
        products: [{ product_definition_id: productId,
          configuration_product_version_id: "00000000-0000-4000-8000-000000000006",
          item_code: "BAR-001", item_name: "Barite", package_size: "25",
          package_unit_code: "kg", inventory_unit_code: "package",
          price: { id: "00000000-0000-4000-8000-000000000007",
            project_product_id: "00000000-0000-4000-8000-000000000006",
            effective_from: "2026-01-01", effective_to: null, unit_price: "18.5",
            currency: "GBP", price_basis_unit_code: "package", source: null } }],
      }))
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => deferred);
    render(<OpeningStockWorkspace projectId={projectId} session={session} />);
    const quantity = await screen.findByLabelText("Barite quantity");
    fireEvent.change(quantity, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Post opening stock" }));
    expect(quantity).toBeDisabled();
    expect(screen.getByLabelText("Barite unit")).toBeDisabled();
    finish(new Response(JSON.stringify({
      id: "00000000-0000-4000-8000-000000000008", project_id: projectId,
      source_configuration_snapshot_id: "00000000-0000-4000-8000-000000000005",
      posting_type: "opening_stock", status: "posted", posting_date: "2026-07-18",
      reversal_of_posting_id: null, reversal_posting_id: null, reason: null,
      posted_by: session.userId, posted_at: "2026-07-18T12:00:00Z", lines: [],
    }), { status: 201 }));
    await waitFor(() => expect(screen.getByText(/Quantity and cost are now immutable/)).toBeInTheDocument());
  });
});
