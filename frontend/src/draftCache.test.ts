import "fake-indexeddb/auto";

import { describe, expect, it } from "vitest";

import { cacheDraft, readDraft, removeDraft } from "./draftCache";

describe("draft cache", () => {
  it("VTX-OFF-001 completes deletion before resolving", async () => {
    const reportId = crypto.randomUUID();
    await cacheDraft({
      reportId,
      baseVersion: 1,
      mutationId: crypto.randomUUID(),
      savedAt: new Date().toISOString(),
      general: {
        operation_mode: "drilling",
        interval_id: crypto.randomUUID(),
        fluid_system_id: crypto.randomUUID(),
        present_activity: "Drilling ahead",
      },
    });

    expect(await readDraft(reportId)).toBeDefined();
    await removeDraft(reportId);
    expect(await readDraft(reportId)).toBeUndefined();
  });
});
