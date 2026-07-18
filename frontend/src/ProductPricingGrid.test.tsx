import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductPricingGrid from "./ProductPricingGrid";

const session = {
  userId: "00000000-0000-4000-8000-000000000001",
  organisationId: "00000000-0000-4000-8000-000000000002",
  capabilities: ["configure_project"],
};

const configuration = {
  id: "00000000-0000-4000-8000-000000000010",
  project_id: "00000000-0000-4000-8000-000000000011",
  version: 1,
  state: "draft" as const,
  row_version: 1,
  data: { default_interval_id: null, intervals: [] },
  change_summary: null,
  snapshot_id: null,
  checksum: null,
};

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("product and pricing grid", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("VTX-PRO-001 exposes packaging, inventory unit, SG availability, and price readiness", async () => {
    const saved = vi.fn();
    const product = {
      id: "00000000-0000-4000-8000-000000000012",
      project_id: configuration.project_id,
      configuration_version_id: configuration.id,
      configuration_row_version: 2,
      item_code: "BAR-001",
      item_name: "Barite",
      alternate_name: null,
      packaging: "sack",
      package_size: "25",
      package_unit_code: "kg",
      inventory_applicable: true,
      inventory_unit_code: "package",
      specific_gravity: null,
      active: true,
      prices: [],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([]))
      .mockImplementationOnce(() => response(product, 201));

    render(
      <ProductPricingGrid
        configuration={configuration}
        currency="GBP"
        session={session}
        disabled={false}
        onPendingChange={() => undefined}
        onSaved={saved}
      />,
    );

    expect(await screen.findByText("Add at least one active product.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Item code"), { target: { value: "BAR-001" } });
    fireEvent.change(screen.getByLabelText("Product name"), { target: { value: "Barite" } });
    fireEvent.change(screen.getByLabelText("Package size"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Add product" }));

    expect(await screen.findByText("Price required")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Specific gravity (optional)")[0]).toHaveAttribute(
      "placeholder",
      "Unavailable",
    );
    expect(screen.getByText("Inventory unit", { selector: "span" })).toBeInTheDocument();
    expect(saved).toHaveBeenCalledWith(2);
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/products"),
      expect.objectContaining({ method: "POST" }),
    ));
  });
});
