# UL 3DMark Fire Strike Source V1

## Scope

`parse_ul_3dmark_fire_strike_submission` converts one offline, browser-saved,
hydrated English UL 3DMark individual-result HTML document into the existing
`FireStrikeSubmissionV1` model.

The parser accepts only:

- `CapturedSourceV1`;
- source identifier `source:ul-3dmark-results`;
- media type `text/html`;
- strict UTF-8;
- Fire Strike Standard results.

It performs no networking, browser automation, acquisition, persistence, or
filesystem access. WAF pages, AJAX fragments, comparison pages, saved asset
directories, and other Fire Strike variants are outside this contract.

## Source identity

The URL used to open or share a browser run is not necessarily the benchmark's
native result identity. In the authorized source inspection, `/3dm/161404206`
resolved to a Fire Strike result whose native identity was `34771565`.

V1 requires agreement between two independent source structures:

1. a direct canonical link in the authoritative document `<head>`, with path
   `/fs/<id>`; and
2. the Fire Strike result side box's `ID` term and immediate value.

Both IDs must be positive canonical ASCII decimals without leading zeros. A
result-header compare path is optional corroboration; when present, it must
agree. Conflicting identities fail. `/3dm/` values, script endpoints,
OpenGraph data, and the acquisition URL never become submission identity.
Canonical-like links in the document body are decoys and are ignored. Body ID
text is validated exactly as captured; whitespace is not trimmed or folded
into a canonical identifier.

The resulting submission identity is:

`submission:source:ul-3dmark-results:<native-fire-strike-result-id>`

## Fire Strike Standard authority

The parser requires the combined evidence of:

- canonical family `/fs/<id>`;
- result-header label `Fire Strike`;
- result badge classes `result-badge test-fs`;
- one `scoresLinkfs-P` structure;
- its corresponding `scoresfs-P` target; and
- the Fire Strike result-side-box heading.

`P` is the structural Standard-preset discriminator. Extreme, Ultra, Custom,
stress-test, missing, duplicated, contradictory, and unknown presets are
rejected. Display text alone is not sufficient.

## Score authority

Overall comes only from the direct result-header chain:

`result-header → result-header-details → result-header-details-header → h1 → result-header-score → immediate score span`

Graphics, Physics, and Combined come only from direct additional-score chains:

`result-header → result-header-details → result-header-details-items → column3 → result-header-details-additional-score → dl → exact dt → immediate dd`

The supported terms are `Graphics Score`, `Physics Score`, and
`Combined Score`. Values use `marks`. V1 accepts canonical unsigned integer
text with either no grouping or single ASCII-space three-digit grouping. Zero
is an observed value. The exact numeric text token becomes raw evidence;
arbitrary leading, trailing, repeated, tab, newline, or Unicode whitespace is
not normalized into a score. Other localized or numeric forms are malformed.
For component `<dd>` values, surrounding UL markup indentation and the
decorative empty span are structural layout, not part of the numeric token.

Each field retains:

- the UL results source identifier;
- native `/fs/` result identity;
- exact capture SHA-256;
- a stable source-specific locator;
- raw lexical value when observed;
- canonical normalized decimal value;
- unit `marks`.

Absent valid authority produces `MISSING`. Equivalent observations collapse.
Distinct authoritative values produce deterministic `CONFLICTING` evidence.
Malformed authoritative values fail. No score is inferred from FPS or another
score.

## Decoy exclusion

The inspected page contains many unrelated numeric values. OpenGraph and
social text, JavaScript constants, histogram parameters, result-context rows,
`your-score-row`, compare widgets, lazy detailed-score content, frequencies,
memory quantities, dates, versions, and result IDs never produce score
evidence. Only the four documented direct structures are interpreted.

HTML attributes are compared case-insensitively. Any duplicate attribute name
on a parsed element is malformed, even when values are identical or ordering
is reversed. Structural DOM IDs such as `scoresLinkfs-P` must also be unique.

## Visibility

UL uses presentation classes differently from HWBOT. The inspected legitimate
result header contains class `hidden` as an animation token while its final
inline opacity is `1`. The collapsed result-details container uses `hide`
while still containing the authoritative source ID.

V1 therefore does not treat every `hidden` or `hide` class as global evidence
exclusion. Score candidates are excluded for semantic `hidden`,
`aria-hidden=true`, effective inline `display:none`, `visibility:hidden`, or
`opacity:0`, and for nested source-specific hidden score containers. A hidden
authority label cannot authorize a visible numeric sibling. The observed
final visible result-header animation state remains authoritative only on the
result-header root; it is not inherited by nested `hidden` elements.

For `display`, `visibility`, and `opacity`, V1 applies narrow inline
`!important` priority: important declarations outrank non-important ones and
later declarations win only at equal priority. It does not interpret external
stylesheets or selectors.

## Validity and deferred metadata

Parsing means that UL presented the captured score values. It does not claim
that the result is valid, stable, competition-eligible, or HWBOT-valid. The
authorized inspection included invalid-result notices; those notices do not
cause PR149 rejection because validity is not represented by
`FireStrikeSubmissionV1`.

Validity, invalidity reasons, Test Version, SystemInfo Version, date, user,
GPU, CPU, clocks, temperatures, driver, operating system, motherboard, memory,
FPS, and settings are deliberately deferred to later Benchmark Intelligence
models.

## Fixture provenance

The committed fixture is a minimal Atlas-authored reduction derived from the
authorized source structure. Its result ID and scores are synthetic. It
contains no real user or hardware data, scripts, analytics, cookies, external
assets, account details, validity notices, or result-context values. The full
authorized browser capture and its saved assets are not repository artifacts.
