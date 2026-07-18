import type { GeneralSection, Readiness, Report } from "./types";

export interface Session {
  userId: string;
  organisationId: string;
  capabilities: string[];
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(session: Session, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Vantix-User-ID": session.userId,
      "X-Vantix-Organisation-ID": session.organisationId,
      "X-Vantix-Capabilities": session.capabilities.join(","),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail ?? body;
    throw new ApiError(response.status, detail.code ?? "REQUEST_FAILED", detail.message ?? "Request failed");
  }
  return response.json() as Promise<T>;
}

export const api = {
  getReport(session: Session, reportId: string): Promise<Report> {
    return request(session, `/daily-reports/${reportId}`);
  },
  saveGeneral(session: Session, report: Report, general: GeneralSection): Promise<Report> {
    return request(session, `/daily-report-revisions/${report.revision.id}/sections/general`, {
      method: "PATCH",
      body: JSON.stringify({ expected_version: report.revision.version, data: general }),
    });
  },
  validate(session: Session, reportId: string): Promise<Readiness> {
    return request(session, `/daily-report-revisions/${reportId}/validate`, { method: "POST" });
  },
  submit(session: Session, report: Report): Promise<Report> {
    return request(session, `/daily-report-revisions/${report.revision.id}/submit`, {
      method: "POST",
      headers: {
        "If-Match": String(report.revision.version),
        "Idempotency-Key": crypto.randomUUID(),
      },
    });
  },
  reject(session: Session, report: Report, reason: string): Promise<Report> {
    return request(session, `/daily-report-revisions/${report.revision.id}/reject`, {
      method: "POST",
      body: JSON.stringify({ expected_checksum: report.revision.checksum, reason }),
    });
  },
  approve(session: Session, report: Report): Promise<Report> {
    return request(session, `/daily-report-revisions/${report.revision.id}/approve`, {
      method: "POST",
      body: JSON.stringify({ expected_checksum: report.revision.checksum }),
    });
  },
};
