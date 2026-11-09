// Shapes of /api/admin/debug/* (backend app/admin/debug.py, app/admin/inspect.py).

export type Outcome =
  "ok" | "cache" | "503" | "quota" | "400" | "fallback" | "forced" | "repair" | "error";

export interface CallRow {
  id: number;
  ts: string;
  task_kind: string;
  lane: string | null;
  tier: string;
  provider: string;
  model: string;
  pattern: string;
  status_code: number | null;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cache_hit: boolean;
  single_flight: boolean;
  fallback: boolean;
  forced: boolean;
  refusal_reason: string | null;
  request_hash: string | null;
  job_id: string | null;
  attempt: number | null;
  debug: boolean;
  outcome: Outcome;
  traced?: boolean;
}

export interface WorkerLive {
  worker_id: string;
  updated_at: string;
  age_s: number;
  fresh: boolean;
  started_at?: string;
  in_flight?: Record<string, number>;
  lane_limits?: Record<string, number>;
  job_ids?: string[];
  last_error?: { t: string; job_id: string; kind: string; error: string } | null;
  provider?: string;
  offline?: boolean;
  offline_reason?: string | null;
  slot_live?: boolean;
  quota?: {
    remaining: number | null;
    reset_s: number | null;
    low: boolean;
    background_pause_s: number;
  };
  limiter?: {
    active: number;
    concurrency: number;
    max_active: number;
    waiting: Record<string, number>;
    buckets: Record<string, { tokens: number; capacity: number; rpm: number }>;
    rpm_last_60s: Record<string, number>;
  };
  flags?: Record<string, unknown>;
  status_error?: string;
}

export interface Live {
  now: string;
  workers: WorkerLive[];
  queue: {
    lane: string;
    ready: number;
    waiting: number;
    running: number;
    next_not_before: string | null;
  }[];
  calls_per_minute: { minute: string; tier: string; calls: number }[];
  flags: Record<string, unknown>;
  trace_on: boolean;
  app_env: string;
  last_calls: CallRow[];
}

export interface JobEvent {
  t: string;
  type: string;
  stage?: string;
  reason?: string;
  delay_s?: number;
  error?: string;
  worker?: string;
  quick_mode?: boolean;
  lane?: string;
  cost?: number;
}

export interface Timeline {
  job: {
    id: string;
    kind: string;
    lane: string;
    status: string;
    stage: string | null;
    stages: string[];
    attempts: number;
    not_before: string | null;
    cost: number;
    quick_mode: boolean;
    provider: string | null;
    error: string | null;
    user_id: string | null;
    user: string | null;
    world_id: string | null;
    worker_id: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
  };
  events: JobEvent[];
  calls: CallRow[];
  coins: { created_at: string; day: string; bucket: string; kind: string; delta: number }[];
  pool: { kind: string; delta: number; world_id: string }[];
  result: unknown;
}

export interface Trace {
  created_at: string;
  messages: { role: string; content: string }[] | null;
  reply: string | null;
  reply_without_think: string | null;
  parsed: unknown;
  error: string | null;
}

export interface CallDetail {
  call: CallRow;
  trace: Trace | null;
  repair: (CallRow & { trace: Trace | null }) | null;
  replay: { available: boolean; targets: string[]; reason: string | null } | null;
  tracing_note: string | null;
}

export interface ReplayResult {
  job_id: string;
  status: string;
  error: string | null;
  edited: boolean;
  result: {
    content: unknown;
    model: string;
    model_tier: string;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
    notes: string[];
    target: string;
  } | null;
}

export interface Routing {
  since: string;
  provider: string;
  kinds: {
    task_kind: string;
    expected: { tier: string; pattern: string } | null;
    actual: { tier: string; pattern: string; calls: number; flag: string | null }[];
  }[];
  repeats: {
    request_hash: string;
    task_kind: string;
    calls: number;
    first: string;
    last: string;
    call_ids: number[];
    purge_between: boolean;
  }[];
  flags: number;
}

export interface Invariant {
  check: string;
  ok: boolean;
  description: string;
  rows: Record<string, unknown>[];
}

export interface LedgerRow {
  created_at: string;
  bucket: string;
  kind: string;
  delta: number;
  ref: string | null;
}

export interface Student {
  user: { id: string; nickname: string; ui_language: string; created_at: string };
  wallet: {
    free: number;
    earned: number;
    purchased: number;
    coins: number;
    today: string;
    earned_today: number;
    daily_earn_cap: number;
    pass_until: string | null;
    pass_active: boolean;
    pass_used_today: number;
    pass_daily_limit: number;
    has_daily_row_today: boolean;
    spending_order: string[];
    days: { day: string; rows: LedgerRow[]; net: number; earned: number }[];
  };
  points: {
    total: number;
    streak: number;
    rows: {
      created_at: string;
      world_id: string | null;
      delta: number;
      reason: string;
      ref: string;
    }[];
    ranks: {
      scope: string;
      world_id: string | null;
      period: string;
      rank: number | null;
      points: number;
      opted_in: boolean;
    }[];
  };
  learning: {
    levels: {
      course_id: string;
      course: string;
      level: string;
      placed_at: string;
      goal: string | null;
    }[];
    mastery: {
      chapter_id: string;
      chapter: string;
      course_id: string;
      mastery: number;
      weak: boolean;
    }[];
  };
  daily: {
    date: string;
    challenges: {
      type: string;
      target: number;
      progress: number;
      done: boolean;
      why?: string | null;
      chapter_id?: string | null;
    }[];
    plan: unknown;
    planned_by: string;
    plan_job_id: string | null;
    seen_at: string | null;
  } | null;
  activity: {
    quiz_attempts: {
      id: string;
      level: string;
      language: string;
      status: string;
      score: number;
      points: number;
      second_tries: number;
      answers: unknown[] | null;
    }[];
    tutor_sessions: {
      id: string;
      status: string;
      turns: number;
      hints_used: number;
      stuck_count: number;
      escalations: number;
      summary: unknown;
    }[];
    peer_questions: { id: string; status: string }[];
    peer_answers: {
      id: string;
      status: string;
      ai_score: number | null;
      ai_confidence: string | null;
      reviewed_by_mid: boolean;
      rewarded: boolean;
    }[];
    flashcard_reviews: { card_id: string }[];
    jobs: {
      id: string;
      kind: string;
      status: string;
      cost: number;
      error: string | null;
      created_at: string;
    }[];
  };
  invariants: Invariant[];
}

export interface PriceExplain {
  activity: string;
  base_cost: number;
  cached: boolean;
  exam_pass: boolean;
  pool: { balance: number; can_pay: boolean } | null;
  split: Record<string, number>;
  pays: number;
  affordable: boolean;
  steps: string[];
}
