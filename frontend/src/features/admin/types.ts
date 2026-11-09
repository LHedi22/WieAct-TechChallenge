// Row shapes of the admin read endpoints (backend app/admin/browse.py). Those endpoints return
// plain dicts, so openapi-typescript can't type them; keep these in step with browse.py.
export interface WalletRow {
  free: number;
  earned: number;
  purchased: number;
  coins: number;
  pass_until: string | null;
  pass_active: boolean;
}

export interface UserRow {
  id: string;
  nickname: string;
  created_at: string;
  ui_language: string;
  worlds: number;
  wallet: WalletRow;
  points: number;
  streak: number;
  last_seen: string | null;
  dev_user: boolean;
}

export interface LedgerRow {
  created_at: string;
  day?: string;
  bucket?: string;
  kind?: string;
  reason?: string;
  delta: number;
  ref: string | null;
}

export interface JobRow {
  id: string;
  kind: string;
  lane: string;
  status: string;
  stage: string | null;
  attempts: number;
  not_before: string | null;
  cost: number;
  error: string | null;
  quick_mode: boolean;
  provider: string | null;
  user_id: string | null;
  user?: string | null;
  world_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface UserDetail {
  id: string;
  nickname: string;
  ui_language: string;
  created_at: string;
  session_epoch: number;
  dev_user: boolean;
  wallet: WalletRow;
  points: number;
  streak: number;
  worlds: { id: string; name: string; join_code: string; joined_at: string }[];
  levels: { course_id: string; course: string; level: string; placed_at: string }[];
  counts: Record<string, number>;
  coin_ledger: LedgerRow[];
  points_ledger: LedgerRow[];
  jobs: JobRow[];
}

export interface WorldRow {
  id: string;
  name: string;
  join_code: string;
  creator: string | null;
  members: number;
  courses: number;
  documents: number;
  failed_documents: number;
  pool: number;
}

export interface DocumentRow {
  id: string;
  filename: string;
  kind: string;
  size: number;
  status: string;
  progress: number;
  error: string | null;
  page_count: number | null;
  tagged_by: string | null;
  created_at: string;
}

export interface WorldDetail {
  id: string;
  name: string;
  join_code: string;
  creator: string | null;
  members: { id: string; nickname: string; joined_at: string }[];
  courses: {
    id: string;
    name: string;
    exam_date: string | null;
    chapters: { id: string; idx: number; title: string; documents: DocumentRow[] }[];
  }[];
  pool: {
    balance: number;
    history: {
      created_at: string;
      kind: string;
      delta: number;
      ref: string | null;
      by: string | null;
    }[];
  };
}

export type ContentKind =
  "quiz_sets" | "study_assets" | "wisdom_tips" | "placement_sets" | "flashcards";

export interface ContentRow {
  id: string;
  created_at: string;
  provider: string | null;
  edited_by_admin: boolean;
  world_id: string | null;
  chapter_id: string | null;
  course_id?: string;
  level: string | null;
  language: string | null;
  summary: string;
  source?: string;
  personal?: boolean;
  body?: unknown;
}

export interface QuestionRow {
  id: string;
  created_at: string;
  author: string;
  text: string;
  language: string;
  status: string;
  reject_reason: string | null;
  pinned_answer_id: string | null;
  answers: number;
  world_id: string;
  chapter_id: string;
}

export interface AnswerRow {
  id: string;
  created_at: string;
  author: string;
  question_id: string;
  question: string;
  pinned: boolean;
  text: string;
  status: string;
  ai_score: number | null;
  ai_confidence: string | null;
  reviewed_by_mid: boolean;
  rewarded: boolean;
  feedback: unknown;
}

export interface CacheRow {
  key: string;
  task_kind: string;
  provider: string;
  model: string;
  model_tier: string;
  hits: number;
  created_at: string;
  age_s: number;
  size_bytes: number;
}

export interface ActionRow {
  id: number;
  ts: string;
  actor: string;
  action: string;
  target_kind: string | null;
  target_id: string | null;
  before: unknown;
  after: unknown;
  reason: string | null;
}
