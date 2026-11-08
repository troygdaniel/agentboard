# Settings: tabs

**Status: design, stage 1 of the card `settings-ui-tabs`.** Mockup (every tab, wide and narrow, a search state, light and dark): `docs/settings-tabs-mockup.html`,
with `settings-tabs-design-wide-light.png`, `-wide-dark.png`, `-narrow-light.png` and `-narrow-dark.png`. Every value in it is made up.

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
| **Agents and chat** | **Agent chat**: Agents may talk to each other (new control, the existing `/api/chat-agents`, the same as `agentboard chat agents on`). **Who is listening** (status, from the receipts the chat already polls) | new rows on existing data |
| **Texts** | Pull my texts, Text me back (Off / Dry run / Send, the inline Send confirm), the restart chip's row, the remember switch | plugin (home) |
| **Facts** | Keep a daily list of my events and to-dos, Refresh now | plugin (home) |
| **Security** | Status: lockdown, redaction, plugins allowed, last self-check | phase 2 (below) |
| **Backup and data** | Status: last backup, data folder mode | phase 2 (below) |

The sheet is 720px wide and `min(680px, 100vh - 48px)` tall; the tab list is vertical on the left, the pane scrolls inside it. At 900px of window height
General, Agents and chat, Texts and Facts fit whole; **Sound is the one tab that scrolls** (about five rows of effects below the fold). Splitting Ambience
into its own tab would fix that and cost a tab for a section most people open once; the design keeps one Sound tab.

## Nothing removed, nothing renamed

Rows keep their labels, their about lines and their element ids (`cfg-snd`, `cfg-amb`, `cfg-vol`, `lyr-*`, `mix-close`, the containers `mix-touch`,
`mix-amb`, `mix-fx`, `mix-look`). Only places change: Look moves to General; Touch, Ambience and Effects move to Sound (Touch and Ambience share one heading,
Touch and ambience, in two columns); the paragraph that explains the sound defaults sits at the top of Sound. About lines are clamped to two lines in a tab, the
whole line is the row's title and opens on a click. New: the Theme row, the Agent chat switch, the tab list, the search box.

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

## Two decisions for ORCH

1. **Security and Backup and data are phase 2.** They are read-only status (the lockdown state, whether redaction is on, whether plugins are allowed, the
   last self-check, the age of the last backup), and the page has no endpoint for them. A single `GET /api/settings` returning booleans, counts and ages
   (never a path, a key or a name) would feed both; it needs its own security review (AGENT-3) before it ships. The shell takes them as two more `AB.settingsTab`
   calls, so nothing in the build waits on them. The build covers General, Sound, Agents and chat and the plugin tabs.
2. **Agents and chat writes a board-wide setting from the page.** The call exists (`/api/chat-agents`, used by the CLI's switch) and is reversible, free and
   the owner's alone; the switch says what it does in one line. If you would rather keep that one in the terminal, the tab shows the status and the command
   instead.

## Build order

1. The shell: tablist, panes, `AB.settingsTab`, `AB.settingsBadge`, the old sections moved into General and Sound with the same ids, memory, deep link,
   keyboard, 390px, reduced motion. Page-script check, tests (the old Settings tests updated where a heading moved), before and after screenshots.
2. Search, the Theme row, the Agent chat switch and the listeners rows.
3. The home plugin's two page scripts on their own branch; then AGENT-6 render-checks every tab, light and dark, wide and narrow.

## Not designed

Editing the board's own values (owner, stale minutes) from the page; a Security or Backup action (run a self-check, make a backup); per-tab reset; import
and export of settings.
