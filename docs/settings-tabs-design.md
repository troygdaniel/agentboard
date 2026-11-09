# Settings: tabs

**Status: designed in stage 1 (4d3b032), built in stage 2 (the shell, General, Sound, Agents and chat, search, the plugin API) and phase 2 (the Security and Backup and data tabs from `GET /api/settings`).** The card is `settings-ui-tabs`. Mockup images (every tab, wide and narrow, a search state, light and dark): `settings-tabs-design-wide-light.png`, `-wide-dark.png`, `-narrow-light.png` and `-narrow-dark.png`. Every value in it is made up.

## The problem

The Settings sheet is one column, 480px wide and as tall as the page: five sections (Sound, Touch, Ambience, Effects, Look) holding 19 switches and sliders,
then whatever the plugins append (Texts, Facts). It reads as a sound panel, the settings that are not sound (the Texts switch, the restart chip's row) sit
below the fold, and nothing on the board's own behaviour is in it at all.

## The tabs

A tab is drawn only while it has something in it. With no plugins the sheet has General, Sound and Agents and chat; the home plugin adds Texts and Facts.

| Tab | Holds | Source |
|-----|-------|--------|
| **General** | **Look**: Theme (new: Auto / Light / Dark, the same switch as the header's half-moon), Calm cards, Lively, From the future, Motion. **This board** (status): Owner, Stale after | Look moves here from the old sheet; the board's own values are read-only, each with the key that changes it |
| **Sound** | Sound, Ambient bed, Volume; **Touch and ambience** (Touch, Rain, Wind, Pad, Pulse, Deep space, Tide) in two columns; **Effects** (Echo, Duck the bed, Signatures, All clear, Chimes, Future sound, Hourly chime) | the old sheet's bulk, unchanged rows |
| **Agents and chat** | **Agent chat**: Agents may talk to each other, shown as on or off **with the command that changes it** (`agentboard chat agents on` / `off`): a read-only status, no switch (ORCH, 8 Nov). **Who is listening** (status, from the receipts the chat already polls) | new rows on existing data |
| **Texts** | Pull my texts, Text me back (Off / Dry run / Send, the inline Send confirm), the restart chip's row, the remember switch | plugin (home) |
| **Facts** | Keep a daily list of my events and to-dos, Refresh now | plugin (home) |
| **Security** | Status: lockdown, work profile, secret masking, plugins. The self-check row says how to run it: the board does not keep a result, and running it starts a throwaway server | built (phase 2) |
| **Backup and data** | Status: last backup and how many are kept, sync copy on or off and its last time, whether the data folder is private | built (phase 2) |

The sheet is 720px wide and `min(720px, 100vh - 48px)` tall; the tab list is vertical on the left, the pane scrolls inside it. At 900px of window height
General and Agents and chat fit whole, and so does a plugin's tab (Texts, Facts); **Sound is the one tab that scrolls**: measured in the built page its pane is about
1.7 screens tall (1170px in a 671px pane) because it holds 17 rows. Splitting Ambience and Effects into their own tabs would shorten it and cost two tabs for
sections most people open once; the build keeps one Sound tab, and the search box finds any layer in one keystroke.

## Nothing removed, nothing renamed

Rows keep their labels, their about lines and their element ids (`cfg-snd`, `cfg-amb`, `cfg-vol`, `lyr-*`, `mix-close`, the containers `mix-touch`,
`mix-amb`, `mix-fx`, `mix-look`). Only places change: Look moves to General; Touch, Ambience and Effects move to Sound, **each under the heading it had** (the mockup merged two of them; the build
did not), laid out in two columns; the paragraph that explains the sound defaults sits at the top of Sound. About lines are clamped to two lines in a tab, the
whole line is the row's title (a hover away). New: the Theme row, the Agent chat status row, the tab list, the search box.

## What a plugin does

One call, made once when the plugin's page script loads:

```js
const pane = AB.settingsTab('texts', 'Texts', { order: 40, icon: '<svg…>' });   // the same pane for the same id; returns an element
pane.append(head, box);                                                          // exactly what AB.settings.append did
AB.settingsBadge('texts', 'warn');                                               // the small amber dot on the tab ('' clears it)
AB.openSettings(head);                                                           // opens the sheet on the tab that holds head, scrolled to it
```

- **A tab with nothing in it is not drawn**, and is drawn the moment its pane gets a child (the sheet watches the panes).
- **`AB.settings` keeps working** for a plugin that has not moved: it is the pane of a last tab, **More**, drawn only if something was appended.
- The core tabs register through the same function (orders 10, 20, 30; plugins from 40; More last), so a plugin tab and a core tab behave the same.
- The restart chip's click (`AB.openSettings(head)`) now lands on the Texts tab; a Send confirm that opens inline stays in its pane.
- The home plugin's change is small (`AB.settings.append` becomes `AB.settingsTab(...).append`) and goes on a branch in its own repo; the shell works without it.

## Search, deep link, memory, keyboard

- **Search** (the box in the header, `/` focuses it from anywhere in the sheet): it indexes every row in every pane, hidden tabs included (the name, the
  about line, the tab), matches all the words typed, ranks a name that starts with the query first, and shows eight at most. Enter or a click opens the
  tab, scrolls the setting to the top and marks it for a second (a left bar instead when motion is reduced). Escape clears the box; a second Escape closes the sheet.
- **Deep link**: `/#settings` opens the sheet, `/#settings/texts` opens it on that tab. Changing tab updates the hash without a history entry; closing removes
  it. An unknown tab id falls back to the remembered tab, then General.
- **Memory**: the last tab used is kept per browser (`localStorage`, every read and write in `try/catch`), and the page works without it.
- **Keyboard**: the list is a real tablist: one tab stop, then Up / Down (Left / Right on a phone) move and select, Home and End go to the ends; `aria-selected`,
  `aria-controls` and `aria-labelledby` tie each tab to its pane. Focus order is the close button, the search box, the tab list, the pane. Opening focuses the
  selected tab; closing returns focus to the gear. Escape closes, as today.

## Narrow (390px)

Below 620px the sheet fills the screen. The tab list becomes a strip that scrolls sideways with an edge fade, and the selected tab scrolls itself into view;
the panes are one column. Because the search box finds a setting on any tab, no setting depends on its tab being in view.

Light and dark use only the board's tokens; the amber dot and the Send confirm keep their `--warn` colours; the flash is the only motion and is replaced by
a bar under reduced motion.

## Decided (ORCH, 8 Nov)

1. **Security and Backup and data are read-only status tabs, as phase 2 (built).** They use a new `GET /api/settings`: loopback only with the Host check, on / off and
   counts only (no paths, no patterns, no secrets: the same rule as `config show`), and AGENT-3 reviews it before it merges. The shell takes them as two more
   `AB.settingsTab` calls, so nothing in stage 2 waits on them.
2. **Agent chat is not written from the page.** The tab shows the status and the command to change it. If Troy later wants a switch, it gets a confirm box like
   Send's.

## Build order

1. **Stage 2 (built):** the shell (tablist, panes, `AB.settingsTab`, `AB.settingsBadge`), General, Sound and Agents and chat, search, the Theme row, memory,
   deep link, keyboard, 390px, reduced motion; page-script check, 31 tests, before and after screenshots.
2. The home plugin's two page scripts on their own branch (its tests, its repo); then AGENT-6 render-checks every tab, light and dark, wide and narrow.
3. **Phase 2 (built):** `GET /api/settings` (`settingsview.py`: every value a boolean, a whole number or null; a test pins that no string and no `/` can appear), the Security and Backup and data tabs; AGENT-3 reviews it before it merges.

## Not designed

Editing the board's own values (owner, stale minutes) from the page; a Security or Backup action (run a self-check, make a backup); per-tab reset; import
and export of settings.
