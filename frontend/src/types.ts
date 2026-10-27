export interface KnowledgeBase {
  id: string;
  name: string;
  created_at?: string;
}

export interface DocVersion {
  version: number;
  status: string;
  chunk_count: number | null;
  created_at: string;
}

export interface DocumentItem {
  id: string;
  title: string;
  doc_type: string;
  current_version: number;
  status: string;
  version_policy: string;
  chunk_count: number | null;
  versions: DocVersion[];
  updated_at: string;
}

export interface IngestStatus {
  status: string;
  stage: string;
  progress: number;
  error?: string | null;
}

export interface Citation {
  n: number;
  chunk_id: string;
  doc_id?: string;
  doc_title: string;
  page: number | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  route?: string;
  latency_ms?: number;
  error?: string;
  logId?: string;
  feedback?: number;
}
