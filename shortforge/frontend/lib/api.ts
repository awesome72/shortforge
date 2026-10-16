import type {
  AppConfig,
  ImageAsset,
  Input,
  OutputKey,
  Project,
  ProjectRow,
  PublishKit,
  Quota,
  StepId,
  VersionSummary,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, `백엔드에 연결할 수 없다 (${API_BASE}) — uvicorn이 실행 중인지 확인한다`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : (body.detail ?? [])
              .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg}`)
              .join("\n") || detail;
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  config: () => call<AppConfig>("/config"),
  quota: () => call<Quota>("/quota"),
  list: () => call<ProjectRow[]>("/projects"),
  get: (id: string) => call<Project>(`/projects/${id}`),
  create: (input: Partial<Input> & { topic: string }) =>
    call<Project>("/projects", { method: "POST", ...json(input) }),
  patch: <K extends OutputKey>(id: string, key: K, value: Project[K]) =>
    call<Project>(`/projects/${id}/${key}`, { method: "PATCH", ...json(value) }),
  runStep: (id: string, step: StepId) =>
    call<{ started: StepId }>(`/projects/${id}/steps/${step}/run`, { method: "POST" }),
  runAll: (id: string, from: StepId) =>
    call<{ started: StepId }>(`/projects/${id}/run-all?from=${from}`, { method: "POST" }),
  duplicate: (id: string) => call<Project>(`/projects/${id}/duplicate`, { method: "POST" }),
  versions: (id: string) => call<VersionSummary[]>(`/projects/${id}/versions?limit=15`),
  restoreVersion: (id: string, version: number) =>
    call<Project>(`/projects/${id}/versions/${version}/restore`, { method: "POST" }),
  candidates: (id: string, sceneId: string) =>
    call<{ candidates: ImageAsset[]; notices: string[] }>(
      `/projects/${id}/scenes/${sceneId}/candidates?n=3`,
      { method: "POST" },
    ),
  selectCandidate: (id: string, sceneId: string, candidate: ImageAsset) =>
    call<Project>(`/projects/${id}/scenes/${sceneId}/image/select`, {
      method: "POST",
      ...json(candidate),
    }),
  publish: (id: string) => call<PublishKit>(`/projects/${id}/publish`),
  regenerateImage: (id: string, sceneId: string) =>
    call<{ project: Project; notices: string[] }>(`/projects/${id}/scenes/${sceneId}/image`, {
      method: "POST",
    }),
  upload: (id: string, files: File[], attach = true) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return call<{ saved: string[]; user_media: string[] }>(
      `/projects/${id}/media?attach=${attach}`,
      { method: "POST", body: form },
    );
  },
};

/** 프로젝트 폴더 안의 상대 경로만 내려받을 수 있다. 절대 경로(CLI로 넣은 사진)는 null. */
export function fileUrl(
  id: string,
  path: string | null | undefined,
  version?: number,
  download = false,
): string | null {
  if (!path || /^[a-zA-Z]:[\\/]|^\//.test(path)) return null;
  const q = new URLSearchParams();
  if (version !== undefined) q.set("v", String(version)); // 다시 만든 파일이 캐시에 가리지 않게
  if (download) q.set("download", "1"); // 출처가 달라 <a download>가 무시되므로 서버가 첨부로 내준다
  const qs = q.size ? `?${q}` : "";
  return `${API_BASE}/projects/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}${qs}`;
}

export function eventsUrl(id: string): string {
  return `${API_BASE}/projects/${id}/events`;
}
