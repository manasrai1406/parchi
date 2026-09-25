# Design: Theme C

Dark palette, left sidebar, violet accent for actions, green reserved for success.

## What the files here are

The `.dc.html` files are the source of the design canvas boards. They are one self-contained page each, written with inline styles, and they need the canvas runtime (`support.js`) to render, so opening them in a browser will not show the design. Use them as a reference for markup, spacing and copy: read the inline styles and the sample data. Build the real pages as React components with Tailwind.

| File | Page |
| --- | --- |
| `Main.dc.html` | Files (status list, summary cards, filters, batch selection) |
| `UploadC.dc.html` | Upload |
| `ReviewC.dc.html` | Review (original file, library vs AI results, line items) |
| `QueryC.dc.html` | Query |
| `AiConfirmC.dc.html` | Dialog: approve AI for one file |
| `AiBatchC.dc.html` | Dialog: approve AI for a batch |

The Files page in `Main.dc.html` has working filter chips and row selection written as a small state class. It shows the intended behavior.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| ground | `#0B1210` | Page background |
| sidebar | `#0F1815` | Sidebar and table headers |
| card | `#121C18` | Cards and tables |
| border | `#1F2E28` | Card borders, dividers |
| input border | `#2A3B34` | Inputs and secondary buttons |
| text | `#EAF2EE` | Body text |
| muted | `#9DB0A7` | Secondary text |
| accent | `#8B7CF6` | Primary buttons, selected chips, focus. Text on it is `#0B0820` |
| accent soft | `#241F4D` | Active nav item, selection bar |
| accent text | `#B9AFFF` | Links and eyebrow labels |
| success | `#3DDC97` and `#6EE7B0` | Parsed badge, done progress |
| needs review | `#FFC766` on `#3A2A0B` | Needs review badge |
| flagged | `#FF9C8A` on `#3A1A14` | Flagged badge |
| processing | `#8FC3FF` on `#12283F` | Processing badge, progress |
| pending | `#B9C7C0` on `#222E29` | Pending badge |
| resolved | `#9BDDBC`, border `#3D6152` | Resolved badge (outline) |

Fonts: Space Grotesk for headings, DM Sans for body, JetBrains Mono for file names, reference numbers and figures.

## Rules

- Minimum touch target height is 44px for buttons, inputs and links.
- Status is never shown by color alone: every badge has a text label and a dot.
- Sidebar badges count `needs_review` plus `flagged` files.
- The sidebar shows "AI approved today" with a bar, from `GET /ai/usage`.
- Every AI action goes through the approval dialog. Nothing is sent before the person approves.
- Show reference numbers (`REF-2026-000412`) in mono text wherever a file or receipt is listed.

The app is called Parchi. The sidebar logo text is "Parchi".
