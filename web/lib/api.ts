// Use the Next.js same-origin proxy by default. This avoids browser-side
// localhost resolution, CORS, and mixed-content failures.
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");
const MOCK = process.env.NEXT_PUBLIC_MOCK === "true";

export interface NavigationResult {
  is_clear: boolean;
  brief: string | null;
  directions: string[];
  message: string | null;
}

export interface NavigationRefineResult {
  brief: string;
}

export async function analyzeNavigation(query: string): Promise<NavigationResult> {
  if (MOCK) {
    const { mockNavigation } = await import("./mock");
    return mockNavigation(query);
  }
  const res = await fetch(`${API_BASE}/api/navigator/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error(`Navigation analysis failed: ${await res.text()}`);
  return res.json();
}

export async function refineNavigation(query: string, response: string): Promise<NavigationRefineResult> {
  if (MOCK) {
    const { mockNavigationRefinement } = await import("./mock");
    return mockNavigationRefinement(query, response);
  }
  const res = await fetch(`${API_BASE}/api/navigator/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, response }),
  });
  if (!res.ok) throw new Error(`Navigation refinement failed: ${await res.text()}`);
  return res.json();
}

export interface SaveReportResult {
  title: string;
  status: "skipped" | "overwritten" | "created";
}

export async function saveReport(title: string, content: string): Promise<SaveReportResult> {
  if (MOCK) {
    const { mockSaveReport } = await import("./mock");
    return mockSaveReport(title);
  }
  const res = await fetch(`${API_BASE}/api/library/save-report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content }),
  });
  return res.json();
}

export interface LibraryDoc {
  title: string;
  source_type: string;
  added_at: string;
}

export async function listDocs(): Promise<LibraryDoc[]> {
  if (MOCK) {
    const { mockListDocs } = await import("./mock");
    return mockListDocs();
  }
  const res = await fetch(`${API_BASE}/api/library`);
  return res.json();
}

export interface LibraryPreview {
  title: string;
  source_type: string;
  content: string;
}

export async function getDocPreview(title: string): Promise<LibraryPreview> {
  if (MOCK) return { title, source_type: "mock", content: title };
  const url = API_BASE + "/api/library/" + encodeURIComponent(title) + "/preview";
  const res = await fetch(url);
  if (res.ok === false) throw new Error("Failed to preview document: " + await res.text());
  return res.json();
}

export async function deleteDoc(title: string): Promise<void> {
  if (MOCK) {
    const { mockDeleteDoc } = await import("./mock");
    return mockDeleteDoc(title);
  }
  await fetch(`${API_BASE}/api/library/${encodeURIComponent(title)}`, {
    method: "DELETE",
  });
}

export async function uploadFile(file: File): Promise<SaveReportResult> {
  if (MOCK) {
    const { mockUploadFile } = await import("./mock");
    return mockUploadFile(file);
  }
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/library/upload`, {
      method: "POST",
      body: form,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Could not reach the document upload service. Confirm the backend is running. (${detail})`);
  }
  if (!res.ok) {
    const body = await res.text();
    let message = body || `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(body);
      message = parsed.detail || message;
    } catch {
      // The backend may return plain text for proxy or infrastructure errors.
    }
    throw new Error(`Failed to upload file: ${message}`);
  }
  return res.json();
}

// --- Long-term research memory ---

export interface ResearchPreferences {
  report_language: "auto" | "zh-CN" | "en";
  report_depth: "concise" | "balanced" | "deep";
  prefer_primary_sources: boolean;
  prefer_academic_sources: boolean;
  include_methodology: boolean;
  include_quantitative_evidence: boolean;
  include_code_repositories: boolean;
  research_context: string;
}

export const DEFAULT_RESEARCH_PREFERENCES: ResearchPreferences = {
  report_language: "auto",
  report_depth: "deep",
  prefer_primary_sources: true,
  prefer_academic_sources: true,
  include_methodology: true,
  include_quantitative_evidence: true,
  include_code_repositories: false,
  research_context: "",
};

export function getClientSessionId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const key = "iceberg-research-session-id";
  let value = window.localStorage.getItem(key);
  if (!value) {
    value = `web_${crypto.randomUUID()}`;
    window.localStorage.setItem(key, value);
  }
  return value;
}

export async function getResearchPreferences(): Promise<ResearchPreferences> {
  if (MOCK) return DEFAULT_RESEARCH_PREFERENCES;
  const res = await fetch(`${API_BASE}/api/memory/preferences`);
  if (!res.ok) throw new Error(`读取研究偏好失败: ${await res.text()}`);
  return res.json();
}

export async function saveResearchPreferences(
  preferences: ResearchPreferences,
  sessionId?: string,
): Promise<ResearchPreferences> {
  if (MOCK) return preferences;
  const res = await fetch(`${API_BASE}/api/memory/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preferences, session_id: sessionId || null }),
  });
  if (!res.ok) throw new Error(`保存研究偏好失败: ${await res.text()}`);
  return res.json();
}

// --- SSE Research Events ---

export type ResearchEvent =
  | { type: "navigator"; sub_questions: { label: string; question: string }[] }
  | { type: "diver"; question: string; preview: string; tool_call_counts: Record<string, number> }
  | { type: "sonar"; round: number; sonar_summary: { question: string; verdict: string; failed: Record<string, boolean>; evidence?: Record<string, string> }[]; missing_dimensions?: string }
  | { type: "synthesizer"; report: string }
  | { type: "stats"; total_calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number }
  | { type: "error"; message: string };

export function startResearch(
  brief: string,
  onEvent: (event: ResearchEvent) => void,
): () => void {
  if (MOCK) {
    let cancelled = false;
    let mockAbort: (() => void) | null = null;
    import("./mock").then(({ startMockResearch }) => {
      if (!cancelled) {
        mockAbort = startMockResearch(brief, onEvent);
      }
    });
    return () => {
      cancelled = true;
      mockAbort?.();
    };
  }

  const controller = new AbortController();

  fetch(`${API_BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, session_id: getClientSessionId() }),
    signal: controller.signal,
  })
    .then((res) => {
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      function pump(): Promise<void> {
        return reader.read().then(({ done, value }) => {
          if (done) return;
          buffer += decoder.decode(value, { stream: true });

          const blocks = buffer.split("\n\n");
          buffer = blocks.pop()!;

          for (const block of blocks) {
            let eventType = "";
            let data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event: ")) eventType = line.slice(7);
              else if (line.startsWith("data: ")) data = line.slice(6);
            }
            if (eventType && data) {
              onEvent({ type: eventType, ...JSON.parse(data) } as ResearchEvent);
            }
          }

          return pump();
        });
      }

      return pump();
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onEvent({ type: "error", message: err.message });
      }
    });

  return () => controller.abort();
}
