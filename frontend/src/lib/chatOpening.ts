import { createMercurySession } from './mercury';
import {
  ApiError,
  createGuideSession,
  dispatchStreamEvent,
  ensureIdentity,
  fetchApi,
  getGuideSession,
  getStoredSessionId,
  storeSessionId,
  type PlanSelection,
  type TurnResponse,
  type TurnStreamCallbacks,
  type TurnStreamEvent,
} from './saleGuide';

const OPENING_KEY = 'ceres-v3-opening-id';
const MERCURY_SESSION_KEY = 'ceres-mercury-session-id';

export type ChatRole = 'keke' | 'momo';

export interface OpeningView {
  opening_id: string;
  guide_session_id: string;
  mercury_session_id: string;
  role: ChatRole;
  prompt_displayed?: boolean;
  handoff_id?: string | null;
}

export interface ServiceRoutePayload {
  decision: 'stay_current' | 'suggest_switch' | 'clarify' | null;
  status?: string;
  target_role?: ChatRole;
  handoff_id?: string;
  prompt_mode?: 'automatic' | 'fixed_entry' | 'none';
  request_id?: string;
  message?: string;
  current_role?: ChatRole;
}

export interface OpeningTurnCallbacks extends TurnStreamCallbacks {
  onServiceRoute?: (route: ServiceRoutePayload) => void;
  onRoutePrompt?: (message: string, route: ServiceRoutePayload) => void;
  onMercuryDelta?: (text: string) => void;
  onMercuryOrders?: (orders: unknown[]) => void;
  onMercuryCompleted?: (finalText: string) => void;
}

export interface OpeningTurnResult {
  kind: 'business';
  turn: TurnResponse;
}

export interface OpeningRouteOnlyResult {
  kind: 'route_only';
  message: string;
  route: ServiceRoutePayload;
}

function storedOpeningId(): string | null {
  if (typeof window === 'undefined') return null;
  return sessionStorage.getItem(OPENING_KEY);
}

function storeOpeningId(id: string) {
  sessionStorage.setItem(OPENING_KEY, id);
}

export async function getMercurySessionId(): Promise<string> {
  if (typeof window === 'undefined') return '';
  const stored = sessionStorage.getItem(MERCURY_SESSION_KEY);
  if (stored) return stored;
  const id = await createMercurySession();
  sessionStorage.setItem(MERCURY_SESSION_KEY, id);
  return id;
}

async function ensureGuideSession(entryContext: Record<string, unknown>): Promise<string> {
  const stored = getStoredSessionId();
  if (stored) {
    try {
      await getGuideSession(stored, false);
      return stored;
    } catch {
      /* recreate */
    }
  }
  const session = await createGuideSession(entryContext);
  return session.session_id;
}

export async function fetchOpening(openingId: string): Promise<OpeningView> {
  return fetchApi<OpeningView>(`/api/v1/chat/openings/${encodeURIComponent(openingId)}`);
}

export async function createOpening(
  guideSessionId: string,
  mercurySessionId: string,
  role: ChatRole,
): Promise<OpeningView> {
  const view = await fetchApi<OpeningView>('/api/v1/chat/openings', {
    method: 'POST',
    body: JSON.stringify({
      guide_session_id: guideSessionId,
      mercury_session_id: mercurySessionId,
      role,
    }),
  });
  storeOpeningId(view.opening_id);
  return view;
}

export async function ensureOpening(
  entryRole: ChatRole,
  entryContext: Record<string, unknown>,
): Promise<OpeningView> {
  await ensureIdentity();
  const guideSessionId = await ensureGuideSession(entryContext);
  storeSessionId(guideSessionId);
  const mercurySessionId = await getMercurySessionId();

  const existingId = storedOpeningId();
  if (existingId) {
    try {
      let view = await fetchOpening(existingId);
      if (view.guide_session_id !== guideSessionId || view.mercury_session_id !== mercurySessionId) {
        view = await createOpening(guideSessionId, mercurySessionId, entryRole);
        return view;
      }
      if (view.role !== entryRole) {
        await streamRoleSwitch(existingId, { accept: true, target_role: entryRole });
        view = await fetchOpening(existingId);
      }
      return view;
    } catch {
      sessionStorage.removeItem(OPENING_KEY);
    }
  }

  return createOpening(guideSessionId, mercurySessionId, entryRole);
}

export async function markPromptDisplayed(openingId: string, handoffId: string): Promise<OpeningView> {
  return fetchApi<OpeningView>(
    `/api/v1/chat/openings/${encodeURIComponent(openingId)}/prompt-displayed`,
    {
      method: 'POST',
      body: JSON.stringify({ handoff_id: handoffId }),
    },
  );
}

export interface SwitchBody {
  accept: boolean;
  target_role: ChatRole;
  handoff_id?: string;
}

function parseV3Block(block: string): { type: string; payload: Record<string, unknown> } | null {
  const trimmed = block.trim();
  if (!trimmed || trimmed.startsWith(':')) return null;
  let eventName: string | null = null;
  let dataLine: string | null = null;
  for (const line of trimmed.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('event: ')) eventName = line.slice(7).trim();
    if (line.startsWith('data: ')) dataLine = line.slice(6);
  }
  if (!dataLine) return null;
  try {
    const body = JSON.parse(dataLine) as Record<string, unknown>;
    if (eventName) return { type: eventName, payload: body };
    const type = String(body.type ?? '');
    if (typeof body.protocol_version === 'number' && type) {
      return { type, payload: body };
    }
    const payload = (body.payload ?? body) as Record<string, unknown>;
    return type ? { type, payload } : null;
  } catch {
    return null;
  }
}

function consumeV3Buffer(
  buffer: string,
  onBlock: (block: { type: string; payload: Record<string, unknown> }) => void,
): string {
  const normalized = buffer.replace(/\r\n/g, '\n');
  const parts = normalized.split('\n\n');
  const remainder = parts.pop() ?? '';
  for (const part of parts) {
    const parsed = parseV3Block(part);
    if (parsed) onBlock(parsed);
  }
  return remainder;
}

function dispatchMercuryPayload(
  type: string,
  payload: Record<string, unknown>,
  callbacks: OpeningTurnCallbacks,
): void {
  switch (type) {
    case 'answer.delta':
      if (typeof payload.text === 'string') callbacks.onMercuryDelta?.(payload.text);
      break;
    case 'orders':
      callbacks.onMercuryOrders?.((payload.items as unknown[]) ?? []);
      break;
    case 'turn.completed':
      if (typeof payload.final_text === 'string') callbacks.onMercuryCompleted?.(payload.final_text);
      else if (typeof payload.message === 'string') callbacks.onMercuryCompleted?.(payload.message);
      break;
    case 'error':
      callbacks.onError?.({
        type: 'error',
        protocol_version: 1,
        run_id: '',
        sequence: 0,
        session_id: '',
        payload,
      } as TurnStreamEvent);
      break;
    default:
      break;
  }
}

function guideEventFromBlock(block: { type: string; payload: Record<string, unknown> }): TurnStreamEvent | null {
  if (block.type === 'service.route' || block.type === 'service.switch') return null;
  if (typeof block.payload.protocol_version === 'number' && typeof block.payload.type === 'string') {
    return block.payload as unknown as TurnStreamEvent;
  }
  return {
    type: block.type,
    protocol_version: 1,
    run_id: '',
    sequence: 0,
    session_id: String(block.payload.session_id ?? ''),
    payload: block.payload,
  } as TurnStreamEvent;
}

function buildOpeningTurnBody(
  message: string,
  requestId: string,
  expectedStateVersion: number,
  expectedTaskId: string | null,
  expectedSessionVersion: number | null | undefined,
  viewContext?: { page: string; category_id?: string | null; product_id?: string | null },
  planSelection?: PlanSelection,
  orderId?: string | null,
) {
  return {
    request_id: requestId,
    message,
    expected_task_id: expectedTaskId,
    expected_state_version: expectedStateVersion,
    expected_session_version: expectedSessionVersion ?? undefined,
    view_context: viewContext,
    plan_selection: planSelection,
    order_id: orderId ?? undefined,
  };
}

async function readOpeningStream(
  res: Response,
  role: ChatRole,
  callbacks: OpeningTurnCallbacks,
): Promise<{ route: ServiceRoutePayload | null; turn: TurnResponse | null; routeOnly: OpeningRouteOnlyResult | null }> {
  if (!res.body) throw new Error('Stream body missing');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let route: ServiceRoutePayload | null = null;
  let turnResult: TurnResponse | null = null;
  let routeOnly: OpeningRouteOnlyResult | null = null;

  const handleBlock = (block: { type: string; payload: Record<string, unknown> }) => {
    if (block.type === 'service.route') {
      route = block.payload as ServiceRoutePayload;
      callbacks.onServiceRoute?.(route);
      return;
    }
    if (block.type === 'service.switch') return;
    if (block.type === 'turn.completed' && block.payload.business_not_run) {
      const message = String(block.payload.message ?? '');
      if (route) {
        routeOnly = { kind: 'route_only', message, route };
        callbacks.onRoutePrompt?.(message, route);
      }
      return;
    }

    if (role === 'momo') {
      dispatchMercuryPayload(block.type, block.payload, callbacks);
      if (block.type === 'turn.completed' && !block.payload.business_not_run) {
        turnResult = {
          message: String(block.payload.final_text ?? block.payload.message ?? ''),
          task_id: '',
          state_version: 0,
          session_version: 0,
          status: 'completed',
        } as TurnResponse;
      }
      return;
    }

    const guideEvent = guideEventFromBlock(block);
    if (guideEvent) {
      const completed = dispatchStreamEvent(guideEvent, callbacks);
      if (completed) turnResult = completed;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      buffer = consumeV3Buffer(buffer, handleBlock);
    }
    if (done) break;
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeV3Buffer(`${buffer}\n\n`, handleBlock);

  return { route, turn: turnResult, routeOnly };
}

export async function sendOpeningTurnStream(
  openingId: string,
  role: ChatRole,
  message: string,
  requestId: string,
  expectedTaskId: string | null,
  expectedStateVersion: number,
  expectedSessionVersion: number | null | undefined,
  viewContext: { page: string; category_id?: string | null; product_id?: string | null } | undefined,
  callbacks: OpeningTurnCallbacks,
  planSelection?: PlanSelection,
  orderId?: string | null,
): Promise<OpeningTurnResult | OpeningRouteOnlyResult> {
  await ensureIdentity();
  const res = await fetch(
    `/api/v1/chat/openings/${encodeURIComponent(openingId)}/turns/stream`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      signal: callbacks.signal,
      body: JSON.stringify(
        buildOpeningTurnBody(
          message,
          requestId,
          expectedStateVersion,
          expectedTaskId,
          expectedSessionVersion,
          viewContext,
          planSelection,
          orderId,
        ),
      ),
    },
  );

  if (!res.ok || !res.body) {
    const payload = await res.json().catch(() => ({}));
    const body = payload?.error || {};
    throw new ApiError(body.message || res.statusText, body.code || 'STREAM_FAILED', {
      taskId: payload.task_id,
      stateVersion: payload.state_version,
      sessionVersion: payload.session_version,
      retryable: body.retryable,
    });
  }

  const { turn, routeOnly } = await readOpeningStream(res, role, callbacks);
  if (routeOnly) return routeOnly;
  if (!turn) throw new Error('Stream ended without turn.completed');
  return { kind: 'business', turn };
}

export async function streamRoleSwitch(
  openingId: string,
  body: SwitchBody,
  callbacks: OpeningTurnCallbacks = {},
  roleAfterSwitch: ChatRole = body.target_role,
): Promise<OpeningView | null> {
  await ensureIdentity();
  const res = await fetch(
    `/api/v1/chat/openings/${encodeURIComponent(openingId)}/switches/stream`,
    {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      signal: callbacks.signal,
      body: JSON.stringify(body),
    },
  );

  if (!res.ok || !res.body) {
    const payload = await res.json().catch(() => ({}));
    const err = payload?.error || {};
    throw new ApiError(err.message || res.statusText, err.code || 'SWITCH_FAILED');
  }

  await readOpeningStream(res, roleAfterSwitch, callbacks);
  if (body.accept) {
    return fetchOpening(openingId);
  }
  return null;
}

export async function fixedRoleSwitch(openingId: string, targetRole: ChatRole): Promise<OpeningView> {
  const view = await streamRoleSwitch(openingId, { accept: true, target_role: targetRole });
  return view ?? fetchOpening(openingId);
}
