/** Client minimale verso il backend FastAPI (M0). */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function handleFetch<T>(url: string, options?: RequestInit): Promise<T> {
  try {
    const res = await fetch(url, {
      ...options,
      credentials: "include",
      headers: {
        ...(options?.headers || {}),
      },
    });
    
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail ?? `HTTP ${res.status}`);
    }
    
    return res.json();
  } catch (error) {
    if (error instanceof TypeError && error.message.includes("fetch")) {
      throw new Error("Impossibile connettersi al server. Verifica che il backend sia in esecuzione su http://127.0.0.1:8000");
    }
    throw error;
  }
}

export interface HealthResponse {
  status: string;
  service: string;
  projects_count: number;
}

export async function getHealth(): Promise<HealthResponse> {
  return handleFetch<HealthResponse>(`${API_BASE}/api/health`, { cache: "no-store" } as RequestInit);
}

export interface ProjectSummary {
  project_id: string;
  media_count: number;
  has_audio: boolean;
  has_render: boolean;
  updated_at: number;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return handleFetch<ProjectSummary[]>(`${API_BASE}/api/projects`, { cache: "no-store" } as RequestInit);
}

export async function createProject(): Promise<{ project_id: string }> {
  return handleFetch<{ project_id: string }>(`${API_BASE}/api/projects`, { method: "POST" } as RequestInit);
}

export interface MediaItem {
  id: string;
  source: "local" | "google_drive";
  path: string;
  type: "photo" | "video";
  orientation: "landscape" | "portrait" | "square";
  width: number;
  height: number;
  duration_sec: number;
  order_index: number;
  fit_mode?: "cover" | "contain" | null;
  background_fill?: "blur" | "solid_color" | null;
  trim_start_sec?: number | null;
  trim_end_sec?: number | null;
}

export interface ProjectState {
  project_id: string;
  media: MediaItem[];
  audio: { path: string | null; duration_sec: number; bpm: number; beat_markers_sec: number[]; energy_curve: number[] };
  style_profile: string;
  output_spec: { resolution: string; fps: number; background_fill: "blur" | "solid_color"; vcodec: "h264" | "h265" };
  edit_decision_list: EditEntry[];
  render_manifest: RenderManifest | null;
  qa_report: QAReport | null;
  errors: { stage: string; message: string }[];
  pipeline_log: { stage: string; status: string; ts: number }[];
  created_at: number;
  updated_at: number;
}

export async function uploadMedia(projectId: string, files: File[]): Promise<ProjectState> {
  const formData = new FormData();
  files.forEach(f => formData.append("files", f));
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/media`, {
    method: "POST",
    body: formData,
  } as RequestInit);
}

export async function getProject(projectId: string): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}`, { cache: "no-store" } as RequestInit);
}

export type BackgroundFill = "blur" | "solid_color";

export async function reorderMedia(projectId: string, mediaIds: string[]): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/media/order`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_ids: mediaIds }),
  } as RequestInit);
}

export async function updateMediaFill(
  projectId: string,
  mediaId: string,
  backgroundFill: BackgroundFill,
): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/media/${mediaId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ background_fill: backgroundFill }),
  } as RequestInit);
}

export interface SettingsPatch {
  background_fill?: BackgroundFill;
  resolution?: string;
  fps?: number;
  vcodec?: "h264" | "h265";
}

export async function updateSettings(projectId: string, patch: SettingsPatch): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  } as RequestInit);
}

/** URL del file originale (uso raro: gli originali pesano). */
export function mediaFileUrl(projectId: string, mediaId: string): string {
  return `${API_BASE}/api/projects/${projectId}/media/${mediaId}/file`;
}

/** Anteprima JPEG leggera con cache server (timeline, griglie). */
export function mediaThumbUrl(projectId: string, mediaId: string, w = 320): string {
  return `${API_BASE}/api/projects/${projectId}/media/${mediaId}/thumb?w=${w}`;
}

export interface AudioInfo {
  path: string | null;
  duration_sec: number;
  bpm: number;
  beat_markers_sec: number[];
  energy_curve: number[];
}

export async function uploadAudio(projectId: string, file: File): Promise<ProjectState> {
  const formData = new FormData();
  formData.append("file", file);
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/audio`, {
    method: "POST",
    body: formData,
  } as RequestInit);
}

export interface KenBurns {
  movement: string;
  zoom_from: number;
  zoom_to: number;
  pan_x_from: number;
  pan_x_to: number;
  pan_y_from: number;
  pan_y_to: number;
}

export interface EditEntry {
  media_id: string;
  start_sec_in_final_video: number;
  duration_sec: number;
  ken_burns: KenBurns | null;
  transition_in: number;
  transition_out: number;
}

export interface QACheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface QAIssue {
  check: string;
  message: string;
  route_to: string;
}

export interface QAReport {
  status: "approved" | "rejected";
  checks: QACheck[];
  issues: QAIssue[];
}

export interface RenderManifest {
  version: number;
  output: { path: string; resolution: string; fps: number; size_bytes?: number; rendered_at?: number };
  inputs: { index: number; path: string; kind: string }[];
  segments: { media_id: string; kind: string; fit: string; duration_sec: number }[];
  transitions: { duration_sec: number; offset_sec: number }[];
  total_sec: number;
  audio: { path: string } | null;
  status?: string;
}

export async function planEdit(projectId: string): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/edit`, { method: "POST" } as RequestInit);
}

export async function renderVideo(projectId: string): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/render`, { method: "POST" } as RequestInit);
}

/** URL diretto all'mp4 finale (anteprima <video> e download). */
export function downloadUrl(projectId: string): string {
  return `${API_BASE}/api/projects/${projectId}/download`;
}

export interface DriveStatus {
  configured: boolean;
  connected: boolean;
  email: string | null;
}

export interface DriveEntry {
  id: string;
  name: string;
  mimeType: string;
  is_folder: boolean;
}

export interface DriveFolder {
  current: { id: string; name: string };
  entries: DriveEntry[];
  nextPageToken: string | null;
}

export async function driveStatus(): Promise<DriveStatus> {
  return handleFetch<DriveStatus>(`${API_BASE}/api/drive/status`, { cache: "no-store" } as RequestInit);
}

export async function saveDriveCredentials(clientId: string, clientSecret: string): Promise<void> {
  await handleFetch<void>(`${API_BASE}/api/drive/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
  } as RequestInit);
}

export async function driveAuthUrl(): Promise<string> {
  const result = await handleFetch<{ url: string }>(`${API_BASE}/api/drive/auth-url`, { cache: "no-store" } as RequestInit);
  return result.url;
}

export async function driveDisconnect(): Promise<void> {
  await handleFetch<void>(`${API_BASE}/api/drive/disconnect`, { method: "POST" } as RequestInit);
}

export async function driveListFiles(
  projectId: string,
  folderId = "root",
  pageToken?: string,
  shared?: boolean,
): Promise<DriveFolder> {
  const params = new URLSearchParams();
  if (folderId !== "root" || !shared) params.set("folder_id", folderId);
  if (pageToken) params.set("page_token", pageToken);
  if (shared) params.set("shared", "true");
  return handleFetch<DriveFolder>(`${API_BASE}/api/projects/${projectId}/drive/files?${params}`, { cache: "no-store" } as RequestInit);
}

export async function driveImport(
  projectId: string,
  fileIds: string[],
  folderIds: string[],
): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/drive/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
  } as RequestInit);
}

export interface PipelineEvent {
  stage: string;
  status: string;
  ts: number;
}

export interface ProgressSnapshot {
  pipeline_log: PipelineEvent[];
  errors_count: number;
  media_count: number;
  has_audio: boolean;
  has_edit: boolean;
  has_render: boolean;
  qa_status: "approved" | "rejected" | null;
  updated_at: number;
  jobs: Job[];
}

export interface JobProgress {
  fraction: number;
  note: string;
  stage: string;
}

export interface Job {
  job_id: string;
  project_id: string;
  kind: "render" | "drive_import";
  status: "queued" | "running" | "done" | "failed";
  progress: JobProgress;
  result: unknown;
  error: string | null;
  created_at: number;
  updated_at: number;
}

export function isJobActive(job: Job | null | undefined): job is Job {
  return !!job && (job.status === "queued" || job.status === "running");
}

export async function submitRenderJob(projectId: string): Promise<Job> {
  const result = await handleFetch<{ job: Job }>(`${API_BASE}/api/projects/${projectId}/render?background=true`, { method: "POST" } as RequestInit);
  return result.job;
}

export async function submitDriveImportJob(
  projectId: string,
  fileIds: string[],
  folderIds: string[],
): Promise<Job> {
  const result = await handleFetch<{ job: Job }>(`${API_BASE}/api/projects/${projectId}/drive/import?background=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
  } as RequestInit);
  return result.job;
}

export async function clearErrors(projectId: string): Promise<ProjectState> {
  return handleFetch<ProjectState>(`${API_BASE}/api/projects/${projectId}/errors/clear`, { method: "POST" } as RequestInit);
}

export async function deleteProject(projectId: string): Promise<void> {
  await handleFetch<void>(`${API_BASE}/api/projects/${projectId}`, { method: "DELETE" } as RequestInit);
}
