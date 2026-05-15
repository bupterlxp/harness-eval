const http = require('http');
const fs = require('fs');
const path = require('path');

const CCR_PORT = 3456;
const PROXY_PORT = 3457;
const MODEL_NAME = process.env.MODEL_NAME || 'claude-sonnet-4-6';
const METRICS_PATH = path.join(process.env.WORKSPACE || '/workspace', 'metrics.json');

// Rough estimate: 1 token ≈ 4 chars for English, ≈ 2 chars for Chinese
const CHARS_PER_TOKEN = 3.5;

const metrics = {
  total_requests: 0,
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_cache_read_tokens: 0,
  total_cache_creation_tokens: 0,
  usage_source: 'none', // 'api' if real usage found, 'estimated' if fallback
  requests: [],
};

function saveMetrics() {
  try {
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
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
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

          metrics.total_requests += 1;
          metrics.total_input_tokens += usage.input_tokens;
          metrics.total_output_tokens += usage.output_tokens;
          metrics.total_cache_read_tokens += usage.cache_read_tokens;
          metrics.total_cache_creation_tokens += usage.cache_creation_tokens;
          if (usage.source === 'api') metrics.usage_source = 'api';
          else if (metrics.usage_source === 'none') metrics.usage_source = 'estimated';

          metrics.requests.push({
            seq: metrics.total_requests,
            timestamp: new Date().toISOString(),
            elapsed_ms: elapsed,
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
            cache_read_tokens: usage.cache_read_tokens,
            cache_creation_tokens: usage.cache_creation_tokens,
            source: usage.source,
          });

          console.log(`[req #${metrics.total_requests}] ${elapsed}ms | in=${usage.input_tokens} out=${usage.output_tokens} (${usage.source})`);
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

server.listen(PROXY_PORT, '127.0.0.1', () => {
  console.log(`Model proxy listening on 127.0.0.1:${PROXY_PORT}, forwarding to CCR on ${CCR_PORT}`);
});
