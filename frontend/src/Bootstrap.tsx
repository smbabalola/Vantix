import { useEffect, useState } from "react";

import App from "./App";
import { ApiError, api, type Session } from "./api";
import ProjectConfiguration from "./ProjectConfiguration";
import OpeningStockWorkspace from "./OpeningStockWorkspace";
import ReceiptWorkspace from "./ReceiptWorkspace";
import type { Report } from "./types";

function environmentSession(): Session | undefined {
  const userId = import.meta.env.VITE_VANTIX_USER_ID as string | undefined;
  const organisationId = import.meta.env.VITE_VANTIX_ORGANISATION_ID as string | undefined;
  if (!userId || !organisationId) return undefined;
  return {
    userId,
    organisationId,
    capabilities: (import.meta.env.VITE_VANTIX_CAPABILITIES as string | undefined)
      ?.split(",")
      .map((item) => item.trim())
      .filter(Boolean) ?? [],
  };
}

export default function Bootstrap() {
  const [session] = useState(() => environmentSession());
  const reportId = new URLSearchParams(window.location.search).get("report");
  const projectId = new URLSearchParams(window.location.search).get("project");
  const workspace = new URLSearchParams(window.location.search).get("workspace");
  const [report, setReport] = useState<Report>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!session || !reportId) return;
    api.getReport(session, reportId).then(setReport).catch((caught) => {
      setError(caught instanceof ApiError ? caught.message : "Unable to open report.");
    });
  }, [reportId, session]);

  if (error) {
    return <main className="empty-shell"><div className="brand-mark">V</div><h1>Report unavailable</h1><p>{error}</p><span className="state-badge state-incomplete">Failed</span></main>;
  }
  if (session && reportId && !report) {
    return <main className="empty-shell"><div className="brand-mark">V</div><h1>Opening report</h1><span className="state-badge state-incomplete">Loading</span></main>;
  }
  if (session && projectId && workspace === "opening-stock") {
    return <OpeningStockWorkspace projectId={projectId} session={session} />;
  }
  if (session && projectId && workspace === "receipts") {
    return <ReceiptWorkspace projectId={projectId} session={session} />;
  }
  if (session && projectId) return <ProjectConfiguration projectId={projectId} session={session} />;
  return <App initialReport={report} session={session} />;
}
