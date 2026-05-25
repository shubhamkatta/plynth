# API reference

The full OpenAPI 3.1 schema for the Plynth platform, served interactively below. The same spec is committed in machine-readable form at [`docs/openapi.json`](openapi.json) — import it into Postman, Insomnia, Bruno, or any OpenAPI-aware tool.

<!-- Swagger UI loaded from CDN -->
<link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.addEventListener('DOMContentLoaded', () => {
  window.ui = SwaggerUIBundle({
    url: 'openapi.json',
    dom_id: '#swagger-ui',
    deepLinking: true,
    persistAuthorization: true,
    layout: 'BaseLayout',
    docExpansion: 'list',
  });
});
</script>

## Versioning & deprecation

See [Architecture § 10 — API versioning + deprecation policy](architecture.md#10-api-versioning--deprecation-policy).
