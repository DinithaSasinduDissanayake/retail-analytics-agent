/* API client for the warehouse agent backend */
const BASE = "/api";

export interface HealthResponse {
  status: string;
  products?: number;
  detail?: string;
}

export interface DashboardResult {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
  error?: string;
}

export interface SyncResult {
  status: string;
  summary?: Record<string, unknown> | null;
}

export interface PendingQuestion {
  question_id: string;
  question: string;
  session_id: string;
}

export async function healthCheck(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function dashboardQuery(sql: string): Promise<DashboardResult> {
  const res = await fetch(`${BASE}/dashboard/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql }),
  });
  return res.json();
}

export async function syncData(): Promise<SyncResult> {
  const res = await fetch(`${BASE}/sync`, { method: "POST" });
  return res.json();
}

export async function getPendingQuestions(): Promise<PendingQuestion[]> {
  const res = await fetch(`${BASE}/agent/questions`);
  return res.json();
}

export async function submitAnswer(
  answer: string,
  questionId?: string | null
): Promise<Response> {
  return fetch(`${BASE}/agent/respond`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer, question_id: questionId || null }),
  });
}
