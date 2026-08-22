# Sprint 3 Known Issues

- The SQL Server full-text catalogue uses English language configuration;
  Spanish/neutral tuning remains a later search milestone.
- SLA compliance is intentionally absent. There is no durable SLA timer,
  request-policy link, first-response timestamp, or resolution timestamp.
- Tenant `default_timezone` and `default_page_size` are exposed configuration
  values but do not mutate Django process-global behavior.
- Feature flags are configuration-only in Sprint 3 and do not disable existing
  product endpoints.
- Domain users become login-capable only through the separate Django/OIDC
  identity provisioning path using a verified matching email.
- Workflow, feature-flag, notification-template, and request-detail
  subcollections remain bounded arrays for web compatibility rather than using
  the standard pagination envelope.
- Sprint 2 request/comment/upload permissions are not retrofitted during Day 9;
  existing JWT and tenant enforcement remains unchanged.
