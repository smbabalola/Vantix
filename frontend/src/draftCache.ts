import type { GeneralSection } from "./types";

const DB_NAME = "vantix-drafts";
const STORE_NAME = "draft-patches";
const DB_VERSION = 1;

export interface CachedDraft {
  reportId: string;
  baseVersion: number;
  mutationId: string;
  savedAt: string;
  general: GeneralSection;
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "reportId" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function cacheDraft(draft: CachedDraft): Promise<void> {
  const database = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(draft);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}

export async function readDraft(reportId: string): Promise<CachedDraft | undefined> {
  const database = await openDatabase();
  const value = await new Promise<CachedDraft | undefined>((resolve, reject) => {
    const request = database.transaction(STORE_NAME).objectStore(STORE_NAME).get(reportId);
    request.onsuccess = () => resolve(request.result as CachedDraft | undefined);
    request.onerror = () => reject(request.error);
  });
  database.close();
  return value;
}

export async function removeDraft(reportId: string): Promise<void> {
  const database = await openDatabase();
  const transaction = database.transaction(STORE_NAME, "readwrite");
  transaction.objectStore(STORE_NAME).delete(reportId);
  database.close();
}

