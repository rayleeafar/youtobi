import CryptoJS from 'crypto-js';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

function cookieDecrypt(uuid, encrypted, password, cryptoType = 'legacy') {
  if (cryptoType === 'aes-128-cbc-fixed') {
    const hash = CryptoJS.MD5(uuid + '-' + password).toString();
    const key = hash.substring(0, 16);
    const fixedIv = CryptoJS.enc.Hex.parse('00000000000000000000000000000000');
    const options = {
      iv: fixedIv,
      mode: CryptoJS.mode.CBC,
      padding: CryptoJS.pad.Pkcs7,
    };
    const decrypted = CryptoJS.AES.decrypt(
      encrypted,
      CryptoJS.enc.Utf8.parse(key),
      options
    ).toString(CryptoJS.enc.Utf8);
    return JSON.parse(decrypted);
  } else {
    const key = CryptoJS.MD5(uuid + '-' + password).toString().substring(0, 16);
    const decrypted = CryptoJS.AES.decrypt(encrypted, key).toString(CryptoJS.enc.Utf8);
    return JSON.parse(decrypted);
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname.replace(/\/+$/, '') || '/';

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // Root / Status endpoint
      if (pathname === '/' || pathname === '/health') {
        return new Response(
          JSON.stringify({ status: 'OK', message: 'CookieCloud Cloudflare Worker active', timestamp: new Date().toISOString() }),
          { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        );
      }

      // POST /update - Extension uploads encrypted cookies
      if (pathname === '/update' && request.method === 'POST') {
        let body = {};
        const contentType = request.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          body = await request.json();
        } else if (contentType.includes('form')) {
          const formData = await request.formData();
          body = Object.fromEntries(formData.entries());
        }

        const { uuid, encrypted, crypto_type = 'legacy' } = body;
        if (!uuid || !encrypted) {
          return new Response('Bad Request: Missing uuid or encrypted data', { status: 400, headers: corsHeaders });
        }

        const record = JSON.stringify({
          encrypted: encrypted,
          crypto_type: crypto_type,
          updated_at: new Date().toISOString()
        });

        // Save into Cloudflare KV
        if (env.COOKIE_STORE) {
          await env.COOKIE_STORE.put(uuid, record);
        }

        return new Response(JSON.stringify({ action: 'done' }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      // GET or POST /get/:uuid - Retrieve encrypted or decrypted cookie store
      if (pathname.startsWith('/get/')) {
        const uuid = pathname.replace('/get/', '').trim();
        if (!uuid) {
          return new Response('Bad Request', { status: 400, headers: corsHeaders });
        }

        let rawData = null;
        if (env.COOKIE_STORE) {
          rawData = await env.COOKIE_STORE.get(uuid);
        }

        if (!rawData) {
          return new Response('Not Found', { status: 404, headers: corsHeaders });
        }

        const data = JSON.parse(rawData);

        // Check if password provided for auto-decryption
        let password = url.searchParams.get('password');
        if (!password && request.method === 'POST') {
          try {
            const body = await request.json();
            password = body.password;
          } catch (e) {}
        }

        if (password) {
          const cryptoType = url.searchParams.get('crypto_type') || data.crypto_type || 'legacy';
          const decrypted = cookieDecrypt(uuid, data.encrypted, password, cryptoType);
          return new Response(JSON.stringify(decrypted), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });
        }

        return new Response(JSON.stringify(data), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      return new Response('Not Found', { status: 404, headers: corsHeaders });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }
};
