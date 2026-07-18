import type {
  ConfigurationReadiness,
  GeneralSection,
  Project,
  ProjectConfiguration,
  Readiness,
  Report,
} from "./types";

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
  getProject(session: Session, projectId: string): Promise<Project> {
    return request(session, `/projects/${projectId}`);
  },
  listConfigurations(session: Session, projectId: string): Promise<ProjectConfiguration[]> {
    return request(session, `/projects/${projectId}/configuration-versions`);
  },
  createConfiguration(
    session: Session,
    projectId: string,
    idempotencyKey: string,
  ): Promise<ProjectConfiguration> {
    return request(session, `/projects/${projectId}/configuration-versions`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ copy_active: true }),
    });
  },
  saveConfiguration(
    session: Session,
    configuration: ProjectConfiguration,
  ): Promise<ProjectConfiguration> {
    return request(
      session,
      `/projects/${configuration.project_id}/configuration-versions/${configuration.id}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          expected_version: configuration.row_version,
          data: configuration.data,
          change_summary: configuration.change_summary,
        }),
      },
    );
  },
  validateConfiguration(
    session: Session,
    configuration: ProjectConfiguration,
  ): Promise<ConfigurationReadiness> {
    return request(
      session,
      `/projects/${configuration.project_id}/configuration-versions/${configuration.id}/validate`,
      { method: "POST" },
    );
  },
  activateConfiguration(
    session: Session,
    configuration: ProjectConfiguration,
    readiness: ConfigurationReadiness,
    idempotencyKey: string,
  ): Promise<ProjectConfiguration> {
    return request(
      session,
      `/projects/${configuration.project_id}/configuration-versions/${configuration.id}/activate`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({
          expected_version: readiness.validated_version,
          expected_checksum: readiness.draft_checksum,
        }),
      },
    );
  },
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
