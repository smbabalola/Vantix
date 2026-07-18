import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProjectConfiguration from "./ProjectConfiguration";

const session = {
  userId: "00000000-0000-4000-8000-000000000001",
  organisationId: "00000000-0000-4000-8000-000000000002",
  capabilities: ["configure_project"],
};

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
}

describe("project configuration workspace", () => {
  afterEach(() => vi.restoreAllMocks());

  it("VTX-PRJ-002 keeps activation gated by server readiness and labels depths optional", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({
        id: "00000000-0000-4000-8000-000000000010",
        organisation_id: session.organisationId,
        project_code: "NS-A",
        project_name: "North Sea A",
        well_name: "A-01",
        time_zone: "Europe/London",
        currency: "GBP",
        unit_set: "Metric",
        status: "draft",
        current_configuration_version_id: null,
        active_configuration_snapshot_id: null,
      }))
      .mockImplementationOnce(() => response([{
        id: "00000000-0000-4000-8000-000000000011",
        project_id: "00000000-0000-4000-8000-000000000010",
        version: 1,
        state: "draft",
        row_version: 1,
        data: {
          default_interval_id: "00000000-0000-4000-8000-000000000012",
          intervals: [{
            id: "00000000-0000-4000-8000-000000000012",
            name: "12 1/4 inch interval",
            operation_mode: "drilling",
          }],
        },
        change_summary: null,
        snapshot_id: null,
        checksum: null,
      }]))
      .mockImplementationOnce(() => response({ state: "ready", can_activate: true, issues: [] }));

    render(<ProjectConfiguration projectId="00000000-0000-4000-8000-000000000010" session={session} />);

    expect(await screen.findByLabelText("Top MD (m, optional)")).toHaveAttribute("placeholder", "Unavailable");
    const activate = screen.getByRole("button", { name: /activate and freeze snapshot/i });
    expect(activate).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /validate readiness/i }));
    await waitFor(() => expect(activate).toBeEnabled());
    expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/validate"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
