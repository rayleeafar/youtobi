# CookieCloud Server for Cloudflare Workers & Cloudflare Pages

This project allows deploying a 100% serverless, zero-maintenance, zero-cost **CookieCloud** API server on Cloudflare Workers / Cloudflare Pages Functions backed by Cloudflare KV storage.

## Features
- **Serverless**: Zero server maintenance or VPS costs.
- **Fast & Global**: Powered by Cloudflare Edge Network.
- **Full Compatibility**: Works seamlessly with the official CookieCloud Chrome/Edge Browser Extension and `youtobi`.

---

## Deploy to Cloudflare Workers in 3 Steps

### Step 1: Install Dependencies
```bash
npm install
```

### Step 2: Create Cloudflare KV Namespace
Run the following command to create a KV storage bucket:
```bash
npx wrangler kv:namespace create COOKIE_STORE
```
Copy the generated `id` from the terminal output and paste it into your `wrangler.toml`:
```toml
[[kv_namespaces]]
binding = "COOKIE_STORE"
id = "your-kv-namespace-id-here"
```

### Step 3: Deploy to Cloudflare
```bash
npx wrangler deploy
```

Once deployed, Cloudflare will provide your worker URL (e.g. `https://cookiecloud-cloudflare.<your-subdomain>.workers.dev`).

---

## Deploy to Cloudflare Pages Functions

If you prefer Cloudflare Pages:
1. Connect your Git repository or deploy static functions directory:
   ```bash
   npx wrangler pages deploy src --project-name cookiecloud-app
   ```
2. In your Cloudflare Dashboard under **Pages** > **Settings** > **Functions** > **KV namespace bindings**, add a binding named `COOKIE_STORE` pointing to your created KV namespace.

---

## How to Configure Browser Extension & `youtobi`

1. **Extension Server Address**: Set to `https://cookiecloud-cloudflare.<your-subdomain>.workers.dev`
2. **UUID & Password**: Choose a strong secret UUID and Password.
3. **youtobi Dashboard**: In `youtobi` settings (⚙️), paste the same server URL, UUID, and Password to sync cookies automatically.
