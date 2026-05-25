# Plynth demo recording — generates docs/assets/demo.gif
#
# Prereqs (one-time):
#   1. Plynth running locally:
#        make up && make migrate && make seed
#   2. Platform admin token exported (read from your .env):
#        export TOKEN=$(grep '^PLATFORM_ADMIN_TOKEN=' .env | cut -d= -f2)
#   3. VHS installed:
#        brew install vhs
#
# Record:
#   vhs vhs/demo.tape
#
# Output:
#   docs/assets/demo.gif (~1 MB, ~35 seconds)
#
# Tweak `Sleep` lines to slow down or speed up the pacing.

Output docs/assets/demo.gif

Set Theme "Catppuccin Mocha"
Set FontSize 16
Set Width 1200
Set Height 720
Set Padding 24
Set TypingSpeed 35ms
Set Framerate 24
Set PlaybackSpeed 1.0

# ─── Title card ──────────────────────────────────────────────────
Hide
Type "clear"
Enter
Sleep 200ms
Show

Type "# 🏛  Plynth — multi-product SaaS backend, one deployment"
Sleep 800ms
Enter
Enter
Sleep 1s

# ─── 1. Health check ────────────────────────────────────────────
Type "# 1. API is up"
Enter
Sleep 600ms
Type "curl -s http://localhost:8000/health"
Sleep 400ms
Enter
Sleep 1500ms
Enter

# ─── 2. Bootstrap a product ─────────────────────────────────────
Type "# 2. Bootstrap a SaaS product (admin token only)"
Enter
Sleep 600ms
Type `curl -s -X POST http://localhost:8000/api/v1/admin/products \`
Enter
Type `  -H "X-Platform-Admin-Token: $TOKEN" \`
Enter
Type `  -H "Content-Type: application/json" \`
Enter
Type `  -d '{"name":"ChatBot","slug":"chatbot","tenant_type":"company"}' | jq`
Sleep 400ms
Enter
Sleep 2500ms
Enter

# ─── 3. Atomic tenant + owner + trial ────────────────────────────
Type "# 3. Create a tenant + owner user + trial subscription — one call"
Enter
Sleep 700ms
Type `curl -s -X POST http://localhost:8000/api/v1/tenants \`
Enter
Type `  -H "X-Platform-Admin-Token: $TOKEN" \`
Enter
Type `  -H "X-Product-Slug: chatbot" \`
Enter
Type `  -H "Content-Type: application/json" \`
Enter
Type `  -d '{"name":"Acme","slug":"acme",`
Type `       "owner":{"email":"alice@acme.example.com","password":"S3cretPassword!"},`
Type `       "plan_code":"pro"}' | jq '{slug,is_root,parent_id}'`
Sleep 400ms
Enter
Sleep 2500ms
Enter

# ─── 4. Owner can log in immediately ─────────────────────────────
Type "# 4. The new owner can sign in — JWT pair issued"
Enter
Sleep 600ms
Type `curl -s -X POST http://localhost:8000/api/v1/auth/login \`
Enter
Type `  -H "X-Product-Slug: chatbot" \`
Enter
Type `  -H "Content-Type: application/json" \`
Enter
Type `  -d '{"email":"alice@acme.example.com","password":"S3cretPassword!"}' \`
Enter
Type `  | jq '{access_token: (.access_token[0:30]+"…"), expires_at}'`
Sleep 400ms
Enter
Sleep 2500ms
Enter

# ─── 5. Recap ────────────────────────────────────────────────────
Type "# That's a fully wired SaaS:"
Enter
Type "#   product · tenant · owner user · RBAC roles · trial subscription · audit row"
Enter
Type "#"
Enter
Type "# Add a second product (Notes / CRM / yours) — one admin call. No new deploy."
Enter
Sleep 3s
