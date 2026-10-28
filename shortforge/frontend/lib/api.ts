import type {
  AppConfig,
  ImageAsset,
  Input,
  AdvancedProvider,
  AdvancedStatus,
  KeyCheck,
  KeyStatus,
  OutputKey,
  Project,
  ProjectRow,
  PublishKit,
  Quota,
  StepId,
  VersionSummary,
  VideoPreview,
  TrendingVideo,
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
    throw new ApiError(0, `백엔드에 연결할 수 없어요 (${API_BASE}) — start.bat으로 서버가 켜져 있는지 확인해 주세요`);
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
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** 문제 보고용 zip 주소 (로그·환경 정보·사용 통계, project를 주면 그 프로젝트 파일도). 첨부 응답이라 링크로 받는다. */
export function supportBundleUrl(projectId?: string): string {
  return `${API_BASE}/support/bundle${projectId ? `?project=${projectId}` : ""}`;
}

/** 거절된 키가 있으면 422와 함께 항목별 결과가 온다. 오류로 던지지 않고 결과를 돌려준다. */
async function saveKeys(values: Record<string, string>, image_mode?: string) {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/settings/keys`, { method: "POST", ...json({ values, image_mode }) });
  } catch {
    throw new ApiError(0, `백엔드에 연결할 수 없어요 (${API_BASE})`);
  }
  const body = await res.json().catch(() => ({}));
  if (res.ok || (res.status === 422 && body.results)) {
    return body as { saved: string[]; results: KeyCheck; setup_problems?: string[] };
  }
  throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
}

export const api = {
  config: () => call<AppConfig>("/config"),
  quota: () => call<Quota>("/quota"),
  keys: () => call<KeyStatus>("/settings/keys"),
  checkKeys: (values: Record<string, string>) =>
    call<{ results: KeyCheck }>("/settings/keys/check", { method: "POST", ...json(values) }),
  saveKeys: (values: Record<string, string>, image_mode?: string) =>
    saveKeys(values, image_mode),
  saveAdvanced: (body: {
    mode: "off" | AdvancedProvider;
    model?: string;
    effort?: "low" | "medium" | "high";
    daily_budget_usd?: number;
    accept_cost?: boolean;
  }) =>
    call<{ advanced: AdvancedStatus; setup_problems: string[] }>("/settings/advanced", {
      method: "POST",
      ...json(body),
    }),
  list: () => call<ProjectRow[]>("/projects"),
  get: (id: string) => call<Project>(`/projects/${id}`),
  create: (input: Partial<Input> & { topic: string }) =>
    call<Project>("/projects", { method: "POST", ...json(input) }),
  patch: <K extends OutputKey>(id: string, key: K, value: Project[K]) =>
    call<Project>(`/projects/${id}/${key}`, { method: "PATCH", ...json(value) }),
  runStep: (id: string, step: StepId) =>
    call<{ started: StepId }>(`/projects/${id}/steps/${step}/run`, { method: "POST" }),
  runAll: (id: string, from: StepId, to: StepId = "s7") =>
    call<{ started: StepId }>(`/projects/${id}/run-all?from=${from}&to=${to}`, { method: "POST" }),
  trending: (category?: string) =>
    call<{ videos: TrendingVideo[]; notice: string | null }>(
      `/trending${category ? `?category=${encodeURIComponent(category)}` : ""}`,
    ),
  setLine: (id: string, sceneId: string, text: string) =>
    call<Project>(`/projects/${id}/scenes/${sceneId}/line`, { method: "POST", ...json({ text }) }),
  duplicate: (id: string) => call<Project>(`/projects/${id}/duplicate`, { method: "POST" }),
  deleteProject: (id: string) => call<void>(`/projects/${id}`, { method: "DELETE" }),
  cleanup: (id: string) => call<{ removed: number; freed_bytes: number }>(`/projects/${id}/cleanup`, { method: "POST" }),
  versions: (id: string) => call<VersionSummary[]>(`/projects/${id}/versions?limit=15`),
  restoreVersion: (id: string, version: number) =>
    call<Project>(`/projects/${id}/versions/${version}/restore`, { method: "POST" }),
  candidates: (id: string, sceneId: string) =>
    call<{ candidates: ImageAsset[]; notices: string[] }>(
      `/projects/${id}/scenes/${sceneId}/candidates?n=3`,
      { method: "POST" },
    ),
  videoPreviews: (id: string, sceneId: string) =>
    call<{ query: string; videos: VideoPreview[] }>(`/projects/${id}/scenes/${sceneId}/videos?n=6`, {
      method: "POST",
    }),
  selectVideo: (id: string, sceneId: string, videoId: number, focusX?: number) =>
    call<Project>(`/projects/${id}/scenes/${sceneId}/video/select`, {
      method: "POST",
      ...json({ id: videoId, focus_x: focusX }),
    }),
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
  outdatedRenders: () =>
    call<{ ids: string[]; bulk: { running: boolean; total: number; done: number; failed: number } }>(
      "/renders/outdated",
    ),
  rerenderOutdated: () => call<{ started: number }>("/renders/outdated/rerender", { method: "POST" }),
  makeCover: (id: string, title?: string) =>
    call<{ cover: string; cover_title: string }>(`/projects/${id}/cover`, {
      method: "POST",
      ...json(title === undefined ? {} : { title }),
    }),
  saveBrand: (name: string) =>
    call<{ brand_name: string }>("/settings/brand", { method: "POST", ...json({ name }) }),
  setMusic: (
    id: string,
    body: { mood?: string; another?: boolean; off?: boolean; auto?: boolean; gain_db?: number },
  ) => call<Project>(`/projects/${id}/music`, { method: "POST", ...json(body) }),
  uploadMusic: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return call<Project>(`/projects/${id}/music/upload`, { method: "POST", body: form });
  },
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
