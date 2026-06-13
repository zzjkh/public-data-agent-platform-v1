import type { QaResponse, RouteType } from '../api/qa';

const STORAGE_PREFIX = 'public-data-agent:qa-session:v1';
const ROUTE_TYPES = new Set<RouteType>(['POLICY_QA', 'DATA_QA', 'HYBRID_QA', 'OTHER']);

export interface QaPageSession {
  question: string;
  response: QaResponse | null;
  savedAt: string;
}

export function loadQaPageSession(username: string): QaPageSession | null {
  const key = qaSessionKey(username);
  const raw = sessionStorage.getItem(key);
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isQaPageSession(parsed)) {
      sessionStorage.removeItem(key);
      return null;
    }
    return parsed;
  } catch {
    sessionStorage.removeItem(key);
    return null;
  }
}

export function saveQaPageSession(
  username: string,
  question: string,
  response: QaResponse | null,
) {
  const session: QaPageSession = {
    question,
    response,
    savedAt: new Date().toISOString(),
  };
  sessionStorage.setItem(qaSessionKey(username), JSON.stringify(session));
}

export function clearQaPageSession(username: string) {
  sessionStorage.removeItem(qaSessionKey(username));
}

export function qaSessionKey(username: string) {
  return `${STORAGE_PREFIX}:${encodeURIComponent(username || 'anonymous')}`;
}

function isQaPageSession(value: unknown): value is QaPageSession {
  if (!isRecord(value) || typeof value.question !== 'string' || typeof value.savedAt !== 'string') {
    return false;
  }
  return value.response === null || isQaResponse(value.response);
}

function isQaResponse(value: unknown): value is QaResponse {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.trace_id === 'string' &&
    typeof value.route_type === 'string' &&
    ROUTE_TYPES.has(value.route_type as RouteType) &&
    typeof value.answer === 'string' &&
    Array.isArray(value.citations) &&
    (value.sql === null || isRecord(value.sql)) &&
    (value.chart === null || isRecord(value.chart)) &&
    typeof value.request_id === 'string'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
