const http = require('http');
const fs = require('fs');
const path = require('path');

const CCR_PORT = parseInt(process.env.CCR_PORT || '3456', 10);
const PROXY_PORT = parseInt(process.env.PROXY_PORT || '3457', 10);
const PROVIDER_PROXY_PORT = parseInt(process.env.PROVIDER_PROXY_PORT || '3458', 10);
const PROVIDER_PROXY_HOST = process.env.PROVIDER_PROXY_HOST || '127.0.0.1';
const MODEL_NAME = process.env.MODEL_NAME || 'claude-sonnet-4-6';
const UPSTREAM_BASE_URL = process.env.UPSTREAM_BASE_URL;
const UPSTREAM_API_KEY = process.env.UPSTREAM_API_KEY;
const OPENROUTER_VERBOSITY = process.env.OPENROUTER_VERBOSITY || '';
const OPENROUTER_REASONING_ENABLED = process.env.OPENROUTER_REASONING_ENABLED === 'true';
const PROVIDER_EXTRA_BODY_JSON = process.env.PROVIDER_EXTRA_BODY_JSON || '';
const PROVIDER_EXTRA_HEADERS_JSON = process.env.PROVIDER_EXTRA_HEADERS_JSON || '';
const PROVIDER_STRIP_MAX_TOKENS = process.env.PROVIDER_STRIP_MAX_TOKENS === '1' || process.env.PROVIDER_STRIP_MAX_TOKENS === 'true';
const PROVIDER_STRIP_CACHE_CONTROL = process.env.PROVIDER_STRIP_CACHE_CONTROL === '1' || process.env.PROVIDER_STRIP_CACHE_CONTROL === 'true';
const PROVIDER_FIX_CACHE_CONTROL = process.env.PROVIDER_FIX_CACHE_CONTROL === '1' || process.env.PROVIDER_FIX_CACHE_CONTROL === 'true';
const PROVIDER_DEFAULT_MAX_TOKENS = process.env.PROVIDER_DEFAULT_MAX_TOKENS || '';
const PROVIDER_RETRY_MAX_ATTEMPTS = Math.max(1, parseInt(process.env.PROVIDER_RETRY_MAX_ATTEMPTS || '5', 10) || 5);
const PROVIDER_RETRY_BASE_MS = Math.max(100, parseInt(process.env.PROVIDER_RETRY_BASE_MS || '2000', 10) || 2000);
// Force upstream streaming and reassemble the full completion in the proxy.
// Non-streaming ModelHub gateway requests are cut at ~300s, which long
// high-effort turns on large contexts routinely exceed; a streaming
// connection stays alive while tokens flow. The client still receives a
// complete response in whichever shape (JSON or SSE) it asked for, and
// upstream retry stays possible because nothing is sent to the client until
// the upstream finishes.
const PROVIDER_UPSTREAM_STREAM = process.env.PROVIDER_UPSTREAM_STREAM === '1' || process.env.PROVIDER_UPSTREAM_STREAM === 'true';
// Verbatim Anthropic passthrough with retry. Claude Code in native Anthropic
// mode talks directly to the endpoint and only has its own small retry
// budget; pointing ANTHROPIC_BASE_URL at this proxy adds the
// PROVIDER_RETRY_MAX_ATTEMPTS budget for 429 quota storms. Request bodies and
// paths pass through untouched; successful responses are piped (streaming
// included), only pre-body failures are retried.
const PROVIDER_ANTHROPIC_PASSTHROUGH = process.env.PROVIDER_ANTHROPIC_PASSTHROUGH === '1' || process.env.PROVIDER_ANTHROPIC_PASSTHROUGH === 'true';
// Cap exponential retry backoff so long retry budgets stay practical.
const PROVIDER_RETRY_MAX_DELAY_MS = Math.max(1000, parseInt(process.env.PROVIDER_RETRY_MAX_DELAY_MS || '60000', 10) || 60000);
const METRICS_PATH = process.env.METRICS_PATH || path.join(process.env.WORKSPACE || process.cwd(), 'metrics.json');
const IS_EXACT_PROVIDER_ENDPOINT = String(UPSTREAM_BASE_URL || '').toLowerCase().includes('/v2/crawl');

// Rough estimate: 1 token ≈ 4 chars for English, ≈ 2 chars for Chinese
const CHARS_PER_TOKEN = 3.5;

const metrics = {
  total_requests: 0,
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cache_read_tokens: 0,
  total_cache_creation_tokens: 0,
  effective_requests: 0,
  effective_input_tokens: 0,
  effective_output_tokens: 0,
  retry_requests: 0,
  usage_source: 'none', // 'api' if real usage found, 'estimated' if fallback
  requests: [],
};

function saveMetrics() {
  try {
    fs.mkdirSync(path.dirname(METRICS_PATH), { recursive: true });
    fs.writeFileSync(METRICS_PATH, JSON.stringify(metrics, null, 2));
  } catch (e) {
    console.error('Failed to save metrics:', e.message);
  }
}

const saveInterval = setInterval(saveMetrics, 30000);
process.on('SIGTERM', () => { saveMetrics(); process.exit(0); });
process.on('SIGINT', () => { saveMetrics(); process.exit(0); });
process.on('exit', saveMetrics);

const MODELS_RESPONSE = JSON.stringify({
  data: [
    { id: 'claude-sonnet-4-6', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: 'claude-opus-4-7', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: 'claude-haiku-4-5-20251001', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: MODEL_NAME, object: 'model', created: 1700000000, owned_by: 'anthropic' },
  ],
  object: 'list',
});

function estimateTokens(text) {
  return Math.ceil((text || '').length / CHARS_PER_TOKEN);
}

function extractUsageFromChunks(body) {
  const usage = {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    source: 'none',
  };

  // Try non-streaming JSON
  try {
    const json = JSON.parse(body);
    if (json.usage) {
      usage.input_tokens = json.usage.input_tokens || json.usage.prompt_tokens || 0;
      usage.output_tokens = json.usage.output_tokens || json.usage.completion_tokens || 0;
      usage.cache_read_tokens = json.usage.cache_read_input_tokens || 0;
      usage.cache_creation_tokens = json.usage.cache_creation_input_tokens || 0;
      usage.source = 'api';
      return usage;
    }
  } catch (e) {}

  // Parse SSE stream
  let outputText = '';
  const lines = body.split('\n');
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const data = line.slice(6).trim();
    if (data === '[DONE]') continue;
    try {
      const event = JSON.parse(data);

      // Anthropic format: message_start has input usage
      if (event.type === 'message_start' && event.message?.usage) {
        usage.input_tokens = event.message.usage.input_tokens || 0;
        usage.cache_read_tokens = event.message.usage.cache_read_input_tokens || 0;
        usage.cache_creation_tokens = event.message.usage.cache_creation_input_tokens || 0;
        usage.source = 'api';
      }
      // Anthropic format: message_delta has output usage
      if (event.type === 'message_delta' && event.usage) {
        usage.output_tokens = event.usage.output_tokens || 0;
        usage.source = 'api';
      }
      // Anthropic format: collect output text for fallback estimation
      if (event.type === 'content_block_delta' && event.delta?.text) {
        outputText += event.delta.text;
      }

      // OpenAI format: usage in final chunk
      if (event.usage) {
        if (event.usage.prompt_tokens || event.usage.input_tokens) {
          usage.input_tokens = event.usage.prompt_tokens || event.usage.input_tokens;
          usage.source = 'api';
        }
        if (event.usage.completion_tokens || event.usage.output_tokens) {
          usage.output_tokens = event.usage.completion_tokens || event.usage.output_tokens;
          usage.source = 'api';
        }
      }
      // OpenAI format: collect output text for fallback
      if (event.choices?.[0]?.delta?.content) {
        outputText += event.choices[0].delta.content;
      }
    } catch (e) {}
  }

  // Fallback: if no API usage found, estimate output tokens from collected text
  if (usage.source === 'none' && outputText.length > 0) {
    usage.output_tokens = estimateTokens(outputText);
    usage.source = 'estimated';
  }

  return usage;
}

function extractInputFromRequest(body) {
  // Estimate input tokens from request body when API doesn't return usage
  try {
    const json = JSON.parse(body);
    // Anthropic format
    if (json.messages) {
      const text = JSON.stringify(json.messages) + (json.system || '');
      return estimateTokens(text);
    }
  } catch (e) {}
  return 0;
}

function buildUpstreamOptions(targetUrl, method, headers, bodyLength) {
  const upstream = new URL(targetUrl);
  const nextHeaders = { ...headers };
  nextHeaders.host = upstream.host;
  nextHeaders.authorization = `Bearer ${UPSTREAM_API_KEY}`;
  nextHeaders['content-length'] = bodyLength;
  delete nextHeaders.connection;
  delete nextHeaders['accept-encoding'];
  if (PROVIDER_EXTRA_HEADERS_JSON) {
    try {
      const extraHeaders = JSON.parse(PROVIDER_EXTRA_HEADERS_JSON);
      if (extraHeaders && typeof extraHeaders === 'object' && !Array.isArray(extraHeaders)) {
        for (const [key, value] of Object.entries(extraHeaders)) {
          const normalized = String(key).toLowerCase();
          if (normalized === 'content-length' || normalized === 'host' || normalized === 'connection') {
            continue;
          }
          nextHeaders[key] = String(value);
        }
      }
    } catch (e) {
      console.error(`Invalid PROVIDER_EXTRA_HEADERS_JSON: ${e.message}`);
    }
  }
  return {
    protocol: upstream.protocol,
    hostname: upstream.hostname,
    port: upstream.port || (upstream.protocol === 'https:' ? 443 : 80),
    path: upstream.pathname + upstream.search,
    method,
    headers: nextHeaders,
  };
}

function isAnthropicNativeUrl(targetUrl) {
  return String(targetUrl || '').includes('/anthropic');
}

function anthropicMessagesUrl(targetUrl) {
  const base = String(targetUrl || '').replace(/\/$/, '');
  if (base.endsWith('/v1/messages') || base.endsWith('/messages')) {
    return base;
  }
  return `${base}/v1/messages`;
}

function textFromContent(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((part) => {
      if (typeof part === 'string') return part;
      if (part?.type === 'text') return part.text || '';
      if (part?.text) return part.text;
      return '';
    }).join('');
  }
  return content == null ? '' : String(content);
}

function stripProviderOnlyFields(value) {
  if (Array.isArray(value)) {
    return value.map(stripProviderOnlyFields);
  }
  if (value && typeof value === 'object') {
    const next = {};
    for (const [key, item] of Object.entries(value)) {
      if (key === 'cache_control') continue;
      next[key] = stripProviderOnlyFields(item);
    }
    return next;
  }
  return value;
}

function stripGeminiUnsupportedSchemaFields(value) {
  if (Array.isArray(value)) {
    return value.map(stripGeminiUnsupportedSchemaFields);
  }
  if (value && typeof value === 'object') {
    const next = {};
    for (const [key, item] of Object.entries(value)) {
      if ([
        '$schema',
        '$id',
        'propertyNames',
        'exclusiveMinimum',
        'exclusiveMaximum',
        'const',
        'examples',
      ].includes(key)) {
        continue;
      }
      if (key === 'additionalProperties') {
        if (item === false || item === true) continue;
      }
      next[key] = stripGeminiUnsupportedSchemaFields(item);
    }
    return next;
  }
  return value;
}

function providerCompatibleToolParameters(parameters) {
  let next = stripProviderOnlyFields(parameters);
  if (String(MODEL_NAME).toLowerCase().includes('gemini')) {
    next = stripGeminiUnsupportedSchemaFields(next);
  }
  return next;
}

function normalizeProviderTools(payload) {
  if (!Array.isArray(payload.tools)) return;
  const tools = [];
  for (const tool of payload.tools) {
    if (!tool || typeof tool !== 'object') continue;
    const source = tool.function || tool.custom || tool;
    const name = source.name || tool.name;
    if (!name) continue;
    const parameters = source.parameters || source.input_schema || source.inputSchema || {
      type: 'object',
      properties: {},
    };
    tools.push({
      type: 'function',
      function: {
        name,
        description: source.description || tool.description || '',
        parameters: providerCompatibleToolParameters(parameters),
      },
    });
  }
  payload.tools = tools;

  const choice = payload.tool_choice;
  if (choice && typeof choice === 'object') {
    if (choice.type === 'auto') payload.tool_choice = 'auto';
    else if (choice.type === 'any') payload.tool_choice = 'required';
    else if (choice.name) {
      payload.tool_choice = { type: 'function', function: { name: choice.name } };
    } else if (choice.function?.name) {
      payload.tool_choice = { type: 'function', function: { name: choice.function.name } };
    }
  }
}

function openAiToAnthropicPayload(bodyText) {
  const payload = JSON.parse(bodyText || '{}');
  const systemParts = [];
  const messages = [];
  for (const msg of payload.messages || []) {
    const role = msg.role === 'assistant' ? 'assistant' : 'user';
    if (msg.role === 'system') {
      systemParts.push(textFromContent(msg.content));
      continue;
    }
    messages.push({ role, content: textFromContent(msg.content) });
  }
  const next = {
    model: MODEL_NAME,
    messages,
  };
  if (!PROVIDER_STRIP_MAX_TOKENS) {
    const requestedMaxTokens = payload.max_tokens || payload.max_completion_tokens || PROVIDER_DEFAULT_MAX_TOKENS;
    if (requestedMaxTokens) {
      next.max_tokens = Number.isNaN(Number(requestedMaxTokens)) ? requestedMaxTokens : Number(requestedMaxTokens);
    }
  }
  if (systemParts.length) next.system = systemParts.join('\n\n');
  if (payload.temperature !== undefined) next.temperature = payload.temperature;
  if (payload.top_p !== undefined) next.top_p = payload.top_p;
  return next;
}

function anthropicToOpenAiCompletion(rawBody, stream) {
  let parsed;
  try {
    parsed = JSON.parse(rawBody || '{}');
  } catch (e) {
    return { statusCode: 502, body: JSON.stringify({ error: { message: rawBody || 'invalid anthropic response' } }) };
  }
  const text = (parsed.content || []).map((part) => part?.text || '').join('');
  const promptTokens = parsed.usage?.input_tokens || 0;
  const completionTokens = parsed.usage?.output_tokens || 0;
  const response = {
    id: parsed.id || `chatcmpl-${Date.now()}`,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: parsed.model || MODEL_NAME,
    choices: [
      {
        index: 0,
        message: { role: 'assistant', content: text },
        finish_reason: parsed.stop_reason || 'stop',
      },
    ],
    usage: {
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: promptTokens + completionTokens,
    },
  };
  if (!stream) {
    return { statusCode: 200, body: JSON.stringify(response), contentType: 'application/json' };
  }
  const chunk = {
    id: response.id,
    object: 'chat.completion.chunk',
    created: response.created,
    model: response.model,
    choices: [{ index: 0, delta: { role: 'assistant', content: text }, finish_reason: null }],
  };
  const finalChunk = {
    id: response.id,
    object: 'chat.completion.chunk',
    created: response.created,
    model: response.model,
    choices: [{ index: 0, delta: {}, finish_reason: response.choices[0].finish_reason }],
    usage: response.usage,
  };
  return {
    statusCode: 200,
    contentType: 'text/event-stream',
    body: `data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(finalChunk)}\n\ndata: [DONE]\n\n`,
  };
}

function handleAnthropicNativeProvider(req, res, originalBody) {
  let openAiPayload;
  let anthropicPayload;
  try {
    openAiPayload = JSON.parse(originalBody || '{}');
    anthropicPayload = openAiToAnthropicPayload(originalBody);
  } catch (e) {
    res.writeHead(400, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: `Invalid request JSON: ${e.message}` } }));
    return;
  }
  const stream = Boolean(openAiPayload.stream);
  const shapedBody = Buffer.from(JSON.stringify(anthropicPayload));
  const options = buildUpstreamOptions(
    anthropicMessagesUrl(UPSTREAM_BASE_URL),
    'POST',
    {
      'content-type': 'application/json',
      'x-api-key': UPSTREAM_API_KEY,
      'anthropic-version': '2023-06-01',
      authorization: `Bearer ${UPSTREAM_API_KEY}`,
    },
    shapedBody.length,
  );
  const transport = options.protocol === 'https:' ? require('https') : http;
  const upstreamReq = transport.request(options, (upstreamRes) => {
    const chunks = [];
    upstreamRes.on('data', (chunk) => chunks.push(chunk));
    upstreamRes.on('end', () => {
      const rawBody = Buffer.concat(chunks).toString('utf-8');
      if (upstreamRes.statusCode < 200 || upstreamRes.statusCode >= 300) {
        res.writeHead(upstreamRes.statusCode || 502, { 'Content-Type': 'application/json' });
        res.end(rawBody);
        return;
      }
      const converted = anthropicToOpenAiCompletion(rawBody, stream);
      res.writeHead(converted.statusCode, { 'Content-Type': converted.contentType || 'application/json' });
      res.end(converted.body);
    });
  });
  upstreamReq.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: `Anthropic upstream proxy error: ${err.message}` } }));
  });
  upstreamReq.write(shapedBody);
  upstreamReq.end();
}

function shapeProviderRequest(bodyText) {
  let payload;
  try {
    payload = JSON.parse(bodyText);
  } catch (e) {
    return Buffer.from(bodyText);
  }

  payload.model = MODEL_NAME;

  if (PROVIDER_UPSTREAM_STREAM) {
    payload.stream = true;
  }

  if (PROVIDER_EXTRA_BODY_JSON) {
    try {
      const extraBody = JSON.parse(PROVIDER_EXTRA_BODY_JSON);
      if (extraBody && typeof extraBody === 'object' && !Array.isArray(extraBody)) {
        Object.assign(payload, extraBody);
      }
    } catch (e) {
      console.error(`Invalid PROVIDER_EXTRA_BODY_JSON: ${e.message}`);
    }
  }

  if (PROVIDER_STRIP_MAX_TOKENS) {
    delete payload.max_tokens;
    delete payload.max_completion_tokens;
  }
  if (PROVIDER_STRIP_CACHE_CONTROL) {
    stripCacheControl(payload);
  }
  if (PROVIDER_FIX_CACHE_CONTROL) {
    fixCacheControl(payload);
  }

  normalizeProviderTools(payload);

  // Claude/OpenRouter-style endpoints use reasoning.enabled and verbosity.
  // Exact ModelHub crawl endpoints reject these OpenRouter-only fields; keep
  // them governed by PROVIDER_EXTRA_BODY_JSON instead.
  if (OPENROUTER_REASONING_ENABLED && !IS_EXACT_PROVIDER_ENDPOINT) {
    payload.reasoning = { ...(payload.reasoning || {}), enabled: true };
  }
  if (OPENROUTER_VERBOSITY && !IS_EXACT_PROVIDER_ENDPOINT) {
    payload.verbosity = OPENROUTER_VERBOSITY;
  }

  // Some provider endpoints reject non-default sampling parameters instead of
  // ignoring them. Removing them keeps judge calls compatible with exact-model
  // endpoints such as GPT-5.5 and Claude Opus 4.7.
  const stripsSamplingParams = [
    'claude-opus-4.7',
    'gpt-5.5',
  ].some((name) => String(MODEL_NAME).includes(name));
  if (stripsSamplingParams) {
    delete payload.temperature;
    delete payload.top_p;
    delete payload.top_k;
  }

  return Buffer.from(JSON.stringify(payload));
}

function stripCacheControl(value) {
  if (Array.isArray(value)) {
    for (const item of value) stripCacheControl(item);
    return;
  }
  if (!value || typeof value !== 'object') return;
  delete value.cache_control;
  for (const item of Object.values(value)) {
    stripCacheControl(item);
  }
}

function fixCacheControl(value) {
  if (Array.isArray(value)) {
    for (const item of value) fixCacheControl(item);
    return;
  }
  if (!value || typeof value !== 'object') return;
  if (Object.prototype.hasOwnProperty.call(value, 'cache_control')) {
    const current = value.cache_control;
    if (!current || typeof current !== 'object' || Array.isArray(current)) {
      value.cache_control = { type: 'ephemeral' };
    } else if (!current.type) {
      current.type = 'ephemeral';
    }
  }
  for (const item of Object.values(value)) {
    fixCacheControl(item);
  }
}

function providerRetryDelayMs(attempt) {
  const jitter = Math.floor(Math.random() * 500);
  const delay = PROVIDER_RETRY_BASE_MS * Math.pow(2, Math.max(0, attempt - 1)) + jitter;
  return Math.min(delay, PROVIDER_RETRY_MAX_DELAY_MS);
}

function isRetriableProviderFailure(statusCode, rawBody) {
  if ([429, 502, 503, 504, 529].includes(Number(statusCode))) {
    return true;
  }
  const text = String(rawBody || '').toLowerCase();
  return [
    'qpm limit',
    'rate limit',
    'too many requests',
    'gateway',
    'time-out',
    'timeout',
    'time out',
    'temporarily unavailable',
    // Mixed crawl pools route some attempts to broken Bedrock replicas;
    // retrying usually lands on a healthy Vertex replica.
    'not allowed for this account',
  ].some((marker) => text.includes(marker));
}

function reassembleOpenAiStream(rawText) {
  const completion = {
    id: '',
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: MODEL_NAME,
    choices: [],
    usage: null,
  };
  const choiceMap = new Map();
  let sawDone = false;
  let sawChunk = false;
  let sawFinish = false;
  for (const line of String(rawText || '').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) continue;
    const data = trimmed.slice(5).trim();
    if (data === '[DONE]') { sawDone = true; continue; }
    let event;
    try { event = JSON.parse(data); } catch (e) { continue; }
    if (!event || typeof event !== 'object') continue;
    sawChunk = true;
    if (event.id && !completion.id) completion.id = event.id;
    if (event.model) completion.model = event.model;
    if (event.created) completion.created = event.created;
    if (event.usage) completion.usage = event.usage;
    for (const choice of event.choices || []) {
      const index = choice.index != null ? choice.index : 0;
      if (!choiceMap.has(index)) {
        choiceMap.set(index, {
          index,
          role: 'assistant',
          content: '',
          reasoningContent: '',
          finishReason: null,
          toolCalls: new Map(),
        });
      }
      const acc = choiceMap.get(index);
      const delta = choice.delta || choice.message || {};
      if (delta.role) acc.role = delta.role;
      if (typeof delta.content === 'string') acc.content += delta.content;
      if (typeof delta.reasoning_content === 'string') acc.reasoningContent += delta.reasoning_content;
      for (const toolDelta of delta.tool_calls || []) {
        const tcIndex = toolDelta.index != null ? toolDelta.index : acc.toolCalls.size;
        if (!acc.toolCalls.has(tcIndex)) {
          acc.toolCalls.set(tcIndex, { id: '', type: 'function', function: { name: '', arguments: '' } });
        }
        const tc = acc.toolCalls.get(tcIndex);
        if (toolDelta.id) tc.id = toolDelta.id;
        if (toolDelta.type) tc.type = toolDelta.type;
        if (toolDelta.function && toolDelta.function.name) tc.function.name = toolDelta.function.name;
        if (toolDelta.function && typeof toolDelta.function.arguments === 'string') {
          tc.function.arguments += toolDelta.function.arguments;
        }
      }
      if (choice.finish_reason) {
        acc.finishReason = choice.finish_reason;
        sawFinish = true;
      }
    }
  }
  for (const acc of [...choiceMap.values()].sort((a, b) => a.index - b.index)) {
    const message = { role: acc.role || 'assistant', content: acc.content };
    if (acc.reasoningContent) message.reasoning_content = acc.reasoningContent;
    if (acc.toolCalls.size) {
      message.tool_calls = [...acc.toolCalls.entries()].sort((a, b) => a[0] - b[0]).map(([, tc]) => tc);
      if (message.content === '') message.content = null;
    }
    completion.choices.push({
      index: acc.index,
      message,
      finish_reason: acc.finishReason || (message.tool_calls ? 'tool_calls' : 'stop'),
    });
  }
  if (!completion.id) completion.id = `chatcmpl-${Date.now()}`;
  if (!completion.usage) delete completion.usage;
  const complete = sawChunk && completion.choices.length > 0 && (sawDone || sawFinish);
  return { completion, complete, sawChunk };
}

function clientPayloadFromCompletion(completion, clientWantsStream) {
  if (!clientWantsStream) {
    return { contentType: 'application/json', body: JSON.stringify(completion) };
  }
  const headChoices = completion.choices.map((choice) => {
    const delta = { role: choice.message.role };
    if (choice.message.content) delta.content = choice.message.content;
    if (choice.message.reasoning_content) delta.reasoning_content = choice.message.reasoning_content;
    if (choice.message.tool_calls) {
      delta.tool_calls = choice.message.tool_calls.map((tc, i) => ({ index: i, ...tc }));
    }
    return { index: choice.index, delta, finish_reason: null };
  });
  const tailChoices = completion.choices.map((choice) => ({
    index: choice.index,
    delta: {},
    finish_reason: choice.finish_reason,
  }));
  const base = { id: completion.id, object: 'chat.completion.chunk', created: completion.created, model: completion.model };
  const head = { ...base, choices: headChoices };
  const tail = { ...base, choices: tailChoices };
  if (completion.usage) tail.usage = completion.usage;
  return {
    contentType: 'text/event-stream',
    body: `data: ${JSON.stringify(head)}\n\ndata: ${JSON.stringify(tail)}\n\ndata: [DONE]\n\n`,
  };
}

// Commit response headers to the client immediately and keep the socket warm
// while upstream retries run underneath. CCR's outbound HTTP client (undici)
// aborts at headersTimeout=300s if no response headers arrive — that, not the
// gateway, produced the stable ~302s request deaths. SSE clients get legal
// `: keepalive` comment lines; JSON clients get leading whitespace, which is
// valid JSON to every parser.
const PROVIDER_EARLY_KEEPALIVE_MS = Math.max(1000, parseInt(process.env.PROVIDER_EARLY_KEEPALIVE_MS || '15000', 10) || 15000);

function makeProviderResponder(res, clientWantsStream, earlyCommit) {
  const state = { committed: false, finished: false, timer: null, clientGone: false };
  res.on('close', () => {
    state.clientGone = true;
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
  });
  const commit = () => {
    if (state.committed || state.finished || state.clientGone) return;
    state.committed = true;
    if (clientWantsStream) {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      res.write(': keepalive\n\n');
    } else {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked' });
      res.write(' ');
    }
    state.timer = setInterval(() => {
      if (state.finished || state.clientGone) { clearInterval(state.timer); state.timer = null; return; }
      try { res.write(clientWantsStream ? ': keepalive\n\n' : ' '); } catch (e) {}
    }, PROVIDER_EARLY_KEEPALIVE_MS);
  };
  if (earlyCommit) commit();
  const finish = () => {
    state.finished = true;
    if (state.timer) { clearInterval(state.timer); state.timer = null; }
  };
  return {
    isClientGone: () => state.clientGone,
    sendCompletion(completion) {
      if (state.finished || state.clientGone) return;
      finish();
      const payload = clientPayloadFromCompletion(completion, clientWantsStream);
      if (!state.committed) {
        res.writeHead(200, { 'Content-Type': payload.contentType });
        res.end(payload.body);
        return;
      }
      res.end(clientWantsStream ? payload.body : JSON.stringify(completion));
    },
    sendError(statusCode, errorBody) {
      if (state.finished || state.clientGone) return;
      finish();
      const bodyText = typeof errorBody === 'string' ? errorBody : JSON.stringify(errorBody);
      if (!state.committed) {
        res.writeHead(statusCode, { 'Content-Type': 'application/json' });
        res.end(bodyText);
        return;
      }
      if (clientWantsStream) {
        res.end(`data: ${bodyText}\n\ndata: [DONE]\n\n`);
      } else {
        res.end(bodyText);
      }
    },
    sendRaw(statusCode, headers, rawBody) {
      if (state.finished || state.clientGone) return;
      if (!state.committed) {
        finish();
        res.writeHead(statusCode, headers);
        res.end(rawBody);
        return;
      }
      const rawText = Buffer.isBuffer(rawBody) ? rawBody.toString('utf-8') : String(rawBody || '');
      if (statusCode >= 200 && statusCode < 300) {
        try {
          const json = JSON.parse(rawText);
          if (json && Array.isArray(json.choices)) {
            this.sendCompletion(json);
            return;
          }
        } catch (e) {}
      }
      this.sendError(statusCode, rawText || JSON.stringify({ error: { message: `upstream status ${statusCode}` } }));
    },
  };
}

function forwardProviderRequest({ options, transport, shapedBody, res, responder = null, clientWantsStream = false, attempt = 1 }) {
  if (!responder) {
    responder = makeProviderResponder(res, clientWantsStream, false);
  }
  if (responder.isClientGone()) return;
  const scheduleRetry = (reason) => {
    if (responder.isClientGone()) return;
    const delayMs = providerRetryDelayMs(attempt);
    console.error(`[provider_proxy] ${reason}; retrying attempt=${attempt + 1}/${PROVIDER_RETRY_MAX_ATTEMPTS} delay_ms=${delayMs}`);
    setTimeout(() => {
      forwardProviderRequest({ options, transport, shapedBody, res, responder, clientWantsStream, attempt: attempt + 1 });
    }, delayMs);
  };
  const upstreamReq = transport.request(options, (upstreamRes) => {
    const chunks = [];
    let settled = false;
    const failStream = (err) => {
      if (settled) return;
      settled = true;
      if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS) {
        scheduleRetry(`upstream stream failed: ${err.message}`);
        return;
      }
      responder.sendError(502, { error: { message: `Upstream stream failed: ${err.message}` } });
    };
    upstreamRes.on('data', (chunk) => chunks.push(chunk));
    upstreamRes.on('aborted', () => failStream(new Error('upstream connection aborted')));
    upstreamRes.on('error', failStream);
    upstreamRes.on('end', () => {
      if (settled) return;
      settled = true;
      const rawBody = Buffer.concat(chunks);
      const rawText = rawBody.toString('utf-8');
      const statusCode = upstreamRes.statusCode || 502;
      if (statusCode >= 400) {
        console.error(`[provider_proxy] upstream ${statusCode}: ${rawText.slice(0, 1000)}`);
      }
      if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS && isRetriableProviderFailure(statusCode, rawText)) {
        scheduleRetry('retrying upstream request');
        return;
      }
      if (PROVIDER_UPSTREAM_STREAM && statusCode >= 200 && statusCode < 300) {
        const looksSse = String(upstreamRes.headers['content-type'] || '').includes('event-stream')
          || rawText.trimStart().startsWith('data:');
        let result = null;
        if (looksSse) {
          result = reassembleOpenAiStream(rawText);
        } else {
          try {
            const json = JSON.parse(rawText);
            if (json && Array.isArray(json.choices)) {
              result = { completion: json, complete: true, sawChunk: false };
            }
          } catch (e) {}
        }
        if (!result || !result.complete) {
          if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS) {
            scheduleRetry('incomplete upstream stream');
            return;
          }
          responder.sendError(502, { error: { message: 'Upstream stream ended prematurely' } });
          return;
        }
        const firstChoice = result.completion.choices[0] || {};
        console.log(
          `[provider_proxy] ${result.sawChunk ? 'sse_reassembled' : 'json_passthrough'} `
          + `finish=${firstChoice.finish_reason || ''} tool_calls=${(firstChoice.message && firstChoice.message.tool_calls || []).length} `
          + `usage=${result.completion.usage ? 'api' : 'none'}`,
        );
        responder.sendCompletion(result.completion);
        return;
      }
      // Some ModelHub crawl routes answer OpenAI-shaped requests with
      // Anthropic Messages JSON (content blocks). Convert so OpenAI clients
      // (generated harness LLM clients, judges) can parse the response.
      if (statusCode >= 200 && statusCode < 300) {
        try {
          const json = JSON.parse(rawText);
          if (json && !Array.isArray(json.choices) && Array.isArray(json.content)) {
            const text = json.content.filter((b) => b && b.type === 'text').map((b) => b.text || '').join('');
            const toolCalls = json.content
              .filter((b) => b && b.type === 'tool_use')
              .map((b, i) => ({
                id: b.id || `call_${i}`,
                type: 'function',
                function: { name: b.name || '', arguments: JSON.stringify(b.input || {}) },
              }));
            const message = { role: 'assistant', content: toolCalls.length && !text ? null : text };
            if (toolCalls.length) message.tool_calls = toolCalls;
            const completion = {
              id: json.id || `chatcmpl-${Date.now()}`,
              object: 'chat.completion',
              created: Math.floor(Date.now() / 1000),
              model: json.model || MODEL_NAME,
              choices: [{ index: 0, message, finish_reason: json.stop_reason === 'tool_use' ? 'tool_calls' : 'stop' }],
            };
            if (json.usage) {
              completion.usage = {
                prompt_tokens: json.usage.input_tokens || 0,
                completion_tokens: json.usage.output_tokens || 0,
                total_tokens: (json.usage.input_tokens || 0) + (json.usage.output_tokens || 0),
              };
            }
            console.log(`[provider_proxy] anthropic_json_converted finish=${completion.choices[0].finish_reason} usage=${completion.usage ? 'api' : 'none'}`);
            responder.sendCompletion(completion);
            return;
          }
        } catch (e) {}
      }
      responder.sendRaw(statusCode, upstreamRes.headers, rawBody);
    });
  });

  upstreamReq.on('error', (err) => {
    if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS) {
      scheduleRetry(`upstream network error: ${err.message}`);
      return;
    }
    responder.sendError(502, { error: { message: `Upstream proxy error: ${err.message}` } });
  });

  upstreamReq.write(shapedBody);
  upstreamReq.end();
}

function forwardAnthropicPassthrough({ req, res, body, attempt = 1 }) {
  const base = String(UPSTREAM_BASE_URL || '').replace(/\/$/, '');
  const target = new URL(base + (req.url || '/'));
  const headers = { ...req.headers };
  headers.host = target.host;
  headers.authorization = `Bearer ${UPSTREAM_API_KEY}`;
  headers['x-api-key'] = UPSTREAM_API_KEY;
  headers['content-length'] = body.length;
  delete headers.connection;
  delete headers['accept-encoding'];
  const options = {
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port || (target.protocol === 'https:' ? 443 : 80),
    path: target.pathname + target.search,
    method: req.method,
    headers,
  };
  const transport = target.protocol === 'https:' ? require('https') : http;
  const startedAt = Date.now();
  const upstreamReq = transport.request(options, (upstreamRes) => {
    const statusCode = upstreamRes.statusCode || 502;
    if (statusCode >= 400) {
      const chunks = [];
      upstreamRes.on('data', (chunk) => chunks.push(chunk));
      upstreamRes.on('end', () => {
        const rawBody = Buffer.concat(chunks);
        const rawText = rawBody.toString('utf-8');
        console.error(`[anthropic_passthrough] upstream ${statusCode} (${Date.now() - startedAt}ms): ${rawText.slice(0, 300)}`);
        if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS && isRetriableProviderFailure(statusCode, rawText)) {
          const delayMs = providerRetryDelayMs(attempt);
          console.error(`[anthropic_passthrough] retrying attempt=${attempt + 1}/${PROVIDER_RETRY_MAX_ATTEMPTS} delay_ms=${delayMs}`);
          setTimeout(() => forwardAnthropicPassthrough({ req, res, body, attempt: attempt + 1 }), delayMs);
          return;
        }
        res.writeHead(statusCode, upstreamRes.headers);
        res.end(rawBody);
      });
      return;
    }
    console.log(`[anthropic_passthrough] ${req.method} ${(req.url || '').split('?')[0]} status=${statusCode} ttfb_ms=${Date.now() - startedAt} attempt=${attempt}`);
    res.writeHead(statusCode, upstreamRes.headers);
    upstreamRes.pipe(res);
  });
  upstreamReq.on('error', (err) => {
    if (attempt < PROVIDER_RETRY_MAX_ATTEMPTS) {
      const delayMs = providerRetryDelayMs(attempt);
      console.error(`[anthropic_passthrough] network error: ${err.message}; retrying attempt=${attempt + 1}/${PROVIDER_RETRY_MAX_ATTEMPTS} delay_ms=${delayMs}`);
      setTimeout(() => forwardAnthropicPassthrough({ req, res, body, attempt: attempt + 1 }), delayMs);
      return;
    }
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: `Anthropic passthrough error: ${err.message}` } }));
  });
  upstreamReq.write(body);
  upstreamReq.end();
}

const providerProxy = http.createServer((req, res) => {
  if (!UPSTREAM_BASE_URL || !UPSTREAM_API_KEY) {
    res.writeHead(500, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'UPSTREAM_BASE_URL or UPSTREAM_API_KEY is missing' } }));
    return;
  }

  const reqChunks = [];
  req.on('data', (chunk) => reqChunks.push(chunk));
  req.on('end', () => {
    const originalBody = Buffer.concat(reqChunks).toString('utf-8');
    if (PROVIDER_ANTHROPIC_PASSTHROUGH) {
      forwardAnthropicPassthrough({ req, res, body: Buffer.from(originalBody) });
      return;
    }
    if (isAnthropicNativeUrl(UPSTREAM_BASE_URL)) {
      handleAnthropicNativeProvider(req, res, originalBody);
      return;
    }
    let clientWantsStream = false;
    try {
      clientWantsStream = JSON.parse(originalBody || '{}').stream === true;
    } catch (e) {}
    const shapedBody = shapeProviderRequest(originalBody);
    const options = buildUpstreamOptions(UPSTREAM_BASE_URL, req.method, req.headers, shapedBody.length);
    const transport = options.protocol === 'https:' ? require('https') : http;
    const responder = makeProviderResponder(res, clientWantsStream, PROVIDER_UPSTREAM_STREAM);
    forwardProviderRequest({ options, transport, shapedBody, res, responder, clientWantsStream });
  });
});

const server = http.createServer((req, res) => {
  if (req.url === '/v1/models' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(MODELS_RESPONSE);
    return;
  }

  const isChat = req.url?.includes('/messages') || req.url?.includes('/chat/completions');
  const startTime = Date.now();

  if (isChat) {
    // Buffer request body for input token estimation
    const reqChunks = [];
    req.on('data', (chunk) => reqChunks.push(chunk));
    req.on('end', () => {
      const reqBody = Buffer.concat(reqChunks);
      const estimatedInput = extractInputFromRequest(reqBody.toString('utf-8'));

      const options = {
        hostname: '127.0.0.1',
        port: CCR_PORT,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, 'content-length': reqBody.length },
      };

      const proxy = http.request(options, (proxyRes) => {
        const chunks = [];
        const statusCode = proxyRes.statusCode;
        res.writeHead(statusCode, proxyRes.headers);
        proxyRes.on('data', (chunk) => {
          chunks.push(chunk);
          res.write(chunk);
        });
        proxyRes.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf-8');
          const usage = extractUsageFromChunks(body);
          const elapsed = Date.now() - startTime;

          // If API didn't return input tokens, use estimate
          if (usage.input_tokens === 0 && estimatedInput > 0) {
            usage.input_tokens = estimatedInput;
            if (usage.source === 'none') usage.source = 'estimated';
          }

          // Detect retry/failed requests:
          // - HTTP error status (4xx/5xx)
          // - No output tokens AND no API-reported usage (likely API failure)
          const isRetry = statusCode >= 400 ||
            (usage.output_tokens === 0 && usage.source !== 'api');

          metrics.total_requests += 1;
          metrics.total_input_tokens += usage.input_tokens;
          metrics.total_output_tokens += usage.output_tokens;
          metrics.total_cache_read_tokens += usage.cache_read_tokens;
          metrics.total_cache_creation_tokens += usage.cache_creation_tokens;

          if (isRetry) {
            metrics.retry_requests += 1;
          } else {
            metrics.effective_requests += 1;
            metrics.effective_input_tokens += usage.input_tokens;
            metrics.effective_output_tokens += usage.output_tokens;
          }

          if (usage.source === 'api') metrics.usage_source = 'api';
          else if (metrics.usage_source === 'none') metrics.usage_source = 'estimated';

          metrics.requests.push({
            seq: metrics.total_requests,
            timestamp: new Date().toISOString(),
            elapsed_ms: elapsed,
            status_code: statusCode,
            is_retry: isRetry,
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
            cache_read_tokens: usage.cache_read_tokens,
            cache_creation_tokens: usage.cache_creation_tokens,
            source: usage.source,
          });

          const retryTag = isRetry ? ' [RETRY]' : '';
          console.log(`[req #${metrics.total_requests}] ${elapsed}ms | in=${usage.input_tokens} out=${usage.output_tokens} (${usage.source})${retryTag}`);
          res.end();
        });
      });

      proxy.on('error', (err) => {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: `Proxy error: ${err.message}`, type: 'proxy_error' } }));
      });

      proxy.write(reqBody);
      proxy.end();
    });
  } else {
    // Non-chat requests: pass through
    const options = {
      hostname: '127.0.0.1',
      port: CCR_PORT,
      path: req.url,
      method: req.method,
      headers: req.headers,
    };
    const proxy = http.request(options, (proxyRes) => {
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    });
    proxy.on('error', (err) => {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: { message: `Proxy error: ${err.message}`, type: 'proxy_error' } }));
    });
    req.pipe(proxy, { end: true });
  }
});

// Node 18+ defaults server.requestTimeout to 300000ms and destroys the
// inbound socket when a response takes longer — proxies that hold a request
// while retrying or while the upstream model thinks for >5 minutes get cut
// at ~302s and the client sees a 500. The upstream gateway allows 1800s, so
// disable the per-request deadline here (0 = no limit) and keep a sane
// headers timeout.
const SERVER_REQUEST_TIMEOUT_MS = Math.max(0, parseInt(process.env.PROXY_SERVER_REQUEST_TIMEOUT_MS || '0', 10) || 0);
for (const srv of [server, providerProxy]) {
  srv.requestTimeout = SERVER_REQUEST_TIMEOUT_MS;
  srv.headersTimeout = 120000;
  srv.timeout = 0;
}

// The metrics relay (PROXY_PORT) is only used by the Claude Code chain. When
// a second proxy instance runs inside the same container for dev-BMK eval,
// that port may already be taken by the creation-side proxy — that must not
// kill the eval provider proxy, which binds its own dedicated port.
server.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    console.error(`[model_proxy] metrics relay port ${PROXY_PORT} already in use; continuing with provider proxy only`);
    return;
  }
  console.error(`[model_proxy] metrics relay server error: ${err.message}`);
});

providerProxy.on('error', (err) => {
  console.error(`[provider_proxy] fatal server error: ${err.message}`);
  process.exit(1);
});

server.listen(PROXY_PORT, '127.0.0.1', () => {
  console.log(`Model proxy listening on 127.0.0.1:${PROXY_PORT}, forwarding to CCR on ${CCR_PORT} (requestTimeout=${SERVER_REQUEST_TIMEOUT_MS || 'disabled'})`);
});

providerProxy.listen(PROVIDER_PROXY_PORT, PROVIDER_PROXY_HOST, () => {
  const effort = OPENROUTER_VERBOSITY || 'default';
  console.log(`Provider proxy listening on ${PROVIDER_PROXY_HOST}:${PROVIDER_PROXY_PORT}, upstream effort=${effort} (requestTimeout=${SERVER_REQUEST_TIMEOUT_MS || 'disabled'})`);
});
