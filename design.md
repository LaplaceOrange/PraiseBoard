---
name: praise-board-design
description: Visual rules for authenticated teacher and administrator workspaces, roster forms, daily records, and printable praise boards.
version: 2026-10-09-admin
---

# PraiseBoard Interface Design

## 1. Scope and Priority

These rules apply to short authentication forms, workspace shells, dense data lists, multi-item editors, account forms, and fixed-format image layouts. They do not apply to marketing pages or deployment documentation.

Resolve conflicts in this order: user requirements, accessibility and usability, reader tasks, project conventions, this visual direction, decorative details.

## 2. Brand and Readers

[MUST] Interface controls name each action directly.

[SHOULD] Decision: Preserve the class-register visual system: cool white surfaces, ink-green text, teal actions, correction colors, fine table rules, and compact record typography. Basis: existing project identity and `static/css/app.css`.

[SHOULD] Controls remain familiar to readers who alternate between desktop and touch devices. Mobile layouts expose one main task column at a time.

[SHOULD] Feedback copy states the current result and the next available action.

## 3. Page Structure and Composition

[SHOULD] Dashboard layouts use a fixed-width desktop navigation rail, a compact context header, and a flexible content column. Place task records before secondary information. The page ends after the primary records and their controls.

[SHOULD] Below 760px, navigation opens as an overlay drawer from a compact header. Use a visible close control and restore focus when the drawer closes. Dense tables scroll within their own container; text does not shrink to preserve columns.

[SHOULD] Administrative lists and forms reuse the workspace shell. Keep framework filters and data controls inside the content area. Related-object popup forms omit workspace navigation.

[SHOULD] Form layouts group related fields in reading order. Search and bulk-selection controls remain above long selectable lists. Wide editors place fields beside the selection tool. At 980px and below, these columns stack in reading order.

[MUST] Action bars must not obscure selectable records or other controls. If the action bar cannot reserve its own viewport space, keep it in normal document flow.

[SHOULD] Fixed-format image layouts use a clear title, context line, grouped content, and stable page breaks. Screen navigation and controls do not appear in exported images.

## 4. Visual Rules

[SHOULD] Use `--pb-font` for interface text. Apply the shared `body`, `h1`, `h2`, `h3`, and `.pb-muted` type roles from `static/css/app.css`. Authentication headings use `.pb-login h1`. Use tabular numerals for dates and table identifiers.

[SHOULD] Use the existing `--pb-bg`, `--pb-surface`, `--pb-ink`, `--pb-muted`, `--pb-rule`, and `--pb-primary` color roles from `static/css/app.css`. Use `--pb-error` for errors. Use `--pb-warning-bg` and `--pb-warning-ink` for unfinished states, and `--pb-success-bg` and `--pb-success-ink` for completed states.

[MUST] Enabled body and control text maintain at least 4.5:1 contrast against their surfaces. Focus indicators remain visible for keyboard operation.

[SHOULD] Use a 4px spacing base with common gaps of 8px, 12px, 16px, 24px, and 32px. `.pb-content` defines the content measure and viewport gutters. At 980px and below, secondary dashboard content moves below the primary column.

[SHOULD] Use 1px rules to separate rows and sections. Use the shared 6px radius for controls and an 8px radius for compact authentication forms. Do not place cards inside cards.

[SHOULD] Use filled teal for the primary action, white with a rule for secondary actions, and text buttons for low-priority actions. Inputs use visible labels and a persistent focus ring.

[SHOULD] Use the local Lucide SVG icon set in `static/icons/`. Preserve its source stroke widths. Icon-only commands have a descriptive accessible name and a hover title. Do not use emoji or Unicode symbols as interface icons.

[SHOULD] Transitions last 150-220ms and describe state changes. Reduced-motion settings disable nonessential transitions.

## 5. Available Primitives

| Role | Implementation name or value | Source or path | Usage condition | Status |
|---|---|---|---|---|
| Body text | `body`, `--pb-font` | `static/css/app.css` | Regular interface text | Implemented |
| Page title | `h1`; `.pb-login h1` for authentication | `static/css/app.css` | One page heading | Implemented |
| Section and secondary text | `h2`, `h3`, `.pb-muted`, `.pb-subtitle` | `static/css/app.css` | Section hierarchy and supporting context | Implemented |
| Primary action | `.pb-button.pb-button--primary` | `static/css/app.css` | Main action in a view | Implemented |
| Text input | `.pb-input` | `static/css/app.css` | Search and data entry | Implemented |
| Status label | `.pb-status`, `.pb-status--success`, `.pb-status--warning`, `.pb-status--open`, `.pb-status-dot` | `static/css/app.css` | Compact state labels, not ordinary metadata | Implemented |
| Page container | `.pb-shell`, `.pb-content`, `.pb-main`, `.pb-public` | `static/css/app.css` | Authenticated layouts or short public forms | Implemented |
| Navigation | `.pb-sidebar`, `.pb-nav`, `.pb-topbar`, `.pb-nav-backdrop`, `.pb-mobile-menu`, `.pb-nav-close`, `.pb-mobile-brand` | `templates/board/base.html`, `static/css/app.css` | Shared navigation; mobile controls hidden on desktop | Implemented |
| Identity and context | `.pb-brand`, `.pb-brand-row`, `.pb-workspace-label`, `.pb-identity`, `.pb-avatar`, `.pb-topbar-leading`, `.pb-topbar-context`, `.pb-topbar-date`, `.pb-sidebar-foot` | `static/css/app.css` | Navigation identity and current context | Implemented |
| Dashboard layout | `.pb-dashboard-grid`, `.pb-dashboard-main`, `.pb-dashboard-aside` | `static/css/app.css` | Primary records beside secondary content | Implemented |
| Repeated task | `.pb-subject-grid`, `.pb-subject`, `.pb-subject-heading`, `.pb-locked` | `static/css/app.css` | Individual task cards, never section wrappers | Implemented |
| Secondary records | `.pb-facts`, `.pb-aside-link`, `.pb-history-list`, `.pb-history-row`, `.pb-history-empty` | `static/css/app.css`, `templates/board/dashboard.html` | Key-value context and short history lists | Implemented |
| Content groups | `.pb-heading`, `.pb-section`, `.pb-section-heading`, `.pb-summary-band`, `.pb-summary-copy`, `.pb-submission`, `.pb-submission-heading`, `.pb-praise-row` | `static/css/app.css` | Open content groups and record hierarchy | Implemented |
| Repeated record | `.pb-record` | `static/css/app.css` | Repeated structured records | Implemented |
| Icon button | `.pb-icon-button` | `static/css/app.css` | Icon command with title and accessible name | Implemented |
| Forms | `.pb-form`, `.pb-form--narrow`, `.pb-field`, `.pb-toolbar`, `.pb-password-input`, `.pb-search-input`, `.pb-table-search`, `.pb-login`, `.pb-login-brand` | `static/css/app.css` | Shared data entry and authentication | Implemented |
| Buttons and action groups | `.pb-button--secondary`, `.pb-button--text`, `.pb-button--full`, `.pb-actions`, `.pb-icon-actions`, `.pb-action-band` | `static/css/app.css` | Button modifiers require `.pb-button` | Implemented |
| Multi-item editor | `.pb-item-editor`, `.pb-item-layout`, `.pb-item-fields`, `.pb-selector`, `.pb-student-list`, `.pb-student-option`, `.pb-all-students`, `.pb-student-search`, `.pb-student-empty`, `.pb-editor-actions`, `.pb-save-state` | `static/css/app.css`, `static/js/editor.js` | Long selectable lists and repeated form groups | Implemented |
| Dense lists | `.pb-split`, `.pb-table-wrap`, `.pb-table`, `.pb-record-list`, `.pb-record--link`, `.pb-record--history` | `static/css/app.css` | Tables scroll only inside their wrapper | Implemented |
| Feedback | `.pb-empty`, `.pb-messages`, `.pb-message`, `.pb-message--error`, `.pb-message--success`, `.pb-form-error`, `.pb-search-empty` | `static/css/app.css` | Empty, error, confirmation and no-result states | Implemented |
| Keyboard access | `.pb-skip-link`, `:focus-visible` | `static/css/app.css` | Visible keyboard navigation | Implemented |
| Administrative widget adapter | `.pb-custom-admin`, `.pb-admin` | `templates/admin/base_site.html`, `static/css/admin.css` | Maps framework tables, forms, filters, and actions to shared visual roles; does not affect teacher pages | Implemented |
| Printable layout | `.print-page`, `.print-header`, `.print-title`, `.print-context`, `.print-content`, `.print-footer`, `.print-page-no` | `templates/board/print.html` | Fixed-format image pages | Implemented |
| Printable record | `.print-item`, `.print-item-title`, `.print-names`, `.print-name`, `.print-reason`, `.print-note`, `.print-attribution` | `templates/board/print.html` | Record heading, supporting text, and attribution | Implemented |

Public primitives are the names in this table. Page-specific styles use the `pb-custom-*` namespace. Page-specific styles may change layout, but may not change published primitive typography, borders, or surfaces.

State classes such as `.is-active`, `.is-nav-open`, `.is-dirty`, and `.pb-nav-open` belong to the corresponding shared primitive. JavaScript-only selectors do not define additional appearance.

Use button modifiers with the base button class:

```html
<button class="pb-button pb-button--primary" type="submit">保存</button>
```

## 6. Copy and Number Formats

[MUST] Buttons name the action, such as “保存草稿”, “提交填报”, “定稿” or “下载图片”.

[SHOULD] Errors state what failed and how to recover. Confirmation text states what changed without adding a success claim before the server confirms it. Saving states distinguish unchanged, edited, pending, and failed content.

[SHOULD] Display dates as `YYYY年M月D日`. Short dated records can separate the year from the month and day. Native date controls keep the browser's localized format. Display identifiers as supplied; do not add separators or infer numeric values.

## 7. Anti-Patterns

[SHOULD] Do not use a centered hero with a decorative card grid as the default authenticated page.

[SHOULD] Do not place cards inside cards.

[SHOULD] Do not use decorative icon tiles or colored icon backgrounds.

[SHOULD] Do not use font sizes, font weights, or color literals outside the published primitives unless a page-specific state requires them.

[SHOULD] Do not use low-contrast text for primary information.

[SHOULD] Do not use pill labels for ordinary metadata.

## 8. Implementation and Integration

[SHOULD] Shared interface styles live in `static/css/app.css`. Templates extend the shared layout and use the published primitive classes.

[SHOULD] Administrative templates extend `templates/admin/base_site.html` to reuse the shared layout. Load framework styles before the administrative adapter in `static/css/admin.css`. The adapter reuses `--pb-*` tokens and retains the framework widget selectors. Keep the administrative surface in the same light theme as the workspace.

[SHOULD] Image layouts use the dedicated inline stylesheet in `templates/board/print.html`. They reuse the interface color roles but omit workspace navigation. The page title is 48px, context is 25px, record headings and principal text are 27px, supporting notes and attribution are 23px, and footer text is 19px. Titles longer than 40 characters use 34px. These roles remain consistent across pages.

## Glossary

| Concept | Name |
|---|---|
| Application shell | `.pb-shell` |
| Primary action | `.pb-button--primary` |
| Text input | `.pb-input` |
| Status label | `.pb-status` |
| Repeated record | `.pb-record` |
