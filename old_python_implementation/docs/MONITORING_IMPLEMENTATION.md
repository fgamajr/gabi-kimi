# GABI Monitoring Implementation Guide

This guide provides step-by-step instructions for implementing the production monitoring strategy for GABI on Fly.io.

---

## Prerequisites

- [ ] Fly.io CLI installed and authenticated
- [ ] Grafana Cloud account (free tier)
- [ ] PagerDuty or Opsgenie account (for critical alerts)
- [ ] Slack workspace with webhook permissions
- [ ] Access to GABI production deployment

---

## Phase 1: Basic Monitoring Setup (Week 1)

### Step 1.1: Verify Prometheus Metrics

Ensure the `/metrics` endpoint is accessible:

```bash
# Test metrics endpoint
curl https://gabi-api.tcu.gov.br/metrics | head -50

# Verify key metrics are present
curl -s https://gabi-api.tcu.gov.br/metrics | grep "gabi_" | head -20
```

**Expected output:**
```
# HELP gabi_http_requests_total Total de requisições HTTP
# TYPE gabi_http_requests_total counter
gabi_http_requests_total{endpoint="/api/v1/search",method="POST",status="200"} 1234
...
```

### Step 1.2: Set Up Grafana Cloud

1. **Create Grafana Cloud account:**
   - Visit https://grafana.com/products/cloud/
   - Sign up for free tier (10k series, 50GB logs)

2. **Get API credentials:**
   - Go to "Security" > "API Keys"
   - Create key with "MetricsPublisher" role
   - Note down the URL and API key

### Step 1.3: Configure Fly Metrics Integration

Fly.io automatically exposes Prometheus metrics. Configure remote write to Grafana Cloud:

```bash
# Set Grafana Cloud credentials as secrets
fly secrets set --app gabi-api \
  GRAFANA_CLOUD_URL="https://prometheus-prod-01-brazil.grafana.net" \
  GRAFANA_API_KEY="<your-api-key>"
```

### Step 1.4: Import Dashboard

1. **Open Grafana Cloud**
2. **Create new dashboard:**
   - Click "+" > "Import"
   - Upload `grafana-dashboard-main.json`
   - Select your Prometheus data source
   - Click "Import"

### Step 1.5: Set Up UptimeRobot (External Monitoring)

1. **Create UptimeRobot account:**
   - https://uptimerobot.com (free tier: 50 monitors)

2. **Add monitors:**
   ```
   Monitor Type: HTTP(s)
   URL: https://gabi-api.tcu.gov.br/health
   Monitoring Interval: 5 minutes
   Alert Contacts: Email + Slack webhook
   ```

3. **Add keyword checks:**
   ```
   Keyword: "healthy"
   ```

---

## Phase 2: Log Aggregation (Week 2)

### Step 2.1: Create Log Shipper App

```bash
# Create dedicated log shipper app
fly apps create gabi-logs --machines-only

# Set secrets
fly secrets set --app gabi-logs \
  GRAFANA_CLOUD_URL="https://logs-prod-012.grafana.net" \
  GRAFANA_API_KEY="<loki-api-key>" \
  GRAFANA_LOKI_USER="<loki-user-id>" \
  FLY_API_TOKEN="<your-fly-api-token>"
```

### Step 2.2: Deploy Log Shipper

Create `fly.logs.toml`:

```toml
app = 'gabi-logs'
primary_region = 'gru'

[build]
  image = 'timberio/vector:0.35.0-debian'

[env]
  GRAFANA_CLOUD_URL = 'https://logs-prod-012.grafana.net'

[[services]]
  internal_port = 8686
  protocol = "tcp"
  auto_stop_machines = false
  auto_start_machines = false

[metrics]
  port = 8686
  path = "/metrics"
```

Create `vector.toml` (see MONITORING_STRATEGY.md for full configuration):

```bash
# Deploy log shipper
fly deploy --config fly.logs.toml
```

### Step 2.3: Verify Log Shipping

```bash
# Check Vector logs
fly logs --app gabi-logs

# In Grafana: Go to Explore > Select Loki data source
# Query: {app="gabi-api"}
```

---

## Phase 3: Alerting (Week 3)

### Step 3.1: Configure PagerDuty Integration

1. **Create Service in PagerDuty:**
   - Services > Service Directory > New Service
   - Name: "GABI Production"
   - Integration Type: "Events API v2"

2. **Get Integration Key:**
   - Copy the "Integration Key"

3. **Configure in Grafana:**
   - Alerting > Contact Points > New
   - Type: PagerDuty
   - Integration Key: Your key

### Step 3.2: Configure Slack Integration

1. **Create Slack Webhook:**
   - Slack Apps > Create New App
   - Incoming Webhooks > Add New Webhook
   - Select channel: #gabi-alerts

2. **Add to Grafana:**
   - Alerting > Contact Points > New
   - Type: Slack
   - URL: Your webhook URL
   - Title: "GABI Alert"

### Step 3.3: Import Alert Rules

1. **Open Grafana:**
   - Alerting > Alert Rules

2. **Import from YAML:**
   - Click "New Alert Rule"
   - Use the queries from `alert-rules.yaml`
   - Or use Grafana Alerting API:

```bash
# Import via API
curl -X POST \
  https://your-grafana-instance/api/v1/provisioning/alert-rules \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @alert-rules.json
```

### Step 3.4: Configure Notification Routing

Create notification policies in Grafana:

```yaml
# Routing rules
- Critical alerts -> PagerDuty + SMS
- Warning alerts -> Slack
- Info alerts -> Slack (business hours only)
```

### Step 3.5: Test Alert Routing

```bash
# Trigger test alert via API
curl -X POST \
  https://your-grafana-instance/api/v1/alerts \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "labels": {"alertname": "TestAlert", "severity": "critical"},
    "annotations": {"summary": "Test alert"}
  }'
```

---

## Phase 4: Advanced Monitoring (Week 4)

### Step 4.1: Set Up SLO Dashboards

1. **Create SLO tracking dashboard:**
   - Import SLO panels from `grafana-dashboard-slo.json`
   - Configure error budget alerts

2. **Configure SLO alerts:**
   ```yaml
   # Availability SLO: 99.9%
   - alert: GABIAvailabilitySLOBreach
     expr: avg_over_time(up{job="gabi-api"}[30d]) < 0.999
   
   # Latency SLO: p95 < 500ms
   - alert: GABILatencySLOBreach
     expr: histogram_quantile(0.95, ...) > 0.5
   ```

### Step 4.2: Implement Distributed Tracing (Optional)

If needed for complex debugging:

```bash
# Add tracing to dependencies
pip install opentelemetry-distro opentelemetry-instrumentation-fastapi

# Configure in app
export OTEL_EXPORTER_OTLP_ENDPOINT=https://tempo.grafana.net
export OTEL_SERVICE_NAME=gabi-api
```

### Step 4.3: Set Up Cost Monitoring

1. **Fly.io billing alerts:**
   - Organization Settings > Billing > Alerts
   - Set alert at $50, $100 thresholds

2. **Grafana cost dashboard:**
   - Track resource usage
   - Estimate monthly costs

---

## Maintenance Tasks

### Daily

- [ ] Check Grafana dashboard for anomalies
- [ ] Review alert history
- [ ] Monitor DLQ size

### Weekly

- [ ] Review error rates and latencies
- [ ] Check disk space usage
- [ ] Verify backup completion

### Monthly

- [ ] Review SLO compliance
- [ ] Update alert thresholds if needed
- [ ] Review and update runbooks
- [ ] Cost optimization review

---

## Troubleshooting

### Metrics Not Appearing

```bash
# Check if metrics endpoint is accessible
curl -I https://gabi-api.tcu.gov.br/metrics

# Check Fly Metrics
fly metrics --app gabi-api

# Verify prometheus-client is working
fly ssh console --app gabi-api
python -c "from gabi.metrics import HTTP_REQUESTS_TOTAL; print(HTTP_REQUESTS_TOTAL)"
```

### Logs Not Shipping

```bash
# Check Vector status
fly status --app gabi-logs

# Check Vector logs
fly logs --app gabi-logs

# Test NATS connection
fly ssh console --app gabi-logs
vector validate /etc/vector/vector.toml
```

### Alerts Not Firing

```bash
# Check alert rules in Grafana
# Alerting > Alert Rules

# Test alert manually
# Alerting > Alert Rules > Test

# Check notification logs
# Alerting > Notification Error Log
```

---

## Security Considerations

1. **API Keys:**
   - Store in Fly secrets, not in code
   - Rotate quarterly
   - Use least-privilege permissions

2. **Dashboard Access:**
   - Use Grafana Cloud authentication
   - Enable 2FA for all users
   - Limit admin access

3. **Logs:**
   - Redact PII in logs
   - Set retention policies
   - Audit log access

---

## Support and Resources

- **Fly.io Support:** https://fly.io/docs/
- **Grafana Cloud Docs:** https://grafana.com/docs/
- **GABI Wiki:** https://wiki.tcu.gov.br/gabi
- **On-Call Escalation:** See incident response plan

---

## Checklist Summary

- [ ] Prometheus metrics verified
- [ ] Grafana Cloud account created
- [ ] Main dashboard imported
- [ ] UptimeRobot configured
- [ ] Log shipper deployed
- [ ] Logs visible in Grafana
- [ ] PagerDuty integration
- [ ] Slack webhook configured
- [ ] Alert rules imported
- [ ] Notification routing tested
- [ ] Runbooks reviewed
- [ ] Team training completed
