# Dvoretskiy — Web Design System

Design spec for the mini-app / web client (`web/`). **Other agents: follow this when adding or editing any UI.** The identity is "Dvoretskiy" (a butler) — own identity, not a Spotify clone.

## 1. Tokens (source of truth: `src/index.css`)

All colors are CSS variables in `@theme`. Never hardcode hex in components — use the Tailwind utilities generated from these tokens. Light theme overrides the same tokens under `html.light`.

| Token | Utility examples | Use for |
|---|---|---|
| `--color-spotify-black` | `bg-spotify-black` | App background (ink) |
| `--color-spotify-dark` | `bg-spotify-dark` | Raised surface (panels, sidebars, sheets) |
| `--color-spotify-gray` | `bg-spotify-gray` | Cards |
| `--color-spotify-light-gray` | `bg-spotify-light-gray` | Hover / borders |
| `--color-spotify-text` | `text-spotify-text` | Muted / secondary text |
| `--color-gold` / `--color-gold-2` | `text-gold`, `bg-gold`, `from-gold` | **Brand accent**: active nav, primary brand actions, mascot glow |
| `--color-gold-soft` | `bg-gold-soft` | Soft gold background behind active/brand chips |
| `--color-indigo` / `--color-indigo-soft` | `text-indigo`, `bg-indigo-soft` | Data / informational / neutral-interactive |
| `--color-spotify-green` | `bg-spotify-green` | **Money / success / casino** semantics ONLY — do not repurpose as brand accent |

> The `spotify-*` token **names** are legacy; their **values** are the ink palette. Keep using the names so the whole app re-skins from one place.

### Semantic color rules
- **Brand / active / primary brand action** → gold.
- **Success / positive / money / casino win** → green.
- **Destructive / error / danger** → red (`text-red-*`, `bg-red-500/15`).
- **Info / data / neutral interactive** → indigo.
- **Muted text** → `text-spotify-text`. **Primary text** → `text-white` (auto-darkens in light theme).

## 2. Typography
- Display font **Manrope** (`--font-display`) is applied to `h1–h4` globally and via `.font-display`. Use it for headings, big numbers, and stat values.
- Body font is Inter / system.
- Numbers in stats/tables: add `.tabular-nums` so digits don't jump.
- Headings: bold/extrabold, `tracking-tight`. Section labels: `text-xs font-bold uppercase tracking-[0.08em] text-spotify-text`.

## 3. Icons — `lucide-react`
- **UI chrome uses lucide, never emoji**: section headers, buttons, nav, stat labels, empty states, list-item icons, toasts.
- Standard sizes: `16` (inline/buttons), `18–20` (nav/list), `22` (cards). `strokeWidth={2}`.
- Tint icons with the semantic color (`text-gold`, `text-indigo`, `text-spotify-green`, `text-rose-400`).
- Navigation icons live in `src/layouts/navigation.js` as `Icon` component refs — single source for Sidebar, BottomNav, and Home.
- **Emoji are allowed only as game/domain content**: slot reels, card suits, dice faces, chess/checkers pieces, sport markers. Do not lucide-ify these — they are the games' identity.

## 4. Mascot — the butler
- Frames extracted from the sprite sheet into `src/assets/` (`mascot_idle.png`, `mascot_idle_strip.png`).
- Use `<MascotLoader />` (`src/components/MascotLoader.jsx`) for loading states — it plays the idle sprite via CSS `steps()`.
- Place the mascot in **loading, empty states, login, 404** — neutral framing.
- **Never** use the mascot as the user's own avatar (the hero avatar is the logged-in user's photo/initial).

## 5. Components & layout
- **Cards**: `rounded-2xl border border-white/5 bg-spotify-gray p-4`, optional `shadow-sm`. Icon chip: `grid place-items-center rounded-xl` with a soft tint background.
- **Buttons**: primary brand = gold; neutral = `bg-white/5 hover:bg-white/10`; destructive = red. Always `transition-colors`, `rounded-lg`/`rounded-xl`.
- **Filter / segmented tabs**: active = `bg-gold-soft text-gold` (or green where the page is money/casino).
- **Sheets/modals**: Radix, `bg-spotify-dark`, `rounded-t-2xl` (bottom sheet) / `rounded-2xl`.
- **Responsive**: works in three contexts — Telegram phone & Telegram Desktop (`mode==='miniapp'`, BottomNav), and browser (`mode==='web'`: Sidebar at ≥768px, mobile header+drawer below). Content wrappers: `mx-auto max-w-* px-4`. Always test wide and narrow.

## 6. Motion (`framer-motion`, already a dependency)
- The UI should feel alive (see the `lively-web` rule). Page/content fade+rise on mount; `whileTap={{ scale: 0.97 }}` on tappable cards.
- Active nav indicator uses a shared `layoutId` pill (see `BottomNav`).
- Keep durations short (0.15–0.3s), springs for position (`stiffness ~400–500, damping ~30`).

## 7. Don't
- Don't hardcode hex colors or add a new palette — extend tokens in `index.css`.
- Don't use emoji for UI chrome; don't use lucide for game pieces.
- Don't repurpose green as the brand accent.
- Don't write "what changed" / changelog comments in code (history lives in git).
