/**
 * "Gestion du Budget" — the integration's management panel.
 *
 * Built to the mockups in `design_specs/` (`Main.dc.html`, `Mobile.dc.html`)
 * and their HANDOFF.md: a header stating what is available today, an
 * "À surveiller" strip, the buckets split into shared and personal, and
 * a bucket's history in a side panel on desktop or a full screen on mobile.
 *
 * Two deliberate departures from the mockups:
 *
 *  - The mockups' Pierre/Camille switcher is gone. HANDOFF.md calls it a demo
 *    affordance, and filtering happens server-side here — the client is never
 *    sent someone else's personal buckets, so there is nothing to switch to.
 *  - The mockups are read-only, but this panel is the only management
 *    interface. Recording an expense, and editing a bucket, therefore live
 *    inside the detail panel where that bucket's context already is, and
 *    creating one sits next to the group headings.
 *
 * Money maths is not done here: `status`, `released_soon` and `recovery_date`
 * are computed in `calculations.py` and arrive through the websocket, so the
 * figures the panel shows are the tested ones. This file formats and lays out.
 *
 * Plain custom element, no build step. Home Assistant sets `hass`, `narrow`,
 * `route` and `panel` as properties on the element.
 */

const PANEL_TAG = "household-budget-panel";

/* Design tokens from HANDOFF.md, expressed so the panel follows the Home
   Assistant theme instead of pinning one palette: the mockup's values are the
   light-theme fallbacks. */
const STYLES = `
  :host {
    --hb-bg: var(--primary-background-color, #F6F6F4);
    --hb-surface: var(--card-background-color, #FFFFFF);
    --hb-text: var(--primary-text-color, #1A1D1B);
    --hb-muted: var(--secondary-text-color, #5B625D);
    --hb-divider: var(--divider-color, #E6E6E1);
    --hb-ok: var(--hb-accent, #0F766E);
    --hb-warn: #B45309;
    --hb-over: #B42318;
    --hb-warn-tint: #FBF1E4;
    --hb-over-tint: #FBEDEA;
    --hb-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;

    display: block;
    min-height: 100%;
    box-sizing: border-box;
    background: var(--hb-bg);
    color: var(--hb-text);
    font-family: "IBM Plex Sans", var(--paper-font-body1_-_font-family), system-ui, sans-serif;
    padding: 40px clamp(16px, 4vw, 56px) 64px;
  }
  @media (max-width: 700px) { :host { padding: 24px 20px 40px; } }

  /* The mockups specify one palette, for a light background. Those reds and
     ambers are chosen to sit on near-white and go muddy on a dark theme, so
     the dark variants below are lighter versions of the same hues. Switching
     to Home Assistant's own --error-color / --warning-color instead was the
     obvious move and is wrong: its light-theme warning is a bright orange
     that disappears on the pale tint. */
  .shell.dark {
    --hb-ok: #2DD4BF;
    --hb-warn: #FBBF24;
    --hb-over: #F87171;
  }

  .shell { max-width: 1120px; margin: 0 auto; display: flex; flex-direction: column; gap: 40px; }
  @media (max-width: 700px) { .shell { gap: 32px; } }

  .mono { font-family: var(--hb-mono); font-variant-numeric: tabular-nums; }
  .eyebrow {
    margin: 0; font-size: 12px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--hb-muted);
  }

  /* Header */
  /* Never wraps: wrapping dropped the button onto its own line, where
     space-between put it back on the left. The figure block shrinks
     instead, which is why it needs min-width: 0. */
  header { display: flex; flex-wrap: nowrap; justify-content: space-between; align-items: flex-end; gap: 20px; }
  .head-left { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  @media (max-width: 700px) { header { gap: 14px; } }
  .today { font-size: 13px; color: var(--hb-muted); }
  .total-line { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .total {
    font-family: var(--hb-mono); font-size: 40px; font-weight: 500;
    letter-spacing: -0.02em;
  }
  @media (max-width: 700px) { .total { font-size: 34px; } }
  .total-note { font-size: 15px; color: var(--hb-muted); }

  /* Alerts */
  .alerts {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 12px; margin-top: 12px;
  }
  .alert {
    font: inherit; text-align: left; border: 0; border-radius: 12px;
    padding: 16px 18px; cursor: pointer; display: flex; flex-direction: column;
    gap: 10px; width: 100%; box-sizing: border-box; color: var(--hb-text);
  }
  /* The mockups' flat pastels are light-theme values; on a dark theme they
     become a glaring block with unreadable text, because the text colour
     follows the theme and the tint does not. Deriving the tint from the
     status colour instead keeps the same look on light and adapts on dark.
     The flat value stays first as a fallback for browsers without
     color-mix. */
  .alert.warn { background: var(--hb-warn-tint); }
  .alert.over { background: var(--hb-over-tint); }
  @supports (background: color-mix(in srgb, red 10%, transparent)) {
    .alert.warn { background: color-mix(in srgb, var(--hb-warn) 14%, transparent); }
    .alert.over { background: color-mix(in srgb, var(--hb-over) 14%, transparent); }
  }
  .alert-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; width: 100%; }
  .alert-name { font-size: 15px; font-weight: 600; }
  .alert-pct { font-family: var(--hb-mono); font-size: 13px; font-weight: 500; }
  .alert-text { font-size: 13px; }

  /* Bars */
  .track { height: 6px; border-radius: 999px; background: var(--hb-divider); overflow: hidden; display: block; }
  /* Same reason as the tints: an ink-based wash reads on any background. */
  .alert .track { background: rgba(127, 127, 127, 0.25); }
  @supports (background: color-mix(in srgb, red 10%, transparent)) {
    .alert .track { background: color-mix(in srgb, var(--hb-text) 14%, transparent); }
  }
  .fill { height: 100%; border-radius: 999px; display: block; background: var(--hb-ok); transition: width 180ms ease-in-out; }
  .fill.warn { background: var(--hb-warn); }
  .fill.over { background: var(--hb-over); }

  /* Columns */
  .columns { display: flex; flex-wrap: wrap; gap: 40px; align-items: flex-start; }
  .lists { flex: 999 1 520px; min-width: 0; display: flex; flex-direction: column; gap: 36px; }

  /* Bucket rows */
  .group-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
  .row {
    font: inherit; color: inherit; text-align: left; background: transparent;
    /* Transparent rather than removed: the row keeps the exact height it
       had, so only the line goes, not the rhythm. */
    border: 0; border-bottom: 1px solid transparent;
    padding: 16px 12px; margin: 0 -12px; cursor: pointer;
    display: grid; grid-template-columns: minmax(0, 1fr) minmax(60px, 140px) 120px;
    gap: 20px; align-items: center; width: 100%; box-sizing: border-box;
  }
  .row[aria-expanded="true"] { background: var(--hb-surface); border-radius: 10px; }
  .row-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .row-title { font-size: 15px; font-weight: 500; }
  .row-rule { font-size: 12px; color: var(--hb-muted); }
  .row-head { font-family: var(--hb-mono); font-size: 15px; text-align: right; }
  .row-head.over { color: var(--hb-over); }
  @media (max-width: 700px) {
    .row {
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: "name head" "bar bar";
      row-gap: 10px; padding: 14px 0; margin: 0;
    }
    .row-name { grid-area: name; }
    .row-head { grid-area: head; }
    .row .track { grid-area: bar; }
  }

  /* Detail */
  aside {
    flex: 1 1 360px; min-width: 0; background: var(--hb-surface);
    border-radius: 16px; padding: 24px; display: flex; flex-direction: column;
    gap: 24px; box-shadow: 0 1px 2px rgba(26, 29, 27, 0.06);
    box-sizing: border-box;
  }
  .detail-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .detail-title { margin: 0; font-size: 20px; font-weight: 600; }
  .detail-rule { font-size: 13px; color: var(--hb-muted); }
  /* The negative margin moved to .detail-actions: it tucks the whole
     group into the card's corner, not each button on its own. */
  .icon-button {
    width: 44px; height: 44px; border: 0; flex-shrink: 0;
    background: transparent; border-radius: 10px; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    color: var(--hb-muted);
  }
  /* Same colours the text buttons carried, so the pencil still reads as
     the safe act and the bin as the destructive one. */
  .icon-button.accent { color: var(--hb-ok); }
  .icon-button.danger { color: var(--hb-over); }
  .icon-button.small { width: 32px; height: 32px; border-radius: 8px; }
  .detail-actions { display: flex; gap: 2px; margin: -10px -10px 0 0; }
  .summary { display: flex; flex-direction: column; gap: 8px; }
  .summary-top { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .summary-head { font-family: var(--hb-mono); font-size: 24px; font-weight: 500; }
  .summary-head.over { color: var(--hb-over); }
  .summary-spent { font-size: 13px; color: var(--hb-muted); }
  .summary-footer { font-size: 13px; color: var(--hb-text); opacity: 0.85; }

  .back {
    font: inherit; font-size: 14px; color: var(--hb-text); background: transparent;
    border: 0; min-height: 44px; padding: 0 10px 0 0; margin: -10px 0 0;
    align-self: flex-start; cursor: pointer; display: flex; align-items: center; gap: 6px;
  }

  /* History */
  .month { display: flex; flex-direction: column; }
  .month-head { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; padding-bottom: 6px; }
  .month-label { text-transform: capitalize; }
  .month-total { font-family: var(--hb-mono); font-weight: 500; color: var(--hb-muted); }
  .tx {
    display: grid; grid-template-columns: 52px minmax(0, 1fr) auto auto;
    gap: 12px; align-items: baseline; padding: 9px 0;
    border-top: 1px solid transparent;
  }
  .tx-date { font-family: var(--hb-mono); font-size: 12px; color: var(--hb-muted); }
  .tx-main { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .tx-label { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tx-note { font-size: 12px; color: var(--hb-muted); }
  .tx-note.soon { color: var(--hb-ok); }
  .tx-amount { font-family: var(--hb-mono); font-size: 14px; }
  .tx.out .tx-label, .tx.out .tx-amount, .tx.out .tx-note { opacity: 0.55; }
  /* An icon-only button has no text, so it has no baseline to sit on and
     centring it in the row dropped it between the label and its note.
     Pinned to the top of the row instead, with the 32px tap target
     bleeding 8px above and below so the icons centre on the first line,
     next to the label and the amount. */
  .tx-actions { display: flex; gap: 2px; align-self: start; margin: -8px 0; }

  /* Forms and buttons */
  button.text {
    font: inherit; font-size: 13px; background: transparent; border: 0;
    color: var(--hb-ok); cursor: pointer; min-height: 44px; padding: 0 8px;
    border-radius: 10px;
  }
  button.text.danger { color: var(--hb-over); }
  button.primary {
    font: inherit; font-size: 14px; border: 0; border-radius: 10px;
    background: var(--hb-ok); color: #fff; min-height: 44px; padding: 0 18px;
    cursor: pointer;
  }
  /* The dark theme's accent is a bright teal: white on it would be as
     unreadable as the pale tints were. */
  .shell.dark button.primary { color: #06201D; }
  /* Square and icon-only in the header: creating a bucket is a rare act and
     should not out-shout the figure it sits next to. Kept at 44px, the
     minimum tap target the handoff asks for. */
  button.add {
    width: 44px; height: 44px; padding: 0; flex-shrink: 0; margin-left: auto;
    border: 0; border-radius: 12px; cursor: pointer;
    background: var(--hb-ok); color: #fff;
    display: flex; align-items: center; justify-content: center;
  }
  .shell.dark button.add { color: #06201D; }
  button:disabled { opacity: 0.5; cursor: default; }
  button:focus-visible { outline: 2px solid var(--hb-ok); outline-offset: 2px; }

  /* Aligned on start, not end: bottom-aligning cells whose contents differ
     in height left the labels of a row sitting at different heights, which
     read as a broken grid. Aligning on the top of the row keeps every
     label on the same line. Rows breathe more than columns. */
  form {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 18px 14px; align-items: start;
  }
  /* Two columns on a phone too: amount and date belong side by side, and
     what made them look cramped was the bottom alignment and the date
     field's wrong height, both fixed above — not the column count. Only
     the gaps tighten. */
  @media (max-width: 700px) { form { gap: 14px 10px; } }
  form .wide { grid-column: 1 / -1; }
  form .actions { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
  form .actions.end { justify-content: flex-end; }
  label { display: block; font-size: 12px; color: var(--hb-muted); margin-bottom: 6px; }
  input, select {
    width: 100%; box-sizing: border-box; height: 44px; padding: 0 10px;
    border: 1px solid var(--hb-divider); border-radius: 10px;
    background: var(--hb-surface); color: var(--hb-text);
    font: inherit; font-size: 15px;
  }
  /* iOS Safari gives a date input its own intrinsic height and ignores the
     one we set, so it ends up shorter than the fields beside it. Dropping
     the native appearance is what makes it accept the box; the pseudo
     element is where the date text itself lives, and without resetting it
     the value sits off-centre. The picker still opens on tap. */
  input[type="date"] {
    -webkit-appearance: none;
    appearance: none;
    line-height: normal;
  }
  input[type="date"]::-webkit-date-and-time-value {
    text-align: left;
    margin: 0;
    height: auto;
  }
  .form-card {
    background: var(--hb-surface); border-radius: 16px; padding: 24px;
    box-shadow: 0 1px 2px rgba(26, 29, 27, 0.06);
    display: flex; flex-direction: column; gap: 18px;
  }
  .hint { font-size: 12px; color: var(--hb-muted); }
  .empty { font-size: 14px; color: var(--hb-muted); padding: 8px 0; }
  .error {
    font-size: 13px; color: var(--hb-over); border: 1px solid var(--hb-over);
    border-radius: 10px; padding: 10px 12px;
  }
`;

const CLOSE_ICON = `<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>`;
const PLUS_ICON = `<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>`;
const PENCIL_ICON = `<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19.5 8.5a2.12 2.12 0 0 0-3-3L5 17v3z"/><path d="M14.5 6.5l3 3"/></svg>`;
const TRASH_ICON = `<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6.5 7l.9 12.1a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4L17.5 7"/><path d="M10 11v6M14 11v6"/></svg>`;
const BACK_ICON = `<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>`;

const MOBILE_QUERY = "(max-width: 700px)";

/**
 * Whether the theme behind the panel is dark.
 *
 * Home Assistant exposes no "is dark" flag in CSS, so the panel reads the
 * background colour it actually resolved to and measures it. Anything below
 * half luminance counts as dark.
 */
function isDarkBackground(element) {
  const raw = getComputedStyle(element)
    .getPropertyValue("--primary-background-color")
    .trim();
  if (!raw) {
    return false;
  }

  let r;
  let g;
  let b;
  const hex = raw.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const value = hex[1];
    const full =
      value.length === 3
        ? value
            .split("")
            .map((c) => c + c)
            .join("")
        : value;
    [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  } else {
    const parts = raw.match(/\d+(\.\d+)?/g);
    if (!parts || parts.length < 3) {
      return false;
    }
    [r, g, b] = parts.slice(0, 3).map(Number);
  }

  // Rec. 601 luma, good enough to tell a dark theme from a light one.
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
}

function todayIso() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
}

function parseIso(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function daysBetween(fromIso, toIso) {
  return Math.round((parseIso(toIso) - parseIso(fromIso)) / 86400000);
}

function addDays(iso, days) {
  const d = parseIso(iso);
  d.setDate(d.getDate() + days);
  return d;
}

class HouseholdBudgetPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._buckets = [];
    this._expenses = [];
    this._canManage = false;
    this._selected = undefined;
    this._error = undefined;
    this._busy = false;
    this._editingExpense = undefined;
    this._bucketForm = undefined; // "new" | bucket_id
    this._unsubscribe = undefined;
    this._built = false;
    this._mobile = window.matchMedia(MOBILE_QUERY);
    this._onMediaChange = () => this._render();
  }

  set hass(hass) {
    const first = this._hass === undefined;
    this._hass = hass;
    if (first) {
      this._subscribe();
      this._loadExpenses();
    }
  }

  connectedCallback() {
    this._mobile.addEventListener("change", this._onMediaChange);
    if (this._hass && !this._unsubscribe) {
      this._subscribe();
      this._loadExpenses();
    }
  }

  disconnectedCallback() {
    this._mobile.removeEventListener("change", this._onMediaChange);
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = undefined;
    }
  }

  // -- Data -------------------------------------------------------------

  async _subscribe() {
    try {
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (message) => {
          this._buckets = message.buckets || [];
          this._canManage = Boolean(message.can_manage);
          this._error = undefined;
          this._render();
        },
        { type: "household_budget/subscribe_buckets", include_archived: true }
      );
    } catch (err) {
      this._fail(err);
    }
  }

  async _loadExpenses() {
    try {
      const response = await this._hass.callWS({
        type: "household_budget/expenses",
        limit: 500,
      });
      this._expenses = response.expenses || [];
      this._render();
    } catch (err) {
      this._fail(err);
    }
  }

  _fail(err) {
    this._error = err && err.message ? err.message : String(err);
    this._busy = false;
    this._render();
  }

  async _call(message, { reloadExpenses = true } = {}) {
    this._busy = true;
    this._render();
    try {
      await this._hass.callWS(message);
      this._error = undefined;
      if (reloadExpenses) {
        await this._loadExpenses();
      }
      return true;
    } catch (err) {
      this._fail(err);
      return false;
    } finally {
      this._busy = false;
      this._render();
    }
  }

  // -- Derived ----------------------------------------------------------

  get _isMobile() {
    return this._mobile.matches;
  }

  get _active() {
    return this._buckets.filter((b) => !b.archived);
  }

  get _selectedBucket() {
    return this._buckets.find((b) => b.bucket_id === this._selected);
  }

  _currency(bucket) {
    return (bucket && bucket.currency) || "EUR";
  }

  _money(amount, bucket, { round = false } = {}) {
    const currency = this._currency(bucket);
    try {
      const formatted = new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
      }).format(amount);
      // The mockups drop ",00" on round reference amounts like "650 € sur 30
      // jours", but never on a real total.
      return round ? formatted.replace(/[.,]00/, "") : formatted;
    } catch {
      return `${Number(amount).toFixed(round ? 0 : 2)} ${currency}`;
    }
  }

  _dayLabel(iso, options) {
    return parseIso(iso).toLocaleDateString(undefined,
      options || { day: "numeric", month: "short" });
  }

  _dateLabel(date, options) {
    return date.toLocaleDateString(undefined, options);
  }

  /** The headline figure: what is left, or how far over. */
  _headline(bucket) {
    const status = bucket.status || {};
    const over = status.status === "over";
    return {
      over,
      text: over
        ? `−${this._money(Math.abs(status.remaining ?? 0), bucket)}`
        : this._money(status.remaining ?? 0, bucket),
    };
  }

  _ruleLabel(bucket, { long = false } = {}) {
    const limit = this._money((bucket.status || {}).limit ?? 0, bucket, {
      round: true,
    });
    const base = `${limit} sur ${bucket.period_days} jours`;
    if (!long) {
      return base;
    }
    const kind = bucket.visibility === "personal" ? "Perso" : "Commun";
    return `${base} glissants · ${kind}`;
  }

  /** The sentence under a bucket's bar in the detail view. */
  _footerText(bucket) {
    const status = bucket.status || {};
    if (status.status === "over" && status.recovery_date) {
      return `Repasse sous le plafond le ${this._dayLabel(status.recovery_date, {
        day: "numeric",
        month: "long",
      })}`;
    }
    if (status.status === "over") {
      return "Ne repassera pas sous le plafond en vieillissant";
    }
    if ((status.released_soon ?? 0) > 0) {
      return `+${this._money(status.released_soon, bucket)} libérés d’ici 7 jours`;
    }
    return "Aucune libération cette semaine";
  }

  _alertText(bucket) {
    const status = bucket.status || {};
    if (status.status === "over") {
      const over = this._money(Math.abs(status.remaining ?? 0), bucket);
      return status.recovery_date
        ? `Dépassé de ${over} · sous le plafond le ${this._dayLabel(status.recovery_date)}`
        : `Dépassé de ${over}`;
    }
    const left = `Reste ${this._money(status.remaining ?? 0, bucket)}`;
    return (status.released_soon ?? 0) > 0
      ? `${left} · +${this._money(status.released_soon, bucket)} sous 7 j`
      : left;
  }

  /** A bucket's expenses grouped by month, newest month first. */
  _monthsFor(bucket) {
    const today = todayIso();
    const rows = this._expenses
      .filter((e) => e.bucket_id === bucket.bucket_id)
      .slice()
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

    const months = [];
    rows.forEach((expense) => {
      const d = parseIso(expense.date);
      const key = `${d.getFullYear()}-${d.getMonth()}`;
      let month = months.find((m) => m.key === key);
      if (!month) {
        month = {
          key,
          label: this._dateLabel(d, { month: "long", year: "numeric" }),
          sum: 0,
          items: [],
        };
        months.push(month);
      }
      month.sum += expense.amount;

      // Days until this expense stops counting. Negative or zero means it
      // already left the window.
      const daysLeft = bucket.period_days - daysBetween(expense.date, today);
      const counts = daysLeft > 0 && expense.date <= today;
      const releaseOn = addDays(expense.date, bucket.period_days);
      // A note only where it tells the reader something: money about to
      // come back, or an expense that is not weighing on the bucket.
      // "Counts until <date>" was on nearly every line, saying only what
      // the window already implies, and it wrapped to three lines on a
      // phone.
      let note = "";
      if (!counts) {
        note = expense.date > today ? "Pas encore comptée" : "Hors fenêtre";
      } else if (daysLeft <= 7) {
        note = `Libéré le ${this._dateLabel(releaseOn, { day: "numeric", month: "short" })}`;
      }

      month.items.push({
        expense,
        counts,
        soon: counts && daysLeft <= 7,
        note,
      });
    });
    return months;
  }

  // -- Actions ----------------------------------------------------------

  _select(bucketId) {
    this._selected = this._selected === bucketId ? undefined : bucketId;
    this._editingExpense = undefined;
    this._bucketForm = undefined;
    this._render();
  }

  async _submitExpense(event, bucket) {
    event.preventDefault();
    const root = this.shadowRoot;
    const amount = parseFloat(root.querySelector("#amount").value);
    if (!amount) {
      this._error = "Saisissez un montant différent de zéro.";
      this._render();
      return;
    }
    const payload = {
      bucket_id: bucket.bucket_id,
      amount,
      date: root.querySelector("#tx-date").value || todayIso(),
      description: root.querySelector("#label").value || null,
    };
    const editing = this._editingExpense;
    this._editingExpense = undefined;
    await this._call(
      editing
        ? { type: "household_budget/edit_expense", expense_id: editing, ...payload }
        : { type: "household_budget/add_expense", ...payload }
    );
  }

  _startExpenseEdit(expense) {
    this._editingExpense = expense.expense_id;
    this._render();
    const root = this.shadowRoot;
    root.querySelector("#amount").value = expense.amount;
    root.querySelector("#tx-date").value = expense.date;
    root.querySelector("#label").value = expense.description || "";
    root.querySelector("#amount").focus();
  }

  async _submitBucket(event) {
    event.preventDefault();
    const root = this.shadowRoot;
    const name = root.querySelector("#bucket-name").value.trim();
    const periodDays = parseInt(root.querySelector("#period-days").value, 10);
    const limit = parseFloat(root.querySelector("#limit").value);
    if (!name || !periodDays || Number.isNaN(limit)) {
      this._error = "Un nom, une fenêtre et un plafond sont requis.";
      this._render();
      return;
    }
    const threshold = parseInt(root.querySelector("#threshold").value, 10);
    const payload = {
      name,
      period_days: periodDays,
      limit,
      visibility: root.querySelector("#visibility").value,
      alert_threshold_percent: Number.isNaN(threshold) ? null : threshold,
    };

    const editing = this._bucketForm !== "new" ? this._bucketForm : undefined;
    const ok = await this._call(
      editing
        ? { type: "household_budget/update_bucket", bucket_id: editing, ...payload }
        : { type: "household_budget/create_bucket", ...payload },
      { reloadExpenses: false }
    );
    if (ok) {
      this._bucketForm = undefined;
      this._render();
    }
  }

  _openBucketForm(target) {
    this._bucketForm = target;
    this._render();
    if (target === "new") {
      this.shadowRoot.querySelector("#bucket-name").focus();
      return;
    }
    const bucket = this._buckets.find((b) => b.bucket_id === target);
    const root = this.shadowRoot;
    root.querySelector("#bucket-name").value = bucket.name;
    root.querySelector("#period-days").value = bucket.period_days;
    root.querySelector("#limit").value = (bucket.status || {}).limit ?? "";
    root.querySelector("#visibility").value = bucket.visibility;
    root.querySelector("#threshold").value =
      bucket.alert_threshold_percent ?? "";
  }

  async _deleteBucket(bucket) {
    const message = `Supprimer « ${bucket.name} » ? Si elle contient des dépenses, elle sera archivée et son historique conservé.`;
    if (!window.confirm(message)) {
      return;
    }
    if (await this._call({ type: "household_budget/delete_bucket", bucket_id: bucket.bucket_id })) {
      this._selected = undefined;
      this._bucketForm = undefined;
      this._render();
    }
  }

  // -- Rendering --------------------------------------------------------

  _el(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  // Icon-only, so the label has to live where assistive tech and a hover
  // tooltip can still find it.
  _iconButton(className, icon, label, onClick) {
    const button = this._el("button", className);
    button.type = "button";
    button.disabled = this._busy;
    button.setAttribute("aria-label", label);
    button.title = label;
    button.innerHTML = icon;
    button.addEventListener("click", onClick);
    return button;
  }

  _build() {
    const style = document.createElement("style");
    style.textContent = STYLES;
    const fonts = document.createElement("link");
    fonts.rel = "stylesheet";
    fonts.href =
      "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap";
    this._shell = this._el("div", "shell");
    this.shadowRoot.replaceChildren(fonts, style, this._shell);
    this._built = true;
  }

  _render() {
    if (!this._built) this._build();
    const shell = this._shell;
    // Re-checked on every render so switching theme is picked up.
    shell.classList.toggle("dark", isDarkBackground(this));
    shell.replaceChildren();

    const selected = this._selectedBucket;

    // Mobile shows the detail as its own screen, with a back button.
    if (this._isMobile && selected) {
      shell.append(this._renderBackButton(), this._renderDetail(selected, true));
      return;
    }

    shell.append(this._renderHeader());
    if (this._error) shell.append(this._el("div", "error", this._error));

    const alerts = this._active
      .filter((b) => (b.status || {}).status !== "ok")
      .sort(
        (a, b) =>
          ((b.status || {}).percent_used ?? 0) - ((a.status || {}).percent_used ?? 0)
      );
    if (alerts.length) shell.append(this._renderAlerts(alerts));

    const columns = this._el("div", "columns");
    const lists = this._el("div", "lists");

    const groups = [
      {
        key: "shared",
        title: "Enveloppes communes",
        items: this._active.filter((b) => b.visibility !== "personal"),
      },
      {
        key: "personal",
        title: "Mes enveloppes",
        items: this._active.filter((b) => b.visibility === "personal"),
      },
    ];
    groups.forEach((group) => {
      // Someone who cannot create a bucket has no use for an empty
      // "mine" heading.
      if (!group.items.length && group.key === "personal" && !this._canManage) {
        return;
      }
      lists.append(this._renderGroup(group));
    });

    // Only creation lives in the list; editing an existing bucket happens
    // in its detail panel.
    if (this._bucketForm === "new") lists.append(this._renderBucketForm());

    const archived = this._buckets.filter((b) => b.archived);
    if (archived.length && this._canManage) lists.append(this._renderArchived(archived));

    columns.append(lists);
    if (selected) columns.append(this._renderDetail(selected, false));
    shell.append(columns);
  }

  _renderHeader() {
    const header = document.createElement("header");
    const left = this._el("div", "head-left");

    const today = new Date();
    left.append(
      this._el(
        "span",
        "today",
        `Budget · ${this._dateLabel(today, {
          weekday: "long",
          day: "numeric",
          month: "long",
        })}`
      )
    );

    // The sum of what is left, ignoring overspend: a bucket in the red does
    // not lend its deficit to the others.
    const reference = this._active[0];
    const available = this._active.reduce(
      (sum, b) => sum + Math.max(0, (b.status || {}).remaining ?? 0),
      0
    );
    const releasing = this._active.reduce(
      (sum, b) => sum + ((b.status || {}).released_soon ?? 0),
      0
    );

    const line = this._el("div", "total-line");
    line.append(this._el("span", "total", this._money(available, reference)));
    line.append(
      this._el(
        "span",
        "total-note",
        `disponibles · ${this._money(releasing, reference)} libérés d’ici 7 jours`
      )
    );
    left.append(line);
    header.append(left);

    if (this._canManage) {
      const add = this._el("button", "add");
      add.type = "button";
      add.disabled = this._busy;
      // Icon-only, so the label lives where assistive tech and tooltips
      // can find it.
      add.setAttribute("aria-label", "Nouvelle enveloppe");
      add.title = "Nouvelle enveloppe";
      add.innerHTML = PLUS_ICON;
      add.addEventListener("click", () => this._openBucketForm("new"));
      header.append(add);
    }
    return header;
  }

  _renderAlerts(alerts) {
    const section = document.createElement("section");
    section.setAttribute("aria-label", "Enveloppes en alerte");
    section.append(this._el("h2", "eyebrow", "À surveiller"));

    const grid = this._el("div", "alerts");
    alerts.forEach((bucket) => {
      const status = bucket.status || {};
      const button = this._el("button", `alert ${status.status}`);
      button.type = "button";
      button.addEventListener("click", () => this._select(bucket.bucket_id));

      const top = this._el("div", "alert-top");
      top.append(this._el("span", "alert-name", bucket.name));
      const pct = this._el(
        "span",
        "alert-pct",
        `${Math.round(status.percent_used ?? 0)} %`
      );
      pct.style.color = `var(--hb-${status.status})`;
      top.append(pct);
      button.append(top);

      button.append(this._renderTrack(bucket));

      const text = this._el("span", "alert-text", this._alertText(bucket));
      text.style.color = `var(--hb-${status.status})`;
      button.append(text);

      grid.append(button);
    });
    section.append(grid);
    return section;
  }

  _renderTrack(bucket) {
    const status = bucket.status || {};
    const track = this._el("span", "track");
    const fill = this._el("span", `fill ${status.status === "ok" ? "" : status.status}`);
    fill.style.width = `${Math.min(Math.max(status.percent_used ?? 0, 0), 100)}%`;
    if (status.status === "ok" && bucket.color) {
      fill.style.background = `var(--${bucket.color}-color, ${bucket.color})`;
    }
    track.append(fill);
    return track;
  }

  _renderGroup(group) {
    const section = document.createElement("section");
    const head = this._el("div", "group-head");
    head.append(this._el("h2", "eyebrow", group.title));
    section.append(head);

    if (!group.items.length) {
      section.append(
        this._el(
          "div",
          "empty",
          group.key === "shared"
            ? "Aucune enveloppe commune."
            : "Aucune enveloppe personnelle."
        )
      );
      return section;
    }

    group.items.forEach((bucket) => {
      const row = this._el("button", "row");
      row.type = "button";
      row.setAttribute(
        "aria-expanded",
        this._selected === bucket.bucket_id ? "true" : "false"
      );
      row.addEventListener("click", () => this._select(bucket.bucket_id));

      const name = this._el("span", "row-name");
      name.append(this._el("span", "row-title", bucket.name));
      name.append(this._el("span", "row-rule", this._ruleLabel(bucket)));
      row.append(name);

      row.append(this._renderTrack(bucket));

      const headline = this._headline(bucket);
      row.append(
        this._el("span", `row-head${headline.over ? " over" : ""}`, headline.text)
      );
      section.append(row);
    });
    return section;
  }

  _renderDetail(bucket, isScreen) {
    const aside = document.createElement("aside");
    aside.setAttribute("aria-label", `Historique de ${bucket.name}`);

    const head = this._el("div", "detail-head");
    const titles = this._el("div");
    titles.append(this._el("h2", "detail-title", bucket.name));
    titles.append(
      this._el("div", "detail-rule", this._ruleLabel(bucket, { long: true }))
    );
    head.append(titles);

    // Editing and deleting the bucket belong to its title, not to the
    // bottom of the card: they act on the thing the title names.
    const headActions = this._el("div", "detail-actions");
    if (this._canManage) {
      headActions.append(
        this._iconButton(
          "icon-button accent",
          PENCIL_ICON,
          "Modifier l’enveloppe",
          () => this._openBucketForm(bucket.bucket_id)
        ),
        this._iconButton("icon-button danger", TRASH_ICON, "Supprimer l’enveloppe", () =>
          this._deleteBucket(bucket)
        )
      );
    }
    if (!isScreen) {
      headActions.append(
        this._iconButton("icon-button", CLOSE_ICON, "Fermer l’historique", () =>
          this._select(bucket.bucket_id)
        )
      );
    }
    if (headActions.childElementCount) head.append(headActions);
    aside.append(head);

    // While the bucket is being edited, the form is all the panel shows:
    // recording an expense next to it would be a second, competing task.
    if (this._bucketForm === bucket.bucket_id) {
      aside.append(this._renderBucketForm());
      return aside;
    }

    // Summary
    const status = bucket.status || {};
    const headline = this._headline(bucket);
    const summary = this._el("div", "summary");
    const top = this._el("div", "summary-top");
    top.append(
      this._el("span", `summary-head${headline.over ? " over" : ""}`, headline.text)
    );
    top.append(
      this._el(
        "span",
        "summary-spent",
        `${this._money(status.spent ?? 0, bucket)} / ${this._money(
          status.limit ?? 0,
          bucket,
          { round: true }
        )}`
      )
    );
    summary.append(top);
    summary.append(this._renderTrack(bucket));
    summary.append(this._el("div", "summary-footer", this._footerText(bucket)));
    aside.append(summary);

    aside.append(this._renderExpenseForm(bucket));
    aside.append(this._renderHistory(bucket));
    return aside;
  }

  _renderBackButton() {
    const back = this._el("button", "back");
    back.type = "button";
    back.innerHTML = `${BACK_ICON}<span>Budget</span>`;
    back.addEventListener("click", () => {
      this._selected = undefined;
      this._editingExpense = undefined;
      this._bucketForm = undefined;
      this._render();
    });
    return back;
  }

  _field(id, labelText, input, { wide = false } = {}) {
    const holder = this._el("div", wide ? "wide" : undefined);
    const label = this._el("label", undefined, labelText);
    label.setAttribute("for", id);
    input.id = id;
    holder.append(label, input);
    return holder;
  }

  _input(type, attributes = {}) {
    const input = document.createElement("input");
    input.type = type;
    Object.entries(attributes).forEach(([key, value]) => {
      input[key] = value;
    });
    return input;
  }

  _renderExpenseForm(bucket) {
    const form = document.createElement("form");
    form.addEventListener("submit", (event) => this._submitExpense(event, bucket));

    form.append(
      this._field("tx-date", "Date", this._input("date", { value: todayIso() }))
    );
    form.append(
      this._field(
        "amount",
        "Montant",
        this._input("number", { step: "0.01", placeholder: "0,00" })
      )
    );
    form.append(
      this._field(
        "label",
        "Libellé",
        // Several examples rather than one shop name: the field takes any
        // note, and a lone brand made it read as "where you bought it".
        this._input("text", {
          maxLength: 255,
          placeholder: "Boulangerie, essence, restaurant\u2026",
        }),
        { wide: true }
      )
    );

    // Right-aligned, with the primary button last: it ends the form where
    // the eye and the thumb finish filling it in.
    const actions = this._el("div", "wide actions end");
    if (this._editingExpense) {
      const cancel = this._el("button", "text", "Annuler");
      cancel.type = "button";
      cancel.addEventListener("click", () => {
        this._editingExpense = undefined;
        this._render();
      });
      actions.append(cancel);
    }
    const submit = this._el(
      "button",
      "primary",
      this._editingExpense ? "Enregistrer" : "Ajouter la dépense"
    );
    submit.type = "submit";
    submit.disabled = this._busy;
    actions.append(submit);
    form.append(actions);
    form.append(
      this._el(
        "div",
        "wide hint",
        "Un montant négatif enregistre un remboursement."
      )
    );
    return form;
  }

  _renderBucketForm() {
    const card = this._el("div", "form-card");
    const isNew = this._bucketForm === "new";
    card.append(
      this._el("h2", "eyebrow", isNew ? "Nouvelle enveloppe" : "Modifier l’enveloppe")
    );

    const form = document.createElement("form");
    form.addEventListener("submit", (event) => this._submitBucket(event));

    form.append(
      this._field(
        "bucket-name",
        "Nom",
        this._input("text", { placeholder: "Courses" }),
        { wide: true }
      )
    );
    form.append(
      this._field(
        "period-days",
        "Fenêtre (jours)",
        this._input("number", { step: "1", min: "1", value: isNew ? "30" : "" })
      )
    );
    form.append(
      this._field(
        "limit",
        "Plafond",
        this._input("number", { step: "0.01", placeholder: "500" })
      )
    );

    const visibility = document.createElement("select");
    [
      ["shared", "Commune"],
      ["personal", "Personnelle"],
    ].forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      visibility.append(option);
    });
    form.append(this._field("visibility", "Visibilité", visibility));
    form.append(
      this._field(
        "threshold",
        "Seuil d’alerte (%)",
        this._input("number", { step: "1", min: "1", max: "100", placeholder: "80" })
      )
    );

    const actions = this._el("div", "wide actions");
    const submit = this._el("button", "primary", isNew ? "Créer" : "Enregistrer");
    submit.type = "submit";
    submit.disabled = this._busy;
    const cancel = this._el("button", "text", "Annuler");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      this._bucketForm = undefined;
      this._render();
    });
    actions.append(submit, cancel);
    form.append(actions);

    const hint = this._el(
      "div",
      "hint",
      "Une enveloppe personnelle vous est attribuée et n’est listée que pour vous. Filtre d’affichage, pas restriction d’accès : les capteurs restent lisibles par tous."
    );
    card.append(form, hint);
    return card;
  }

  _renderHistory(bucket) {
    const section = this._el("div");
    section.append(this._el("h3", "eyebrow", "Historique des dépenses"));

    const months = this._monthsFor(bucket);
    if (!months.length) {
      section.append(this._el("div", "empty", "Aucune dépense enregistrée."));
      return section;
    }

    months.forEach((month) => {
      const block = this._el("div", "month");
      const head = this._el("div", "month-head");
      head.append(this._el("span", "month-label", month.label));
      head.append(
        this._el("span", "month-total", this._money(month.sum, bucket))
      );
      block.append(head);

      month.items.forEach((item) => {
        const { expense } = item;
        const row = this._el("div", `tx${item.counts ? "" : " out"}`);
        row.append(
          this._el(
            "span",
            "tx-date",
            this._dayLabel(expense.date, { day: "numeric", month: "short" })
          )
        );

        const main = this._el("div", "tx-main");
        main.append(
          this._el("span", "tx-label", expense.description || bucket.name)
        );
        if (item.note) {
          main.append(
            this._el("span", `tx-note${item.soon ? " soon" : ""}`, item.note)
          );
        }
        row.append(main);

        row.append(
          this._el("span", "tx-amount", this._money(expense.amount, bucket))
        );

        const actions = this._el("div", "tx-actions");
        actions.append(
          this._iconButton(
            "icon-button small accent",
            PENCIL_ICON,
            "Modifier la dépense",
            () => this._startExpenseEdit(expense)
          ),
          this._iconButton(
            "icon-button small danger",
            TRASH_ICON,
            "Supprimer la dépense",
            () =>
              this._call({
                type: "household_budget/delete_expense",
                expense_id: expense.expense_id,
              })
          )
        );
        row.append(actions);

        block.append(row);
      });
      section.append(block);
    });
    return section;
  }

  _renderArchived(archived) {
    const section = document.createElement("section");
    section.append(this._el("h2", "eyebrow", "Archivées"));
    section.append(
      this._el(
        "div",
        "hint",
        "Conservées pour leur historique : plus d’appareil ni de capteurs."
      )
    );
    archived.forEach((bucket) => {
      const row = this._el("div", "row");
      const name = this._el("span", "row-name");
      name.append(this._el("span", "row-title", bucket.name));
      name.append(this._el("span", "row-rule", this._ruleLabel(bucket)));
      row.append(name);
      row.append(this._el("span"));

      const restore = this._el("button", "text", "Restaurer");
      restore.type = "button";
      restore.disabled = this._busy;
      restore.addEventListener("click", () =>
        this._call({
          type: "household_budget/update_bucket",
          bucket_id: bucket.bucket_id,
          archived: false,
        })
      );
      row.append(restore);
      section.append(row);
    });
    return section;
  }
}

if (!customElements.get(PANEL_TAG)) {
  customElements.define(PANEL_TAG, HouseholdBudgetPanel);
}
