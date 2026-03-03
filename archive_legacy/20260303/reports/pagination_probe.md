# DOU Pagination Probe

Objective: verify whether embedded `script#params` `jsonArray` represents full issue content or only first page.

Probe method:
- Fetch `https://www.in.gov.br/leiturajornal?data=<DD-MM-YYYY>&secao=do3` via static HTTP.
- Parse `script#params` JSON and count `jsonArray` items.
- Parse UI pagination metadata from page scripts (`request.totalPages`, `request.currentPage`) and inspect presence of pagination controls (`rightArrow`, `leftArrow`, numbered buttons).

## Results

| date | section | jsonArray_count | reported_total_results | pages_estimated | coverage_ratio | more_pages_exist |
|---|---|---:|---:|---:|---:|---|
| 30-01-2026 | do3 | 2855 | 2855 (inferred; no explicit total label) | 1 | 1.000 | no |
| 02-02-2026 | do3 | 2854 | 2854 (inferred; no explicit total label) | 1 | 1.000 | no |
| 26-02-2026 | do3 | 2806 | 2806 (inferred; no explicit total label) | 1 | 1.000 | no |

## Raw signals observed on all three dates

- `script#params` present with large `jsonArray` payload (`~2800` items).
- `request.totalPages = 0` in inline JS.
- `request.currentPage = 1`.
- No pagination controls in DOM (`id="leftArrow"`, `id="rightArrow"`, numbered page buttons absent).
- No `"X resultados"` total-results label for this issue-reading view.

## Conclusion

Result matches **A) full issue content** for tested heavy dates/section:
- Embedded `jsonArray` appears to contain the complete section payload, not first-page-only slice.
- No evidence of UI pagination for `leiturajornal?data=...&secao=do3` in these probes.

Recommendation before implementing crawl pagination:
- Keep discovery/payload parsing as-is for modern `leiturajornal` view.
- Treat pagination as a separate concern only if future probes find `totalPages > 1` or active page controls on this view.
