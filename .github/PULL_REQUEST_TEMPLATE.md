# PR Title
<!-- Usa Conventional Commits, p.ej.:
chore(ci): add GitHub Actions and PR template
feat(api): enforce X-Tenant header
fix(web): correct backticks in App.tsx
-->

## Summary
Breve descripción de qué cambia y por qué.

## Checklist
- [ ] Leí `AGENTS.md`
- [ ] Título en formato Conventional Commit
- [ ] Linter y type-check pasan en CI
- [ ] Tests agregados/actualizados (si aplica)
- [ ] Manejo de estados de UI (loading/empty/error) (si aplica)
- [ ] Autenticación y Tenancy validados (headers `Authorization` y `X-Tenant`) (si aplica)
- [ ] Documentación/OpenAPI tocada si cambió el contrato (API)

## Changes
- Punto 1
- Punto 2

## Testing notes
Pasos rápidos para validar:
- [ ] curl / script / screenshots
- [ ] Smoke test local

### API (si aplica)
- [ ] `GET /api/health` ✅
- [ ] `POST /api/auth/jwt/create` ✅ (recibo access/refresh)
- [ ] Headers: `Authorization: Bearer <token>`, `X-Tenant: <code>` en endpoints protegidos

### Web (si aplica)
- [ ] Compila (`pnpm build`) ✅
- [ ] Type-check (`pnpm tsc --noEmit`) ✅
- [ ] ESLint (`pnpm eslint .`) ✅
- [ ] Comportamiento en navegador (flujo mínimo OK)

## Security
- [ ] Validaciones de entrada (evitar inyección en FTS / SQL)
- [ ] Subidas (presign + PUT) revisadas
- [ ] Datos de otro tenant no se filtran (scopes por tenant)

## Screenshots / Evidence
Adjunta imágenes, logs o capturas de Swagger si ayudan al revisor.

## Breaking changes
¿Hay cambios incompatibles? Explicar mitigación/migración.

## Related
Issues / tickets / PRs relacionados.
