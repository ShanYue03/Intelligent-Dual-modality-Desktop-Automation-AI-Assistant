# Voice assistant flow — **System part** explained simply

This matches how the project really works (`main.py`, Router, `System/`).  
Open this file in **Markdown preview** or paste the diagram into [mermaid.live](https://mermaid.live).

**About the router score:** the program sends you to **System** when the AI label is “system” **and** the score is **above 0.6** (not 0.8). Older drawings sometimes show 0.8; the code uses **0.6**.

---

## Main picture (like your diagram, with System opened up)

Read from **top to bottom**. The **System Control** box is expanded so you can see what happens inside.

```mermaid
flowchart TB
    subgraph USER["User"]
        MIC[Microphone]
        LANG[Language English or Chinese for voice]
    end

    ASR[Speech to text]
    TXT[English text of what you said]

    subgraph ROUTER["Router — decides System or Chat"]
        R1{Skip router?}
        R2{You said open plus a known site?<br/>YouTube ChatGPT Maps Wikipedia News}
        R3[Small AI model asks:<br/>is this a system command or chat?]
        R4{Answer is system and score over 0.6?}
    end

    subgraph SYS["System Control — expanded"]
        direction TB
        S0[Receive English text and language setting]
        S1{Text empty?}
        S1Y[Reply: I did not understand]
        S2{Browser or WhatsApp session already running?}

        subgraph PATHA["Path A — session already on"]
            A1{User said stop session or stop automation?}
            A1Y[Close session reply]
            A2[Soften text remove please now can you<br/>unpause counts as resume]
            A3[Match command search find type pause<br/>play first send and similar]
            A4[Do the action Edge helper or WhatsApp keys]
            A5[Short reply for speaking]
        end

        subgraph PATHB["Path B — no session yet"]
            B1[Clean text lowercase tidy symbols]
            B2[Run fixed checklist in order<br/>timer alarm time date links sites search<br/>youtube phrase screenshot copy paste<br/>folder app media and more]
            B3[First match wins else no system command]
            B4[Run action app folder screenshot<br/>start Edge session or normal browser]
            B5[Short reply for speaking]
        end
    end

    subgraph CHAT["Chat / reasoning"]
        LLM[Large language model writes an answer]
    end

    TTS[Text to speech]
    subgraph OUT["Audio output"]
        SPK[Speaker]
        VOICELANG[Same language choice as at start]
    end

    MIC --> ASR
    LANG --> ASR
    ASR --> TXT

    TXT --> R1
    R1 -->|yes| S0
    R1 -->|no| R2
    R2 -->|yes| S0
    R2 -->|no| R3
    R3 --> R4
    R4 -->|yes| S0
    R4 -->|no| CHAT

    S0 --> S1
    S1 -->|yes| S1Y
    S1 -->|no| S2
    S1Y --> TTS
    S2 -->|yes session| A1
    S2 -->|no session| B1
    A1 -->|yes| A1Y
    A1 -->|no| A2
    A2 --> A3
    A3 --> A4
    A4 --> A5
    A1Y --> TTS
    A5 --> TTS
    B1 --> B2
    B2 --> B3
    B3 --> B4
    B4 --> B5
    B5 --> TTS

    CHAT --> TTS
    TTS --> SPK
    TTS --> VOICELANG
```

**Labels on the Router arrows (plain words)**

| Arrow | Meaning |
|--------|---------|
| **Skip router → yes** | You are already answering a “did you mean this app?” question **or** a browser/WhatsApp session is **still on**. Then the program **does not** run the small AI router and sends you **straight to System**. |
| **open plus known site → yes** | You said **open** together with a known site name. Same as above: **straight to System** without the AI router. |
| **system and score over 0.6 → yes** | The AI router thinks the line is a **system** task and is **confident enough**. |
| **Otherwise** | Goes to the **chat** model for a normal answer. |

---

## Additional flowcharts (aligned with code — thesis / report)

Use these if you need diagrams that match **exact** behaviour: the router **only chooses** System vs Chat (it does **not** parse commands). **`run_system`** is the **same** entry whether routing used **keyword override** or **DeBERTa**. A **session** starts **inside** the system layer when a `_try_*` handler calls `start_*_session`, not in the router.

### Figure A — One round of `main` (idle → listen → route → act → speak → loop or exit)

```mermaid
flowchart TB
    START([Start of round])
    IDLE{Idle timeout message<br/>from last session?}
    IDLESPEAK[Speak idle notice TTS]
    REC[Record mic ASR]
    TXT[English transcript]

    SKIP{pending_system_confirmation<br/>OR session_active?}
    KW{open + known site name?<br/>YouTube ChatGPT Maps Wikipedia News}
    ZS[Zero-shot classify<br/>system vs chat]
    TH{top label system AND<br/>confidence greater than 0.6?}

    SYS[run_system same function<br/>always]
    LLM[run_llm]
    TTS[speak reply]
    LOOP{session or pending<br/>after TTS?}
    AGAIN([Next round])
    EXIT([Exit program])

    START --> IDLE
    IDLE -->|yes| IDLESPEAK
    IDLE -->|no| REC
    IDLESPEAK --> REC
    REC --> TXT
    TXT --> SKIP
    SKIP -->|yes forces system| SYS
    SKIP -->|no| KW
    KW -->|yes forces system| SYS
    KW -->|no| ZS
    ZS --> TH
    TH -->|yes| SYS
    TH -->|no| LLM
    SYS --> TTS
    LLM --> TTS
    TTS --> LOOP
    LOOP -->|yes| AGAIN
    LOOP -->|no| EXIT
    AGAIN --> START
```

**Notes for Figure A**

- **Skip router** covers **both** “waiting for yes/no” **and** “session already on” — same forced **system** route.
- **Keyword path** is only: word **open** + regex site match in `Router/router_layer.py` — not the word “system” and not “automation” as a keyword.
- **Each round** = one recording → one transcript → one `run_system` or one LLM call (not continuous background ASR).

---

### Figure B — Router only: routing decision (no command extraction)

```mermaid
flowchart TB
    IN[English transcript from ASR]

    Q1{Skip entire router?}
    Q1N[No]
    Q2{open AND site pattern match?}
    Q3[Run DeBERTa zero-shot<br/>labels system chat]
    Q4{system AND score over 0.6?}

    OUT_SYS[Output route_system True]
    OUT_CHAT[Output route_system False]

    IN --> Q1
    Q1 -->|pending confirm or session| OUT_SYS
    Q1 -->|otherwise| Q1N
    Q1N --> Q2
    Q2 -->|yes keyword override| OUT_SYS
    Q2 -->|no| Q3
    Q3 --> Q4
    Q4 -->|yes| OUT_SYS
    Q4 -->|no| OUT_CHAT
```

**Notes for Figure B**

- The router returns **only** a **route** plus scores. **Parsing** “search for …”, “open youtube”, timers, etc. happens **later** in **`system_layer`** / **`session_ops`**.

---

### Figure C — `run_system`: where command parsing happens (two modes)

```mermaid
flowchart TB
    RS[run_system voice_lang text]
    EMPTY{text empty?}
    SESS{session_active?}

    ST[run_session_turn<br/>flexible normalize<br/>match stop phrase<br/>match site command<br/>Playwright or WhatsApp action]
    NORM[normalize for one-shot]
    DISPATCH[ordered _try_ chain<br/>first match wins<br/>may start session via start_*_session]
    OUT[Return reply and metadata to main]

    RS --> EMPTY
    EMPTY -->|yes| OUT
    EMPTY -->|no| SESS
    SESS -->|yes| ST --> OUT
    SESS -->|no| NORM --> DISPATCH --> OUT
```

**Notes for Figure C**

- **Keyword router** and **DeBERTa router** both land on **the same** `run_system` box — there is **no** separate “keyword → automation only” entry.
- **Session** begins when a **one-shot** handler successfully calls e.g. `start_youtube_session` **inside** `_dispatch` (not in the router).
- **Next** user utterance: `session_active()` is true → **`run_session_turn`** path until **stop** or **idle timeout**.

---

## What “command extraction” means here (plain words)

**Path B — no session yet**

1. **Clean the text** so the same idea with different punctuation still looks the same (lowercase, spaces fixed, most symbols removed).
2. **Pattern matching** means the program looks for phrases it knows, in a **fixed order** (for example timer before “open website”). The first pattern that fits is the one that runs.
3. **Pull out the important words** from the sentence (for example the part after “search the web for …” or “open youtube and …”).
4. If you tried to open an **unknown app name**, it may **guess** a close name and **ask you to confirm** yes or no.

**Path A — session already on**

1. **Softer cleaning** — removes filler words like “please” so “please search cats” and “search cats” behave the same.
2. **Match commands** for that mode (YouTube uses different rules than ChatGPT / Wikipedia / Maps / News). It looks for **search** plus the rest of the line, or **type** …, **pause**, **play first**, **stop**, and similar.
3. If you started from a phrase like “open YouTube for cats”, the program may first open YouTube then run an internal line like **search cats** so the matcher gets a clear command.

---

## What the System can do in this project (checklist)

| Area | What it covers |
|------|------------------|
| **Time** | Timer and alarm using the Windows Clock app (with limits on how perfect it is) |
| **Time readout** | Say the current time or date |
| **Web** | Open a normal website list, open a link you say, search Google in the browser, open the first DuckDuckGo result in some cases |
| **Screenshots** | Save a picture of the screen |
| **Media key** | Play/pause style command for the active player |
| **Clipboard** | Copy and paste shortcuts |
| **Folders** | Open Downloads Documents Desktop and similar under your user folder |
| **Apps** | Open a known desktop app from a safe list |
| **Paths** | Open a file path if it is allowed and exists |
| **Automation in Edge** | YouTube ChatGPT Wikipedia Google Maps Google News — needs Edge **already running with remote debugging**; the program **connects** to it (it does not have to start a new browser) |
| **WhatsApp** | Opens WhatsApp desktop; only simple typing and sending |

---

## After System: how voice comes out

- **System** only returns **text** to say.
- **main.py** always sends that text to **text-to-speech** in the same **round**, using the language you chose at the start.
- If a **long idle** ended the session, a **one-time message** may be spoken at the **beginning of the next round** before it listens again.

---

## Loop: when the program listens again

- If a **session** is still on or it is **waiting for your yes/no**, the app **stays in the loop** and the next recording goes **straight to System** (router skipped).
- Otherwise it often **ends** after one full round.

---

## File map (for developers)

| Part | File |
|------|------|
| Main loop | `main.py` |
| System or chat routing | `Router/router_layer.py` |
| One-shot commands and starting sessions | `System/system_layer.py` |
| Session commands and stop | `System/session_ops.py` |
| Connect to Edge | `System/browser_control.py` |
| Clicks and typing per site | `System/Automation/*.py` |
