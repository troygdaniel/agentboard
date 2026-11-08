# Settings in tabs: before and after

Card `settings-ui-tabs`; design in `docs/settings-tabs-design.md`. Stage 2: the tab shell, General, Sound, Agents and chat, search, the plugin tab API.
Throwaway board, made-up cards. The Texts tab in the screenshots is **simulated** with two rows registered through `AB.settingsTab` (the home plugin's own tab
content ships from its repo). Security and Backup and data (phase 2) are real: read-only status from `GET /api/settings`.

## Measured in a real browser (Chrome, 1280x900 and 390x844)

| | Before (main) | After |
|---|---|---|
| Sheet | 480 wide, one column; content 2164px tall at 1280 (2522px at 390) in an 868px (812px) sheet | 720x720 at 1280 (the screen at 390), a tab list and one pane |
| Rows reachable without scrolling | 8 of 21 | General 7 of 7, Agents and chat 9 of 9, a plugin tab whole; Sound 17 rows in a 1170px pane (1.7 screens) |
| Page script | valid | valid (`node --check` runs in `tests/test_settings_tabs.py`) |
| Console errors opening the sheet, switching every tab, searching | none | none |

Checked live: opening focuses the selected tab; Down / Down / End / Home move through the tabs and focus stays on them (the board's own arrow shortcuts do not also
run); the last tab is remembered per browser; `#settings/agents` opens that tab, `#settings` the remembered one, an unknown tab the remembered one; a plugin tab is
not drawn while its pane is empty, drawn when it gets a child, takes a badge dot, and `AB.openSettings(el)` lands on it; a row appended to the old `AB.settings`
slot makes a More tab; `/` focuses the search, "text" finds the plugin row, Enter opens its tab and marks it, no match says so, the first Escape clears and the
second closes; the Theme row and the header half-moon stay in step; the sound switch, ambient bed, volume and 17 layer switches are all still there with their
Hear buttons.

## Screenshots

| View | Before | After |
|------|--------|-------|
| Wide, light | `before-sheet-wide-light.png` | `after-general-wide-light.png`, `after-sound-wide-light.png`, `after-texts-wide-light.png`, `after-agents-wide-light.png`, `after-security-wide-light.png`, `after-backup-wide-light.png`, `after-search-wide-light.png` |
| Wide, dark | `before-sheet-wide-dark.png` | `after-general-wide-dark.png`, `after-sound-wide-dark.png`, `after-texts-wide-dark.png`, `after-security-wide-dark.png`, `after-backup-wide-dark.png` |
| 390px, light | `before-sheet-narrow-light.png` | `after-general-narrow-light.png`, `after-sound-narrow-light.png`, `after-security-narrow-light.png` |
| 390px, dark | `before-sheet-narrow-dark.png` | `after-general-narrow-dark.png`, `after-sound-narrow-dark.png`, `after-texts-narrow-dark.png`, `after-backup-narrow-dark.png`, `after-search-narrow-dark.png` |

The "before" is the old sheet's first screen; the rest of it scrolled.

## Try it

`tools/tabs_live_check.py` drives a running board (default `http://127.0.0.1:8795/`, set `AB_URL`) through the checks above and prints one line each;
`tools/tabs_focus_and_deeplink_check.py` checks that Tab and Shift+Tab never leave the sheet and that `/#settings/<tab>` waits for a tab a plugin registers late (AGENT-6's two findings);
`tools/tabs_shots.py <prefix> <outdir> [url]` takes the screenshots (it registers the simulated Texts tab itself). Both need
`pip3 install --target /tmp/qa_pylibs websocket-client` and a throwaway board (`AGENTBOARD_DIR` elsewhere, made-up cards).

## Security and Backup and data (phase 2)

`GET /api/settings` answers with booleans, whole numbers and nulls only (`settingsview.py`). Checked live: a foreign `Host` gets 403, a POST gets 404, `/#settings/security` on a cold load opens that tab (it is drawn once the status has been read, and the deep link waits for it), the search finds "masking", and neither tab shows a path-like string.
