import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

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
      .mockImplementationOnce(() => response({
        state: "ready",
        can_activate: true,
        validated_version: 1,
        draft_checksum: "a".repeat(64),
        issues: [],
      }));

    render(<ProjectConfiguration projectId="00000000-0000-4000-8000-000000000010" session={session} />);

    expect(await screen.findByLabelText("Top MD (optional)")).toHaveAttribute("placeholder", "Unavailable");
    expect(screen.getByLabelText(/top md unit/i)).toHaveValue("m");
    const activate = screen.getByRole("button", { name: /activate and freeze snapshot/i });
    expect(activate).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /validate readiness/i }));
    await waitFor(() => expect(activate).toBeEnabled());
    expect(fetchMock).toHaveBeenLastCalledWith(
      expect.stringContaining("/validate"),
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.change(screen.getByLabelText("Interval name"), {
      target: { value: "Changed after validation" },
    });
    expect(activate).toBeDisabled();
    expect(screen.getByRole("button", { name: /validate readiness/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /save draft/i })).toBeEnabled();
  });

  it("reuses the activation key after a lost response and disables actions while pending", async () => {
    const project = {
      id: "00000000-0000-4000-8000-000000000020",
      organisation_id: session.organisationId,
      project_code: "NS-B",
      project_name: "North Sea B",
      well_name: "B-01",
      time_zone: "Europe/London",
      currency: "GBP",
      unit_set: "Field",
      status: "draft",
      current_configuration_version_id: null,
      active_configuration_snapshot_id: null,
    };
    const configuration = {
      id: "00000000-0000-4000-8000-000000000021",
      project_id: project.id,
      version: 1,
      state: "draft",
      row_version: 1,
      data: {
        default_interval_id: "00000000-0000-4000-8000-000000000022",
        intervals: [{
          id: "00000000-0000-4000-8000-000000000022",
          name: "Field interval",
          operation_mode: "drilling",
        }],
      },
      change_summary: null,
      snapshot_id: null,
      checksum: null,
    };
    let rejectActivation: (reason?: unknown) => void = () => undefined;
    const stalledActivation = new Promise<Response>((_, reject) => {
      rejectActivation = reject;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response(project))
      .mockImplementationOnce(() => response([configuration]))
      .mockImplementationOnce(() => response({
        state: "ready",
        can_activate: true,
        validated_version: 1,
        draft_checksum: "b".repeat(64),
        issues: [],
      }))
      .mockImplementationOnce(() => stalledActivation)
      .mockImplementationOnce(() => response({
        ...configuration,
        state: "active",
        snapshot_id: "00000000-0000-4000-8000-000000000023",
        checksum: "c".repeat(64),
      }));

    render(<ProjectConfiguration projectId={project.id} session={session} />);
    fireEvent.click(await screen.findByRole("button", { name: /validate readiness/i }));
    const activate = screen.getByRole("button", { name: /activate and freeze snapshot/i });
    await waitFor(() => expect(activate).toBeEnabled());

    fireEvent.click(activate);
    expect(activate).toBeDisabled();
    rejectActivation(new Error("Network response lost"));
    expect(await screen.findByText("Network response lost")).toBeInTheDocument();

    fireEvent.click(activate);
    expect(await screen.findByText("Active snapshot frozen")).toBeInTheDocument();
    const activationCalls = fetchMock.mock.calls.filter(([path]) =>
      String(path).endsWith("/activate"),
    );
    expect(activationCalls).toHaveLength(2);
    const firstHeaders = activationCalls[0][1]?.headers as Record<string, string>;
    const secondHeaders = activationCalls[1][1]?.headers as Record<string, string>;
    expect(secondHeaders["Idempotency-Key"]).toBe(firstHeaders["Idempotency-Key"]);
  });

  it("keeps interval controls disabled until a deferred save settles", async () => {
    const project = {
      id: "00000000-0000-4000-8000-000000000030",
      organisation_id: session.organisationId,
      project_code: "NS-C",
      project_name: "North Sea C",
      well_name: "C-01",
      time_zone: "Europe/London",
      currency: "GBP",
      unit_set: "Metric",
      status: "draft",
      current_configuration_version_id: null,
      active_configuration_snapshot_id: null,
    };
    const configuration = {
      id: "00000000-0000-4000-8000-000000000031",
      project_id: project.id,
      version: 1,
      state: "draft",
      row_version: 1,
      data: {
        default_interval_id: "00000000-0000-4000-8000-000000000032",
        intervals: [{
          id: "00000000-0000-4000-8000-000000000032",
          name: "Original interval",
          operation_mode: "drilling",
        }],
      },
      change_summary: null,
      snapshot_id: null,
      checksum: null,
    };
    let completeSave: (value: Response) => void = () => undefined;
    const deferredSave = new Promise<Response>((resolve) => {
      completeSave = resolve;
    });
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response(project))
      .mockImplementationOnce(() => response([configuration]))
      .mockImplementationOnce(() => deferredSave);

    render(<ProjectConfiguration projectId={project.id} session={session} />);
    const intervalName = await screen.findByLabelText("Interval name");
    fireEvent.change(intervalName, { target: { value: "Saved interval" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));

    await waitFor(() => expect(intervalName).toBeDisabled());
    expect(screen.getByRole("combobox", { name: "Operation mode" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /remove interval/i })).toBeDisabled();

    completeSave(new Response(JSON.stringify({
      ...configuration,
      row_version: 2,
      data: {
        ...configuration.data,
        intervals: [{ ...configuration.data.intervals[0], name: "Saved interval" }],
      },
    }), { status: 200 }));

    expect(await screen.findByText("Saved")).toBeInTheDocument();
    await waitFor(() => expect(intervalName).toBeEnabled());
    expect(intervalName).toHaveValue("Saved interval");
  });
});
