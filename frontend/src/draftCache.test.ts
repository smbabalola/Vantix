import "fake-indexeddb/auto";

import { describe, expect, it, vi } from "vitest";

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

  it("VTX-OFF-001 remains pending until the delete transaction completes", async () => {
    const deleteRequest = { readyState: "done" } as IDBRequest<undefined>;
    const objectStore = {
      delete: vi.fn(() => deleteRequest),
    } as unknown as IDBObjectStore;
    const controlledTransaction = {
      objectStore: vi.fn(() => objectStore),
      oncomplete: null,
      onerror: null,
      onabort: null,
      error: null,
    } as unknown as IDBTransaction;
    const transactionSpy = vi
      .spyOn(IDBDatabase.prototype, "transaction")
      .mockImplementationOnce(() => controlledTransaction);

    let resolved = false;
    const removalPromise = removeDraft(crypto.randomUUID()).then(() => {
      resolved = true;
    });

    await vi.waitFor(() => expect(controlledTransaction.objectStore).toHaveBeenCalled());
    await Promise.resolve();
    await Promise.resolve();

    expect(objectStore.delete).toHaveBeenCalledOnce();
    expect(resolved).toBe(false);

    controlledTransaction.oncomplete?.call(controlledTransaction, new Event("complete"));
    await removalPromise;

    expect(resolved).toBe(true);
    transactionSpy.mockRestore();
  });
});
