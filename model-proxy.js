const http = require('http');

const CCR_PORT = 3456;
const PROXY_PORT = 3457;
const MODEL_NAME = process.env.MODEL_NAME || 'claude-sonnet-4-6';

const MODELS_RESPONSE = JSON.stringify({
  data: [
    { id: 'claude-sonnet-4-6', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: 'claude-opus-4-7', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: 'claude-haiku-4-5-20251001', object: 'model', created: 1700000000, owned_by: 'anthropic' },
    { id: MODEL_NAME, object: 'model', created: 1700000000, owned_by: 'anthropic' },
  ],
  object: 'list',
});

const server = http.createServer((req, res) => {
  if (req.url === '/v1/models' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(MODELS_RESPONSE);
    return;
  }

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
});

server.listen(PROXY_PORT, '127.0.0.1', () => {
  console.log(`Model proxy listening on 127.0.0.1:${PROXY_PORT}, forwarding to CCR on ${CCR_PORT}`);
});
