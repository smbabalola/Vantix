import "fake-indexeddb/auto";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Bootstrap from "./Bootstrap";

const report = {
  id: "00000000-0000-4000-8000-000000000010",
  project_id: "00000000-0000-4000-8000-000000000003",
  report_date: "2026-07-19",
  report_number: "DEMO-0001",
  revision: {
    id: "00000000-0000-4000-8000-000000000011",
    number: 1,
    kind: "original",
    state: "draft",
    version: 1,
    data: {},
    checksum: null,
    based_on_revision_id: null,
  },
};

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

describe("bootstrap report deep link", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    window.history.replaceState(null, "", "/");
  });

  it("renders the fetched report when opened via a ?report= deep link", async () => {
    vi.stubEnv("VITE_VANTIX_USER_ID", "00000000-0000-4000-8000-000000000001");
    vi.stubEnv("VITE_VANTIX_ORGANISATION_ID", "00000000-0000-4000-8000-000000000002");
    vi.stubEnv("VITE_VANTIX_CAPABILITIES", "view_draft_report,edit_report");
    window.history.replaceState(null, "", `/?report=${report.id}`);
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => response(report));

    render(<Bootstrap />);

    expect(await screen.findByText("DEMO-0001")).toBeInTheDocument();
    expect(screen.queryByText("No active report")).not.toBeInTheDocument();
  });
});
