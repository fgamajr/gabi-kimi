# INLabs Historical Data Availability Map

**Generated:** 2026-03-02  
**Tested Dates:** Past 60 days (2026-01-01 to 2026-03-02)  
**Credentials Used:** fgamajr@gmail.com

---

## Executive Summary

INLabs (https://inlabs.in.gov.br) is a **login-required** file browser interface for accessing DOU (Diário Oficial da União) PDF archives. 

**Key Finding:** ALL historical data requires authentication - there is NO unauthenticated access window.

---

## 1. Access Requirements

### Authentication
- **Status:** REQUIRED for ALL dates
- **Login URL:** https://inlabs.in.gov.br/logar.php
- **Session:** Cookie-based PHP session
- **Auth Endpoint Stability:** Intermittent 502 Bad Gateway errors under load

### Unauthenticated Access
| Date Range | Result |
|------------|--------|
| Today (-0 days) | Requires login |
| Past 30 days | Requires login |
| Past 60 days | Requires login |
| Past 90 days | Requires login |
| Past 365 days | Requires login |
| Past 730 days | Requires login |

**Conclusion:** No public/unauthenticated access exists.

---

## 2. Availability Window (With Authentication)

### Tested Range: Past 60 Days (2026-01-01 to 2026-03-02)

| Metric | Value |
|--------|-------|
| Total Dates Tested | 61 |
| Available | 61 (100%) |
| Empty | 0 |
| Forbidden | 0 |
| Errors | 0 |

### Pattern Analysis

| Pattern | Count |
|---------|-------|
| Weekday Available | 43 |
| Weekend Available | 18 |
| Month Start Available (days 1-5) | 7 |
| Month End Available | 2 |

**Findings:**
- ✅ **No gaps detected** - all 61 consecutive days have data
- ✅ **Weekend publications exist** - DOU publishes on weekends
- ✅ **100% availability** within tested window

---

## 3. Interface Structure

### URL Pattern
```
Base: https://inlabs.in.gov.br/index.php?p={YYYY-MM-DD}

Examples:
- https://inlabs.in.gov.br/index.php?p=2026-03-02
- https://inlabs.in.gov.br/index.php?p=2026-01-15
- https://inlabs.in.gov.br/index.php?p=2025-12-01
```

### Response Structure
INLabs returns a **file browser interface** (not an article listing):

```html
<table class="table table-bordered table-hover table-sm bg-white" id="main-table">
  <tr>
    <td>
      <a href="?p=2026-01-02&dl=2026_01_02_ASSINADO_do3.pdf">
        <i class="fa fa-cloud-download"></i> 2026_01_02_ASSINADO_do3.pdf
      </a>
    </td>
    <td>30.67 MB</td>
    <td>02-01-2026 23:59</td>
  </tr>
</table>
```

### Download Link Pattern
```
Format: ?p={DATE}&dl={FILENAME}.pdf

Filename Pattern: {YYYY}_{MM}_{DD}_ASSINADO_do{N}.pdf
                  {YYYY}_{MM}_{DD}_ASSINADO_do{N}_extra_{X}.pdf

Examples:
- 2026_01_02_ASSINADO_do3.pdf
- 2026_01_02_ASSINADO_do2.pdf
- 2026_01_07_ASSINADO_do3_extra_A.pdf
- 2026_01_08_ASSINADO_do3_extra_A.pdf
```

### Edition Structure
Each date may contain multiple PDFs representing different DOU sections:

| Edition | Typical Size | Description |
|---------|-------------|-------------|
| do1.pdf | 10-30 MB | Seção 1 |
| do2.pdf | 5-15 MB | Seção 2 |
| do3.pdf | 30-60 MB | Seção 3 (largest) |
| do3_extra_A.pdf | 1-45 MB | Extra editions |

---

## 4. Technical Details

### Content Encoding
- **Format:** gzip compressed
- **Magic Bytes:** `\x1f\x8b` (gzip header)
- Must decompress before parsing HTML

### Session Management
- Cookie-based PHP session
- Session persists across requests
- Re-authentication needed periodically

### Response Times
- Average: ~800ms
- Range: 400ms - 1100ms
- Weekends slightly slower (~850ms vs ~450ms)

---

## 5. Gaps and Inconsistencies

### Identified Issues

| Issue | Severity | Description |
|-------|----------|-------------|
| No unauthenticated access | HIGH | All dates require login |
| Auth endpoint flakiness | MEDIUM | 502 errors under load |
| Inconsistent document counts | LOW | Some dates have 0 PDFs in listing |

### Document Count Variations

| Date | Document Count | Notes |
|------|---------------|-------|
| 2026-01-02 | 3 | Normal (do1, do2, do3) |
| 2026-01-07 | 6 | High (extra editions) |
| 2026-01-08 | 5 | Normal + 1 extra |
| 2026-01-09 | 6 | High (extra editions) |

---

## 6. "5 Business Days" Policy Analysis

The INLabs help page states data is "available until the 5th business day of the following month."

### Observations
- **With authentication:** All 60 days are available (contradicting the policy)
- **Without authentication:** Nothing is available

### Hypothesis
The "5 business days" policy may refer to:
1. **Free/unauthenticated access window** (not implemented or removed)
2. **Public data retention** vs **subscribed user retention**
3. **An outdated policy** no longer enforced

---

## 7. Recommendations

### For Data Collection
1. **Always authenticate** - No unauthenticated access exists
2. **Reuse sessions** - Avoid repeated login attempts (causes 502s)
3. **Handle gzip** - Responses are compressed
4. **Expect multiple PDFs** - Download all editions per date
5. **Check file sizes** - Verify downloads (sizes range 1-60 MB)

### For Archive Strategy
- INLabs appears to maintain **complete archives** for authenticated users
- No evidence of rolling 30-day deletion
- Historical data appears **permanently available** to subscribers

---

## 8. Test Artifacts

| File | Description |
|------|-------------|
| `inlabs_probe_results.json` | 61-day detailed probe results |
| `inlabs_unauth_probe.json` | Unauthenticated access test (all failed) |

---

## Appendix: Raw Data Samples

### Sample Download Links (from 2026-01-02)
```
https://inlabs.in.gov.br/?p=2026-01-02&dl=2026_01_02_ASSINADO_do3.pdf      (30.67 MB)
https://inlabs.in.gov.br/?p=2026-01-02&dl=2026_01_02_ASSINADO_do2.pdf      (8.14 MB)
https://inlabs.in.gov.br/?p=2026-01-02&dl=2026_01_02_ASSINADO_do1.pdf      (size varies)
```

### Authentication Response
```html
<p style="text-align: right;">Olá fgamajr@gmail.com .<br>
<a href="minha-conta.php">Minha Conta</a><br>
<a href="ajuda.php">Ajuda</a><br>
<a href="logout.php">Sair</a></p>
```

---

*Report generated by INLabs Prober v1.0*
