---
phase: 07-upload-ui
plan: "01"
subsystem: frontend
tags: react, upload, admin, xml, zip, xhr, progress

requires:
  - phase: 03-upload-api
    provides: POST /api/admin/upload, 202 + job_id
  - phase: 05-single-xml-processing
    provides: Admin auth (require_admin_access)
provides:
  - Admin upload page at /admin/upload (drag-drop, file picker, .xml/.zip up to 200MB)
  - Upload progress via XHR and Progress component (UPLD-06)
  - XML preview before upload: article count, date range, sections (UPLD-07)
  - Paste tab: raw XML submitted as pasted.xml file (UPLD-08)
affects: Phase 8 Job Dashboard (admin can then view job status)

tech-stack:
  added: uploadApi (XHR with progress), xmlPreview (DOMParser)
  patterns: ProtectedRoute admin for /admin/upload; FormData file upload with credentials

key-files:
  created: src/frontend/web/src/lib/uploadApi.ts, src/frontend/web/src/lib/xmlPreview.ts, src/frontend/web/src/pages/AdminUploadPage.tsx
  modified: src/frontend/web/src/App.tsx, src/frontend/web/src/components/layout/AppShell.tsx

key-decisions:
  - "Upload progress: XHR instead of fetch so xhr.upload.onprogress can report percentage"
  - "Paste tab: create Blob from text and send as File in FormData (same endpoint as file upload)"
  - "XML preview: best-effort client-side DOMParser; backend remains authoritative"

patterns-established:
  - "Admin upload: drag-drop + file input, validate type/size, optional XML preview, then upload with progress"

requirements-completed: [UPLD-01, UPLD-02, UPLD-06, UPLD-07, UPLD-08]

duration: 25
completed: "2026-03-08"
---

# Phase 7 Plan 01: Upload UI Summary

**Admin upload page with drag-drop/file picker, progress indicator, XML preview (count, dates, sections), and paste tab for raw XML (UPLD-01–08).**

## Performance

- **Duration:** ~25 min
- **Tasks:** 1 (full upload UI)
- **Files modified/created:** 5

## Accomplishments

- **uploadApi.ts:** `uploadAdminFile(file, onProgress)` using XMLHttpRequest, FormData, withCredentials; resolves URL via resolveApiUrl; returns `{ job_id, status }`.
- **xmlPreview.ts:** `parseXmlPreview(xmlString)` returns article count, dateMin/dateMax, sections; best-effort DOMParser and tag/attribute heuristics for DOU-like XML.
- **AdminUploadPage:** Tabs "Arquivo" and "Colar XML". File tab: dropzone (onDrop/onDragOver), hidden file input accept .xml/.zip, max 200MB; on XML file selected, preview shown; Progress bar during upload; Enviar calls uploadAdminFile. Paste tab: Textarea, Enviar creates Blob/File and uploads as pasted.xml.
- **Route:** /admin/upload with ProtectedRoute requiredRole="admin"; nav "Upload DOU" and rail "Upload" for admins.

## Task Commits

1. **Upload UI (uploadApi, xmlPreview, page, route, nav)** - `f31e57d` (feat)

## Files Created/Modified

- `src/frontend/web/src/lib/uploadApi.ts` - XHR upload with progress
- `src/frontend/web/src/lib/xmlPreview.ts` - client-side XML preview
- `src/frontend/web/src/pages/AdminUploadPage.tsx` - upload page with tabs
- `src/frontend/web/src/App.tsx` - route /admin/upload
- `src/frontend/web/src/components/layout/AppShell.tsx` - Upload DOU in menu and nav

## Decisions Made

- Use FileCode and ClipboardPaste from lucide-react (FileXml/Paste not available in this version).
- Progress reported as 0–100% from xhr.upload.onprogress when lengthComputable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Lucide icon names**
- **Found during:** Task 1 (build)
- **Issue:** `Paste` and `FileXml` are not exported by lucide-react (v0.462.0).
- **Fix:** Replaced with `ClipboardPaste` and `FileCode`.
- **Files modified:** src/frontend/web/src/pages/AdminUploadPage.tsx
- **Commit:** f31e57d

**Total deviations:** 1 auto-fixed (blocking). Impact: build succeeds with equivalent icons.

## Issues Encountered

None beyond icon name fix.

## Self-Check: PASSED

- uploadApi.ts, xmlPreview.ts, AdminUploadPage.tsx exist. Route /admin/upload and nav entries present. Commit f31e57d verified.

---
*Phase: 07-upload-ui*
*Completed: 2026-03-08*
