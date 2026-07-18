import { useEffect, useState } from "react";

import App from "./App";
import { ApiError, api, type Session } from "./api";
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
  return <App initialReport={report} session={session} />;
}
