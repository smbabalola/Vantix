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
      product_definition_id: "00000000-0000-4000-8000-000000000013",
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
        onDirtyChange={() => undefined}
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
    expect(screen.getByLabelText("From")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Add price" })).toBeDisabled();
    expect(screen.getByLabelText("Per")).not.toHaveTextContent("L");
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/products"),
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("VTX-PRO-001 exposes non-inventory creation and field-level server errors", async () => {
    const product = {
      id: "00000000-0000-4000-8000-000000000014",
      product_definition_id: "00000000-0000-4000-8000-000000000015",
      project_id: configuration.project_id,
      configuration_version_id: configuration.id,
      configuration_row_version: 1,
      item_code: "DRM-001",
      item_name: "Liquid additive",
      alternate_name: null,
      packaging: "drum",
      package_size: "200",
      package_unit_code: "L",
      inventory_applicable: true,
      inventory_unit_code: "package",
      specific_gravity: null,
      active: true,
      prices: [],
    };
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response([product]))
      .mockImplementationOnce(() => response({
        detail: {
          code: "PACKAGE_SIZE_INVALID",
          message: "Value must be finite and greater than zero.",
          field: "package_size",
        },
      }, 422));

    render(
      <ProductPricingGrid
        configuration={configuration}
        currency="GBP"
        session={session}
        disabled={false}
        onPendingChange={() => undefined}
        onSaved={() => undefined}
        onDirtyChange={() => undefined}
      />,
    );
    expect(await screen.findByText("Product authority loaded")).toBeInTheDocument();
    const applicability = screen.getAllByLabelText("Inventory applicable");
    fireEvent.click(applicability[1]);
    expect(screen.getAllByLabelText("Inventory unit")[1]).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Size"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save product" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Value must be finite and greater than zero.",
    );
  });
});
