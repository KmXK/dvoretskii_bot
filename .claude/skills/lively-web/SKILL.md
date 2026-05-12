---
name: lively-web
description: Design rule for the dvoretskii_bot web mini-app — the user wants the UI to feel alive, not static. Apply when editing files in `web/`, building new pages/components, adding interactive controls (buttons, toggles, likes, votes, drag-and-drop), or showing async state (loading, save, error). Skip for pure logic/util/api-client changes that don't render anything.
---

# Lively web UI

The owner of `dvoretskii_bot` wants every interactive surface in `web/` to feel alive. Static UIs get pushed back ("странно выглядит", "ничего не поменялось"). When you touch frontend code, design like the user is watching it move, not reading a screenshot.

## What "lively" means here

1. **State changes animate.** When `voted` flips, the heart pops. When a toast appears, it slides in. When a card opens, it scales. Never let a state change happen with a flat re-render.

2. **Feedback is instant.** Don't wait for the network round-trip before showing the result. Flip local state immediately on click, fire the API in the background, roll back + toast on error. The user explicitly called this out: "пусть сердечкой сразу становится красным, а не после выполнения хттп запроса".

3. **Effort goes into transitions, not just final states.** Spring physics (`type: 'spring', stiffness ~500, damping ~14`) over linear tweens. Stagger lists. Bounce on press (`whileTap={{ scale: 0.95 }}`). Use `AnimatePresence` for enter/exit when items appear or disappear.

4. **Tactile beats functional.** A like button is not just a like button — clicking it spawns floating hearts on like, skulls on unlike. Reactions, confetti, particles, scale pops are fair game when they fit. Don't be afraid of "extra".

5. **Errors are visible, not silent.** Use the toast system (`useToast()` from `src/context/useToast.js`) — `toast.error()` for failed actions, `toast.success()` / `toast.info()` for the rest. No silent catch blocks; no `alert()`.

## Tools that already exist — use them

| Need | Use |
|---|---|
| Spring/tap/drag animations | `framer-motion` (already in deps) |
| Enter/exit of dynamic lists | `<AnimatePresence>` around `motion.*` children |
| Notifications | `useToast()` → `success/error/info/dismiss` |
| Modal/dialog | `@radix-ui/react-dialog` (see `FeaturesPage.jsx`) |
| Theme tokens | Tailwind: `spotify-black`, `spotify-dark`, `spotify-gray`, `spotify-text`, `spotify-green`, plus standard palette |

## Concrete patterns

### Optimistic mutation

```jsx
const handleAction = async (id, desired) => {
  setItems(prev => prev.map(applyOptimistic(id, desired)))   // flip locally
  try {
    const updated = await api.post(`/api/.../${id}`, { ... })
    setItems(prev => prev.map(replace(updated)))             // authoritative
  } catch (err) {
    setItems(prev => prev.map(revert(id, desired)))
    toast.error(`Не удалось: ${err.message}`)
  }
}
```

### Press feedback without breaking nested clickables

If a card is clickable but contains its own interactive element (like, kebab menu), don't use CSS `active:scale-*` on the card — it propagates through ancestors regardless of `stopPropagation`. Instead: track press state with `onPointerDown/Up`, mark the inner control with `data-no-card-press="true"`, skip `setPressed(true)` when `e.target.closest('[data-no-card-press]')`.

### Skip-first-render animation

Spring on mount can look like a glitch when a modal opens. Guard with a ref:

```jsx
const firstRender = useRef(true)
useEffect(() => { firstRender.current = false }, [])
<motion.span
  initial={firstRender.current ? false : { scale: 0.5 }}
  animate={{ scale: [1.4, 1] }}
  ...
/>
```

### Particle bursts

For celebration/destruction feedback (like/unlike, save/delete), spawn 4-6 emoji particles with randomized `x`, `y`, `duration`, `delay`, animate to fade+rise, remove via `onAnimationComplete`. See `VoteButton` in `web/src/pages/FeaturesPage.jsx` for the pattern.

## What to avoid

- `alert()` / `window.confirm()` — use toast and `@radix-ui/react-dialog`.
- Bare CSS `transition-*` on hover state if framer-motion is already imported — keep one animation system per component.
- Silent `catch { /* noop */ }` on user-initiated actions — surface failures.
- Linear easing (`ease: 'linear'`) on UI motion — feels mechanical. Default to `easeOut` or springs.
- Waiting for the server to confirm a UX change the user already committed to (clicking like, toggling a switch).

## When in doubt

Add the motion. The user has explicitly preferred more animation over less, twice this session. Don't strip out a working animation to "simplify" unless the user complains it's distracting.
