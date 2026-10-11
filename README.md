# Solana AI Trader

Paper-first Solana/Pump.fun AI trading research bot with a phone-friendly dashboard.

Included:
- Autonomous paper-trading loop
- Hard deterministic filters before AI
- Jev primary, Laya fallback, Darwin escalation for stronger setups
- Wallet AI, Social AI, Risk AI
- Wallet profiler and overlap graph
- Entry, exit, sizing, and hard-risk engines
- SQLite trade history and performance stats
- Pump/PumpSwap/Jupiter/Jito execution-routing scaffold
- Clean dark mobile dashboard
- Live execution disabled by default

## Mac setup

```bash
git clone https://github.com/Jriv420/solana-ai-trader.git
cd solana-ai-trader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

Discovery scans a bounded set of DexScreener profiles, boosts, and takeovers, plus rotating watched tokens and configured WATCHLIST_MINTS. It does not scan every Solana token.

New Pairs uses a single free PumpPortal token-creation WebSocket subscription and shows launches received in the last hour. Launch time is the event receipt time; launches missed during downtime are not backfilled. USD data is enriched after DexScreener indexes a pair. No paid trade or account subscriptions are opened.

Trending ranks tokens checked in the last ten minutes by 70% volume percentile and 30% market-cap percentile, selectable over 5m / 1h / 24h. It ranks the scanned universe, including older coins, and is independent of the trading score. FDV fallback is labeled when actual market cap is unavailable.

Watch History stores up to 2,000 tokens and 5,000 evaluations in SQLite, including filter rejections and entry reasons. Per-coin history starts with this update. Mount a persistent Railway volume at the project's database directory to retain trades and watch history across redeployments.

Ticker numbers are bot setup scores out of 100, not probabilities of profit. Unscored/rejected tokens display Unscored. Wallet scores use fresh holdings and qualified observed history. Social scores use sampled X contract mentions when configured; unavailable inputs are labeled.

Run checks: `python -m unittest discover -s tests -v` and `node --check dashboard/app.js`.

Never commit `.env`, API keys, wallet private keys, or seed phrases.

## Tracked-wallet holdings

Coin details checks current token balances for the wallets in `TRACKED_WALLETS` through `SOLANA_RPC_URL`. Set `TRACKED_WALLETS` to a JSON list of public addresses, or objects such as `[{"address":"YOUR_PUBLIC_WALLET_ADDRESS","label":"My tracked wallet"}]` (replace the example address). Up to 50 wallets are supported. Holdings are queried on details and in a bounded background loop, cached for 60 seconds, summed across all token accounts for that owner and mint, and listed only when positive. Partial or failed RPC checks are explicitly labeled; missing data does not mean the wallet sold. Labels are user supplied and do not verify an influencer's identity. Holdings do not supply entry price or PnL and feed wallet scoring only alongside qualified reputation evidence.

## Automatic wallet research and manual additions

The Wallets tab supports adding public wallet addresses, optional labels, and stopping tracking. Records, disabled-wallet choices, trade evidence, and reputation profiles live in SQLite and need the same persistent Railway volume as trades. Adding a wallet manually keeps it tracked without requiring profitable history; disabling it prevents discovery from re-enabling it. Environment-configured addresses also appear in the dashboard.

A background researcher runs every 30 seconds. It samples the 20 largest token accounts of one recently scanned coin, resolves account owners, and excludes non-system-owned/program-owned authorities. This is bounded discovery from scanned coins, not every wallet or every buyer on Solana. Pool/exchange categorization is not exhaustive and labels do not establish influencer identities. Balances across an owner's discovered token accounts are summed, valued at the snapshot price, and considered fresh for 15 minutes. The observed portfolio includes only those scanned positions, not a complete portfolio valuation. Automatic whale tracking defaults to a $25,000 position or $100,000 observed portfolio (`WHALE_POSITION_USD`, `WHALE_PORTFOLIO_USD`).

With `HELIUS_API_KEY`, the learner queries Helius Parsed Events transaction history for up to two pages (200 transactions) per candidate, at most two candidates per research cycle and no more frequently than every ten minutes per wallet. Parsed Events requests use provider credits. Normalized evidence is persisted by signature and deduplicated across runs. The adapter uses the current Helius SDK schema, `POST /v1/parsed-events/transaction-history`.

Reputation updates from matched observed SOL-quoted buys/sells using weighted average cost basis and reported network fees. Incoming/outgoing transfers, ambiguous quote flows, unsupported/missing parsed data, and sells without known cost basis do not earn profit credit. Missing-history windows reset inventory evidence; parser errors mark the profile incomplete. The number is an estimate for this observed subset, not verified lifetime PnL. USDC/USDT-quoted swaps, arbitrary multi-asset swaps, off-wallet positions, and full historical backfills are not included. Whales are not automatically marked profitable.

Automatic profitable tracking requires at least ten matched sells (`WALLET_MIN_MATCHED_SELLS`), three different tokens, positive observed net PnL, at least 60% wins, and at least 10% observed ROI. A Wilson confidence bound penalizes small win-rate samples in the reputation score. Selection can change as outcomes arrive; this is statistical evidence-based reputation, not LLM model training. Profiles must have a successful evaluation within an hour for profitable selection. Manual wallets take priority, and up to 50 wallets total are checked in coin details; excess automatic candidates remain visible as research candidates. Fresh qualified-holder evidence now feeds the independent wallet entry gate. Whale labels alone cannot pass that gate.

Discovery uses `SOLANA_RPC_URL`, or the standard Helius mainnet RPC derived privately from `HELIUS_API_KEY` when no separate RPC URL is set; performance learning requires `HELIUS_API_KEY`. The dashboard states when either connection is missing or unavailable.


## Narrative, transfer and security learning

Narrative Research accepts a coin contract, public wallet, person/lore connection, source link, and user-reviewed identity/endorsement status. Verification or confirmed/denied endorsements require an HTTPS source URL, but the app does not authenticate the source, wallet identity or X author automatically. The API is authenticated and uses the same origin check as wallet writes. Revisions remain in SQLite; latest review per wallet is displayed. Saving a claim starts manual research of its wallet and adds the 20 most recently labeled coins to each scanner cycle. Other coins rotate through the existing scanned universe.

Helius parsed history of researched wallets records matched SOL buys/sells separately from received/sent transfers and ambiguous swaps. A received transfer does not establish gift intent, investment, identity or endorsement. Multiple transfers in a transaction are netted by wallet and mint. Supply percentages are approximate and use the latest RugCheck supply; received transfers of at least 5% are flagged. This is a sampled historical transfer report, not a complete holder acquisition index or proof the recipient still holds the gift.

Security research queries one public RugCheck token report every ten seconds, with a five-minute success cache and one-minute failure retry. The integration follows https://api.rugcheck.xyz/swagger/doc.json. Missing, malformed or stale checks block new paper entries, as do danger flags, rugged reports, or active mint/freeze authority. Rejected tokens remain visible and their price outcomes are still observed. Provider reports can lag the chain; no report guarantees safety. Existing exits continue normally.

Bundle indicators use provider bundle/insider flags and three or more observed buying wallets in the same slot. These are clues from partial history, not verified Jito bundles or common ownership. No Jito bundle feed, full early-buyer index, or common-funder graph is connected.

At each fresh price observation the bot freezes categorical research features for a case. It measures forward 5m, 1h and 24h returns, peak gains and maximum observed peak-to-trough drawdown. Later verification creates a different feature case; it never relabels earlier outcomes. Stale prices and missed measurement windows remain missing. Observation frequency may miss intraperiod moves; statistics are price outcomes, not executable PnL after fees/slippage, and do not prove an endorsement caused a gain or drop.

The risk scorer adds caution for speculative identities/endorsements and bundle indicators. Once a pattern has forward 1h outcomes from at least ten distinct coins, it adds up to ten more risk points based on observed drawdowns of 30% or more. Distinct coins, not repeated scans, are the sample unit. Returns, positive-outcome frequency and sharp-dip frequency are shown for comparison and passed to configured Jev/Laya alongside evidence. This is statistical memory and risk adaptation, not LLM retraining or autonomous social verification. Without model endpoints the rule-based fallback still applies the risk adjustment. Paper mode remains default and live execution remains disabled.

Research retains up to 5,000 claims, 20,000 sampled transaction events, 2,000 security reports and 10,000 cases in the same SQLite database. A persistent Railway volume is required for memory across deployments. RugCheck uses the public report route; Helius history uses the existing HELIUS_API_KEY and provider credits. X and model access require the optional variables below.


## Revival, connections and paper accounting

Older or unknown-age coins must have at least $5,000 current 5m volume, more buys than sells, and volume acceleration, a qualified holder, watched KOL mention or recorded narrative. Volume acceleration compares the current five minutes with the average of the other eleven five-minute periods in the last hour. Configure REVIVAL_MIN_VOLUME_5M_USD and REVIVAL_VOLUME_RATIO. Security and hard risk gates apply to both new and revival setups. No market coverage or profitable-entry guarantee is implied.

AI Agents shows configured versus verified provider responses. Jev falls back to Laya, then Darwin only when the deterministic setup score reaches 60; otherwise rules apply. Paid assessments wait for qualified wallet evidence and cache for 30 seconds. Test AI connections sends one request per configured model and may consume credits. Jev uses the documented native OpenJEV SystemOne API at https://api.openjev.sh/v1/systemone: HTTPS POST with Authorization Bearer, model openjev, supplied state and a named setup score question with five ordered criteria. The answers.setup.score level index (0–4) is normalized to 0–100; confidence stays separate and never increases the setup score. Requests run one at a time with a ten-second default timeout and Retry-After cooldown on 429/503. Configure JEV_API_KEY and JEV_ENDPOINT. Laya still uses a generic gateway {state, questions}, and Darwin {prompt, data}, returning a numeric score; native contracts for those providers require their own adapters. OpenJEV evaluates supplied data; it does not browse source URLs or independently investigate lore. Never put credentials in frontend files.

Set X_BEARER_TOKEN privately on Railway for X recent search access. One exact-contract search per minute rotates through up to 100 watched coins, using one page of up to 100 posts from the last ten minutes. Results over ten minutes old are stale. Optional X_KOL_IDS is a comma-separated list of immutable author IDs; user-supplied watched IDs are not verified identities. Mentions are evidence, never automatic endorsement confirmation. Provider rate limits, availability and credits apply; Telegram/Discord are not connected.

For durable memory attach a Railway volume at /data. The database automatically uses RAILWAY_VOLUME_MOUNT_PATH/trades.sqlite3, unless DB_PATH explicitly selects a location. Existing installations should retain their current mounted database path. A new empty volume starts fresh and cannot recover previous ephemeral databases. Back up any existing data before moving paths. Runtime databases are excluded from Git. The production app uses one process and one replica for SQLite and background loops.

New paper fills use token quantities and current SOL/USD. Defaults estimate 1% proportional fees and 1% slippage per side; set PAPER_FEE_BPS and PAPER_SLIPPAGE_BPS to change these assumptions. They do not model actual route quotes, network/priority fees, liquidity impact or missed fills. Existing legacy trades retain their old accounting and are counted separately. Entries need positive finite token/SOL prices and sufficient available balance. Daily realized loss resets at UTC midnight; lifetime PnL stays separate.

Paper exits use the adaptive AI review described below. STOP_LOSS_PCT=20 and PAPER_MAX_HOLD_MINUTES=1440 remain protective limits. TAKE_PROFIT_PCT=50 and TRAILING_STOP_PCT=20 apply as explicit fallback rules when AI reviews are unavailable. Missing/stale prices wait rather than fabricate a fill. Paper performance is simulated; live execution remains disabled.

## Optional OpenAI review

Create a project key at https://platform.openai.com/api-keys and save it privately as `OPENAI_API_KEY` in Railway service Variables. Never put keys in GitHub, dashboard code or chat. Apply the variable changes, then use AI Agents → Test AI connections. API usage is billed separately from ChatGPT subscriptions.

Default `OPENAI_MODEL=gpt-5.6-terra` uses the Responses API with strict structured output, low reasoning effort, at most 1,000 output tokens, at most 12,000 bytes of evidence, no browsing/trading tools, and `store=false`. OpenAI sees supplied token, wallet and research evidence, not this ChatGPT conversation. This is inference with stored research context, not model retraining.

The optional second opinion runs after a baseline score of at least 60, behind the existing qualified-wallet gate. Its score can only lower the baseline. Independent security/risk/position gates remain enforced. A valid review is reused for 15 minutes per coin; cached results are bounded to 1,000 coins. Failures leave the baseline provider/rules working.

`OPENAI_DAILY_REQUEST_LIMIT=10` reserves attempts in SQLite before sending, including failed calls and manual tests, resetting at UTC midnight. The quota survives restart when DB_PATH is on the Railway volume. `0` disables requests. This is a request cap, not a dollar budget; token/model pricing and other applications using your key affect billing. HTTP 429/503 puts requests on cooldown, without automatic retry. Keep one Railway replica for this SQLite app. AI Agents shows model, today’s attempts, limit and connection status, without exposing credentials.

## Gemini free-tier second opinion

Save the Google AI Studio key privately in Railway as `GEMINI_API_KEY`, then apply changes. The default model is `gemini-3.5-flash-lite`; Google limits 2.5 model access to existing users, so new projects use 3.5 Flash-Lite. Keep billing disabled on the Google project to stay on the free tier. The app cannot inspect your Google billing tier, prevent charges on a billing-enabled project, or guarantee a particular free quota. Free-tier inputs may be used to improve Google products.

Gemini takes preference over OpenAI for automated second opinions. When Gemini is configured but unavailable, the baseline Jev/Laya/Darwin/rules assessment continues with no automatic paid OpenAI fallback. Tests still contact each configured provider and may use credits. Qualified-wallet and baseline >=60 gates, conservative minimum scoring, hard risk checks and paper-only execution continue to apply. Coin details show the second opinion's short explanation.

The native generateContent adapter uses a header key (never URL query), schema-constrained JSON, low thinking effort, at most 12,000 bytes of supplied evidence and 1,000 output tokens, without search or trading tools. It validates STOP completion, finite scores, blocking and malformed answers. Missing or unknown information remains unknown; token receipt is not identity/endorsement. No independent lore investigation or model retraining is added.

At most one new Gemini attempt per minute, with a default app cap of 100 per UTC day (`GEMINI_DAILY_REQUEST_LIMIT`), reserved persistently in SQLite including failures and manual tests. Set zero to disable Gemini requests. Google project/model quotas can be lower; 429/503 pauses requests without retry storms. Reviews cache for 15 minutes per coin, bounded to 1,000 coins. AI Agents shows Gemini model, connection status and app request counts without credentials.

## Lookalike contracts

The bot compares normalized names and tickers across the current scan and up to 2,000 retained observed tokens. Different contract addresses sharing both are labeled ambiguous as a branding warning; each contract continues through its own security, market and AI checks. Repeated listings of the same mint are evaluated once. New Pairs and evaluated coin cards display a warning with other matching contract addresses. This does not establish which contract is original, scan the entire market, or catch image-only copies, different branding, or all Unicode lookalikes. Existing positions still follow normal exit rules. No match observed is not an authenticity or safety approval.

## Market cohorts and downside learning

Fresh observed coins, including filtered setups, start forward outcome cases grouped by initial market cap (under $4k, $4k–$10k, $10k–$100k, $100k–$1m, $1m+), 5m absolute volume, turnover relative to cap, and evidence features. FDV is kept separate from market cap. Summaries at 5m/1h/24h report distinct coins, observed +50% peaks and ending losses of 50% or more. Missing or stale prices remain missing, not coin death; sparse sampling can miss peaks and rapid crashes. These are observed associations without fees, not causal evidence or model retraining.

Both Jev and the optional second-opinion adapter consider these summaries. Provider concentration warnings add 10 risk points, alongside existing bundle/narrative risk. Liquidity and security hard gates are unchanged; the default $10k liquidity minimum can exclude tiny caps from paper buys while still observing their outcomes. New cohort risk adjustment still requires 10 distinct coins with matching features.

## Research-informed review and timing (2026-10-10)

Jev and second opinions receive shared guidance to corroborate narrative/influencer attention with contract-specific fresh evidence and actual buying, account for manufactured volume, coordinated supply, execution delay, fees and sampling gaps, and avoid treating bundle exposure as an ability to exit before insiders. X remains optional and disconnected without its key; missing social evidence remains unknown. Cohorts now separate watched KOL mentions, none in the supplied sample, and unknown coverage.

Forward cases record the first observed +50% gain and −30% loss from their initial price. Horizon summaries count only milestones within that horizon and report medians among crossing coins, not all coins. Earlier stored cases have no reconstructed timings. These measurements do not change exit thresholds or bypass security gates. No live bundle-sniping strategy or retrained model is deployed.

Primary sources reviewed:
- Pump.fun official fees (updated 2026-10-08): https://pump.fun/docs/fees — 1.25% bonding-curve fee; PumpSwap fees vary by pool and tier. The app’s configurable proportional fee/slippage model is an estimate, not a route-specific quote.
- MELT (formerly MemeTrans), https://arxiv.org/html/2602.13480v2 — coordinated holdings, behavioral traces and time-based splits support risk screening; historical migrated-token sample is not universal profitability evidence.
- Resisting Manipulative Bots in Memecoin Copy Trading, https://arxiv.org/abs/2601.08641 — manipulation and trade execution lag undermine naive wallet copying.
- Hour-Aware Adaptive Risk Management, https://arxiv.org/abs/2606.08232 — exploratory paper-trading evidence with fragile results; do not transfer fitted thresholds or reported returns to this bot.

No independently verified profitable Jev + Gemini pump.fun strategy was established by this review. Principles are incorporated as hypotheses and conservative guidance; the cited models/datasets have not been installed or trained here. Validate future paper results after costs and across independent coins before claiming an edge.

## Mobile login and scanner diagnostics

Unauthenticated dashboard visits now open /login, a regular password form using the existing NEXUS_PASSWORD. Successful login stores a 12-hour signed Secure/HttpOnly/SameSite=Strict cookie; rotating the dashboard password invalidates sessions. Basic authentication remains supported for compatibility. Cookie-authenticated writes require the same Origin, and login rejects cross-origin submissions and rate limits failed attempts. Credentials never appear in URLs or browser storage. Expired API sessions redirect the dashboard to sign-in.

/api/status includes the last completed scan, coin counts, evaluation failure types, rejection reasons, paper buys this scan, and open positions. Aggregate scan summaries are logged without addresses, keys, passwords or provider response bodies. Completed scan statistics appear in Positions, Trade History, AI Agents, and Opportunities. A healthy web server alone does not establish a healthy scanner; missing or old scan completion and nonzero evaluation errors require investigation.

Rejected-coin learning preserves the first rejection and market evidence, revisits five least-recently observed rejected coins per scan for up to 24 hours, and compares observed winners and losers by rejection reason. Sampled peaks are not executable profits and unequal follow-up is shown explicitly. Gemini/Jev receive these summaries within existing request limits; this is evidence memory, not model-weight retraining. AI paper exceptions can waive revival/wallet/combined-score strategy thresholds when a real model score is at least 75, buying exceeds selling and 5m volume is at least $1,000. Current security clearance, the liquidity minimum, risk and account limits still apply. Exceptions are recorded in each trade's entry context. No live execution is enabled. `/healthz` is an unauthenticated readiness endpoint without private data.

`PAPER_RISK_TRIAL_UNTIL` is a fixed UTC Unix deadline for an optional riskier paper run. Decisions return to base settings automatically at expiry (including after restarts). The trial uses $5k liquidity, score 60, wallet 40, contextual risk 75, revival volume $2k/5m and acceleration 1.5x; AI paper exception score 65. Buys are capped at .025 SOL, three positions, and .15 SOL daily realized loss. Existing stricter size/exposure limits are retained. Security clearance remains required; duplicate contract addresses are deduplicated. Matching-name branding warnings do not block entries by themselves. Existing trades, capital and history are preserved; existing positions continue under normal exit rules after the trial. The loss threshold blocks new entries, not a guarantee against gaps or losses on open positions.


### Cached web sources and aggressive paper benchmark
`TAVILY_API_KEY` enables exact-contract-address Tavily Basic search. Up to four excerpts (700 characters each) and HTTPS source links enter existing AI evidence; search never sets verified identity/endorsement or fabricates lore. Project-provided DEX links are displayed as unverified. Search coverage is partial, especially for fresh tokens/X. Automatic research prioritizes recent liquid high-volume coins; a dashboard search button uses the same budget/cache. Persistent attempts are capped at 25/UTC day and 750/UTC month; global rate is one/minute. Found/error results cache six hours, empty results 30 minutes. Counts include failures, and only this deployment's usage; provider/account limits can differ.

The AI Agents page includes an independent **aggressive momentum paper benchmark**, with separate SQLite `shadow_trades`, balance and history. It takes no live orders. Entries are deterministic; exits now use additional bounded AI reviews shared with the main paper book. Fresh prices, current RugCheck without danger, $5k liquidity, $2k five-minute volume, +5% five-minute change, and buys>sells are required. AI/wallet scores, age and confirmed lore are not required; bundle flags remain recorded. Buys cost .025 SOL, at most three positions; new entries pause after .15 SOL UTC daily realized loss. One-hour same-contract reentry cooldown. Same estimated fees, slippage and exit rules as the main book; prices are sampled, not executable quotes. Entry window persists until the existing paper risk trial deadline, or 24 hours after initial activation if no deadline is set. Exits continue afterward. Primary account/history are preserved. Aggregate realized results are not a controlled matched-cohort experiment, and exclude open-position PnL.

Darwin requires both `DARWIN_API_KEY` and `DARWIN_ENDPOINT`; a key alone is insufficient. Supply the provider's documented endpoint and compatible score response; no endpoint is guessed.


## Adaptive paper exits

Both paper accounts review open positions before entry scoring. JEV uses a native `choice` question (https://openjev.sh/docs) for an exit-specific categorical action: hold, sell 25%, sell 50%, or sell all of the current remainder. This is a separate question from its entry evidence score. Gemini supplies an action and reason when JEV is unavailable, using the existing shared daily request limit and provider cooldown. There is no automatic paid OpenAI fallback. JEV exit attempts have a separate persistent limit of 300 per UTC day across both accounts; ordinary entry requests retain their existing behavior. Each position is reviewed at most every 120 seconds, subject to scan latency and quotas.

Reviews receive current market/research evidence, eight recent market samples, the previous action, and up to twelve recently closed fills from the same account, including sampled subsequent price outcomes. Partial fills share a parent trade and are not independent observations. Retrospective user labels remain unverified. This conditions decisions on observed history; it does not retrain model weights, prove a strategy improves, or provide missing Pump/X engagement data.

An available AI hold can continue beyond the ordinary +50% profit target or trailing trigger. Security danger, user-requested exits, the hard loss stop and maximum holding time remain independent. If models are unavailable, paused, malformed or quota-limited, the old profit/trailing rules take over and the dashboard labels the fallback. JEV may return an action without an explanation; the UI states that rather than inventing a reason.

Decisions are stored in each position's context and a bounded 2,000-row audit table. Sell decisions are consumed before execution so restarts cannot replay a partial sale; a failed/stale fill waits for a later review. Further partial sells require a new decision, preserve proportional token quantity/fee cost basis, and do not reset balances. Positions and Trade History display provider, action, review time and supplied reason. No actual moonbag tokens are transferred.

## Independent paper protection monitor

Open positions in both books have a separate background protective check, targeting a five-second polling cycle with three concurrent price fetches. It calls no AI and does not wait for discovery or entry scoring. Network/provider delay can extend the interval, and a received DEX snapshot is not an on-chain tick or executable quote. Missing prices still do not fabricate a fill. A sudden gap can overshoot the -20% trigger substantially; the recorded fill and PnL use the observed price and estimated costs, never a fictitious -20% fill.

Twelve recent protective samples per position are persisted for exit review. Selling reloads the current position and rejects an already closed or resized position, preventing a delayed AI response from double-selling after a protective exit. The observed GTA 6 Coin -80.3% hard-stop incident is included as retrospective execution-risk evidence in research context. Bundling and the exact price path remain unverified; this is not evidence that every crash has the same cause.

### Is It Bundled? evidence

The bot batches up to 100 recent mints through https://isitbundled.com/api/v1/tokens in a separate background worker (one batch per 30 seconds maximum). Open positions are prioritized. Successful findings are cached five minutes; unscanned/unavailable results retry after a minute. No API key or new Railway variable is needed. Reports persist in the existing SQLite volume, bounded to 2,000 tokens.

Coin research shows launch bundled supply, creator/other bundles, current insider/flagged holdings and an attributed report link. Current holdings/risk are usable only with a provider report timestamp within ten minutes; fetching a report does not refresh its underlying age. Missing, stale, unscanned and failed responses never mean no bundle. Only provider-confirmed scanned no_bundle means that provider did not detect a launch bundle, not that a token is safe. These findings feed existing entry/exit evidence and prospective outcome cohorts; they do not prove wash trading, common ownership, endorsements or fraud. The aggressive paper benchmark does not automatically reject a coin because it was bundled. Existing RugCheck and protective rules remain independent.

### Position evaluation and forward exit tests

The AI Agents page has **Learning & strategy tests** for the selected paper account. Win rate now groups partial sells and the final remainder as one position, excluding open remainders and legacy fills without a cost model. It also reports average wins/losses, net expectancy, profit factor and completed-position realized drawdown. This drawdown does not include open-position swings. Activity comparisons use the same completed-position grouping.

New entries, AI exit reviews and sells save bounded point-in-time evidence in SQLite. `/api/learning/decisions?account=aggressive` (or `original`) requires dashboard authentication and returns at most 100 recent records. Observed final outcomes are separate from decision evidence: a profitable outcome is not automatically a correct-action training label. AI exit memory now uses completed costed positions rather than treating profitable partial legs as separate wins, retaining sampled after-exit reviews. No model weights are automatically trained.

Two versioned prospective exit hypotheses begin on new paper entries: the existing full-profit/trailing reference and a half-profit runner with a wider trail armed after +50%. They observe existing fresh market samples and use the entry's estimated fee/slippage model. They place no orders, spend no simulated balance, add no AI calls and request no extra market data. A gap through the loss trigger records the observed loss, not an invented fill at −20%. Missing prices leave trials pending; only the latest 4,000 comparisons are retained. A trial is paired with the actual result only when both positions have completed. Longer candidate holds can remain pending after actual observation stops; results therefore have incomplete-coverage and survivorship limitations. Portfolio capacity and resulting future entries are not simulated.

The review screen requires 50 paired positions, 20 distinct coins, seven elapsed days and entries on seven distinct UTC dates, then positive net profit above the matched actual result, profit factor above one and no worse completed-position drawdown. This is an evidence screen, not a statistical superiority test or automatic policy promotion. Trials, decision records (latest 5,000) and trade history share the existing persistent database. Self-hosting an additional local model is deferred until task-specific labeled validation justifies its hosting and memory cost.

### Empirical entry learning (paper only)

`entry-loss-v1` makes completed losses affect future **paper entries**, independently for each account. Original AI entry reviews receive compact historical pattern evidence. Both original and aggressive entry paths additionally apply the empirical gate after their normal eligibility checks; a discretionary exception cannot bypass it. Exits, sizing, protective limits and live trading remain unchanged.

A completed costed loss of at least 50% in the same contract creates a 24-hour re-entry cooldown. For broader patterns, fixed groups use entry market-cap basis/cohort, liquidity tier and volume/cap tier, plus available launch-bundle groups. Group evidence uses up to 500 completed costed positions within 30 days, one most recent position per distinct coin, excluding the candidate coin. Open positions, legacy uncosted fills and outcomes after assessment time are excluded. A group causes avoidance only with at least eight distinct coins, 60% losing positions, two losses of 50% or worse and negative average net return. Missing group data is unknown. Historical evidence refreshes every 30 seconds. This is an empirical policy that updates from outcomes, not calibrated model confidence, confirmed scam detection or model-weight training. Results can reflect old exits, market conditions and selection bias. New paper entries wait if learner assessment fails.

To audit missed winners as well as avoided losses, the first eligible screen per coin/account/UTC hour freezes the action, evidence counts and reason. Existing market observations supply the first fresh 60–70-minute mark, including estimated proportional round-trip fees/slippage and SOL conversion. A later price never fills a missing earlier mark. These marks are hypothetical one-hour outcomes, not completed strategy trades or executable returns. Allow means the learner permitted entry; position, balance and loss limits can still prevent a buy. SQLite retains up to 3,000 screens, while the dashboard summarizes the latest 1,000 and shows recent reasons for the selected account. Allowed and avoided results are correlated and selected; the table does not establish a causal gain in win rate. No extra provider calls or market requests are added. Skipped marks audit the policy rather than automatically labeling every avoided winner a correct buy.

### Paper testing controls and reviewed collapse example

`PAPER_DAILY_LOSS_LIMIT_ENABLED=false` disables the daily realized-loss pause in both paper entry paths without resetting history or balance. It cannot disable a live-trading daily loss limit. Sizing, position caps, security checks, severe-loss contract cooldowns and protective exits still apply. `PAPER_TEST_UNTIL` sets the persistent aggressive entry deadline; `PAPER_RISK_TRIAL_UNTIL` controls the original account's temporary trial rules. Dashboard and logs expose whether the paper daily pause is enabled.

SUPMKT's October 11 collapse screenshot is saved once as a suspected activity label and provided to current AI entry/exit reviews through activity evidence. The general example distinguishes the visible collapse from the user's unverified no-dip-buyers/fake-volume claims. It does not rewrite old entries, authenticate engagement or prove wash trading; later user labels can replace it. Models receive the example in evidence, not weight training.

### Prospective exit evolution

The paper learner runs eight bounded exit candidates (defensive, scalp, balanced,
runner) alongside actual entries. Five genes control profit threshold, sale
fraction, trailing width, trailing activation and maximum hold. Costs and observed
price gaps count; trials never create orders or change account balances. Existing
trials retain their original rules. No new data-provider requests are introduced.

Training requires 50 common completed distinct-contract comparisons across seven
UTC entry dates. The training winner and family parents are frozen. Validation
uses future entries in contracts never enrolled in that generation's training,
requiring 25 completed contracts across three entry dates. Only the frozen winner
is judged; validation does not select parents. Positive net profit, improvement
over actual exits on the same entries, profit factor above one (or positive wins
without losses) and no greater completed-position realized drawdown screen a
candidate for review. This is not a portfolio backtest or significance test.

A completed generation breeds one bounded mutation of each family's training
winner plus one newcomer per family. Policies that pass fresh validation become
limited evidence for future AI exit reviews; they do not replace trading rules
automatically. No JEV/Gemini weights are trained. Different hold times and liquidity
constraints are not fully simulated. Missing observations remain pending; 8,000
trial rows and the latest 31 generation summaries per account bound storage.
The finite paper entry window still applies; enough active entry dates are needed
before validation can complete. See AI Agents → Learning & strategy tests.

JEV exit requests now include four independent typed judgments: participation,
activity quality, narrative support and whether the entry thesis remains intact.
They share the same supplied state and API request with the action question.
Missing evidence is unknown; optional factor responses do not invalidate a valid
exit action. Evidence and factor results are saved for review, not assumed to be
correct training labels. Request-count caps remain unchanged; larger request
payloads can change provider token usage.


### Current model collaboration and trade history (model-team-v1)

Both paper accounts now use bounded independent reviews from every model with a key AND endpoint. Gemini evaluates supplied narrative/social evidence; optional Laya, Darwin and OpenAI review opportunity/risk; JEV receives peer findings and selects its own action. Valid entry scores use normalized weights (JEV 0.5, Gemini 0.3, other providers share 0.2), with adverse entry action recommendations able to pause entry. Valid exit actions use the same normalized weights to select the nearest permitted holding fraction. Advisory-only scores are supplied to JEV and never fabricated into exit votes. Unavailable models are excluded explicitly. All-model unavailability uses a named deterministic fallback. Protective rules remain independent and take precedence. This replaces the earlier first-success provider chain for runtime trading.

Exit actions permit every 10% increment, the existing 25% trim, hold, and full exit. Every partial sale applies once to the current remainder and requires a fresh review before another trim. JEV exit limit remains 300/day, Gemini uses its shared 100/day default and provider quotas, OpenAI its existing configured limit, and Laya/Darwin have 30 team attempts/day each. Limits include failed attempts and are persisted; no limit is a monetary budget.

The dashboard shows AVG ENTRY left and AVG EXIT right, including on mobile, full position history, aggregate realized PnL, and per-sale model reviews and risk overrides. The executor currently creates one buy per position; repeated entries are separate positions. AVG ENTRY therefore equals that position's executed entry snapshot; AVG EXIT is weighted by the quantities represented by partial sale cost bases. Missing/mixed cap versus FDV data is never invented. Historical trades are not assigned fabricated model explanations.

Model reviews and completed-position outcomes are logged for comparison. Per-model outcome summaries count distinct completed positions, not repeated reviews, and cannot isolate a provider's contribution. The existing frozen forward strategy tests and loss-pattern screens remain; no model-weight training, automatic unvalidated strategy promotion, live social-feed access or predictive-profit guarantee is claimed.

Audit example: shadow position 106 (trenchcat) was entered through the older momentum benchmark, reviewed by JEV alone for exits, partially sold 25% at 21:19:55 UTC for -0.005534 SOL, then stopped at 21:20:15 UTC for -0.017483 SOL. The adapter recorded no provider explanation; the internal reason cannot be recovered or attributed to Gemini.
