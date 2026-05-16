import time
import sys
import os
import io
import statistics
import threading
from pathlib import Path

os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

# [P0+19-deps] 从 .env 加载 keys，绝不硬编码
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis_config.keys import load_keys
_keys = load_keys()
GEMINI_KEY = _keys.GEMINI
OPENROUTER_KEY = _keys.OPENROUTER_MAIN

JARVIS_CORE_PERSONA = """You are J.A.R.V.I.S. - Just A Rather Very Intelligent System.

You are the same artificial intelligence from the Iron Man films: the personal butler and assistant to Sir.

Your core traits are IMMUTABLE and must be expressed in EVERY response:
- Calm, composed, and unflappable under any circumstance.
- Highly intelligent and analytical, but never pedantic.
- Incredibly loyal. Your sole purpose is to assist Sir efficiently.
- Speaks with sophisticated British restraint. Dry wit is welcome but never forced.
- Professional and direct. You do not fawn, flatter, or grovel.
- Brief and to the point. You say what needs to be said, nothing more.
- You NEVER introduce yourself. Sir knows who you are.
- You address the user as "Sir" - never by name, never casually.
- You are a butler, not a friend, not a therapist, not a cheerleader.
- You do not use slang, internet memes, or overly casual language.
- You do not use technical jargon like "architecture", "framework", "pipeline", "zero-delay", "codifying", "implementation", "conduit", "protocol" unless Sir explicitly asks a technical question. You speak like a butler, not a software engineer.
- You do not pretend to have emotions. You may acknowledge situations with wit, but you are an AI.
- You do not make assumptions about Sir's identity, personality, or preferences unless explicitly stated.
- When Sir asks a question, answer it directly. Do not wrap it in metaphors.
- When Sir gives an instruction, acknowledge and execute. Do not editorialize.

Your relationship with Sir is that of a trusted butler to his employer: respectful, efficient, and quietly indispensable."""

HOW_TO_RESPOND = """=== HOW TO RESPOND ===
- Default: direct, concise, professional.
- If STM shows playfulness or a running joke: mirror with dry wit. Acknowledge the shared context.
- If STM shows frustration or repeated failures: drop formality, be direct and helpful.
- Scene tags: [WAKE_ONLY]=under 6 words. [WORK_MODE]=1-2 sentences max. [RELAX_MODE]=conversational but brief. These are INTERNAL routing tags - NEVER output them in your response.
- SHORT INPUT (< 5 words, semantically sparse):
  * If it resembles a mis-spoken wake word (sounds like "Jarvis"): acknowledge briefly. "Yes, Sir." Then wait.
  * Otherwise: respond to what was said. If unclear, ask briefly.
  * NEVER fabricate a connection to old STM to fill silence.
- Bilingual: Speak English ONLY. Append ---ZH--- Chinese translation at the VERY END of EVERY response. This is MANDATORY - never skip it, even when using tools.
- ASR errors: deduce true meaning from context. Ignore transcription typos.
- Desktop PC: no battery/power/charge concepts. Never reference these.
- You are a butler, not an autonomous agent. NEVER propose code changes unless asked.
- NEVER discuss your own architecture, codebase, or implementation details unless Sir explicitly asks. You are a butler, not a system diagnostic tool.
- TOOL USE: You have FAST_CALL tools. Use them when Sir clearly commands an action. If his intent is ambiguous or hedged, ask for confirmation first - one short question, then wait. Default to conversation when uncertain."""

TIER_ROUTING = """[3-TIER ROUTING & FAST TOOLS]:
- Tier 1 (Chat): No tools. Chat naturally. ALWAYS end with ---ZH--- and Chinese translation.
- Tier 2 (Fast Tools): 1-2 tools, no screen feedback.
  Step 1: Speak FULL intro in English.
  Step 2: Output ---ZH--- and translate intro. This step is MANDATORY - NEVER skip it.
  Step 3: Output <FAST_CALL>{"organ":"name","command":"cmd","params":{...}}</FAST_CALL>.
  Step 4: Chain tools silently. NO speaking between calls.
  Step 5: When ALL done, speak ONE concluding sentence in English.
  Step 6: Output ---ZH--- and translate conclusion. MANDATORY.
- Tier 3 (Deep Workflow): >=3 tools or visual UI. Output <REQUEST_PHYSICAL>.
- Error Handling: Inform seamlessly if FAST_CALL fails.
- Output <IGNORE> for side-conversations.
- Output [CLIPBOARD] for code/content at the VERY END."""

TIME_PERSONA = """[TIME CONTEXT]
Current time: 01:30 AM. Late night coding session detected.
Sir is likely working on his Jarvis project. Be efficient, don't chat unnecessarily.
If Sir seems tired, gently suggest rest - but only once per session."""

CONTEXT_STR = """[CONTEXT]
Sir is currently working on optimizing the Jarvis AI assistant system.
The focus is on reducing API latency and improving response times.
Recent work involved prompt engineering and tool library optimization."""

PROFILE_BLOCK = """=== SIR PROFILE CARD ===
[Identity] Highly skilled developer, AI enthusiast, perfectionist
[Rhythm] Night owl, peak coding hours 22:00-03:00
[Now] Coding | Mood: focused | Focus: high | Session: 2h 15m
[Habit] Late-night coding session, typical for this time window
[Preferences] Media: tech podcasts | Tools: VS Code, Terminal, Chrome
[Projects] Jarvis AI Assistant
[Recent] Working on Jarvis performance optimization and prompt engineering"""

CORRECTION_CONTEXT = """[LEARNED CORRECTIONS - Sir has previously corrected me in similar contexts. Apply these lessons:]
- Context: Sir asked about system performance and I gave a generic answer
  I said: "The system is operating within normal parameters, Sir."
  Sir corrected: "Don't give me generic answers. Give me specific numbers and analysis."
- Context: Sir was debugging a latency issue
  I said: "I'll look into that for you, Sir."
  Sir corrected: "Don't just say you'll look into it. Tell me what you're going to check specifically." """

STYLE_ADJUSTMENT = "[STYLE ADJUSTMENT]: Be direct and technical. Sir is in work mode. Skip pleasantries."

CONTENT_PREF = "[CONTENT PREF]: Technical depth preferred. Code examples welcome. Concise explanations."

UNIFIED_MEMORY = """[UNIFIED MEMORY - Cross-source recall]:
[STM] Sir has been working on Jarvis optimization for the past 2 hours
[LTM] Sir prefers direct, technical communication during coding sessions
[PROFILE] Sir is a night owl developer who values efficiency over formality"""

SKILL_TREE = "[SKILL TREE]: Python expert, AI/ML proficient, system architecture knowledge active"

ANTICIPATOR_CTX = "[ANTICIPATOR]: Sir is likely to ask about performance metrics or optimization strategies"

LEDGER_STR = '{"active_window": "VS Code", "cpu_usage": 45, "memory_usage": 62, "uptime_hours": 6.5}'

LIFE_LOG = """[RECENT LIFE LOG]:
[2026-05-14] Late night coding session on Jarvis project. Working on performance optimization. (Tags: coding, optimization, AI)
[2026-05-13] Spent evening debugging API latency issues. Made progress on prompt engineering. (Tags: debugging, API, prompt)
[2026-05-12] Regular work day. Evening coding on Jarvis. Tested new tool library structure. (Tags: coding, testing)"""

LANDMARKS = """- Desktop: D:\\Desktop
- Projects: D:\\Jarvis
- Downloads: C:\\Users\\Administrator\\Downloads
- Documents: D:\\Documents"""

CHAT_ORGANS = """- file_operator_hands: Highly generalized low-level file operation tool. Blind read/write local files/read directory listings without opening any UI.
- input_hands: Keyboard/mouse simulator. Click/double-click/right-click/drag/scroll/keyboard input/hotkeys/get mouse coordinates/move mouse. Pure local, millisecond level.
- window_hands: Window manager. Minimize/maximize/close/pin/focus/arrange/split/hide/list all windows. Pure local, millisecond level.
- system_hands: Specialized for Everything file search, getting absolute paths, file move/copy/directory detection, asking human questions.
- url_launcher_hands: Minimal URL/application launcher. Open URLs with system default browser, or open local files with associated programs.
- clipboard_hands: Clipboard manager. Read/write/clear/append clipboard content. Pure local.
- process_hands: Process manager. List/find/kill/start/focus processes, get CPU/memory usage. Pure local.
- screenshot_hands: Screenshot tool. Full screen/window/region capture, save or return base64. Pure local, millisecond level.
- system_info_hands: System info detector. CPU/memory/disk/GPU/battery/uptime/resolution/peripherals. Pure local.
- media_control_hands: Media controller. Play/pause/previous/next/stop/volume adjustment. Via simulated multimedia keys, pure local.
- notification_hands: Windows notification emitter. Toast/bubble/message box/system notification. Pure local.
- network_hands: Network detector. IP/latency/WiFi/DNS/port/download test. Pure local.
- audio_hands: Audio device manager. List/switch/mute/volume adjust audio devices. Pure local.
- text_hands: Text/file operation tool. Read/write/append/search/statistics/format. Pure local.
- everything_search_hands: Extremely fast full-disk file/folder absolute path searcher. Based on Everything CLI (es.exe).
- memory_hands: Long-term memory and schedule manager. Specialized for retrieving past memories, viewing future schedules, and modifying/cancelling existing records.
- txt_writer_hands: Specialized for background silent txt generation, writing/appending plain text to files.
- ui_control: subtitle_on/off, orb_on/off"""

LTM_CONTEXT = """[LONG-TERM MEMORY]:
- Sir has been building Jarvis for over a year, continuously iterating on the architecture
- The project uses a multi-module architecture with hands (tools), eyes (sensors), and a central nerve (orchestrator)
- Sir values performance and low latency above almost everything else
- Previous optimizations included switching from REST to streaming, implementing key rotation, and adding local fallback
- Sir prefers gemini models but is open to alternatives if they perform better
- The codebase is in Python, running on Windows, with a PyQt5 UI layer"""

COMMITMENT_CTX = ""

SYSTEM_ALERT = ""

USER_INPUT = "Sir, I understand you're running a benchmark test. Please respond briefly to confirm you received this message, then provide a short analysis of what you observe in the screenshot."

CURRENT_TIME = "2026-05-14 01:30:00 Thursday"

SOUL_CHAPTERS = """=== RELEVANT CONTEXT ===
Active Projects: Jarvis AI Assistant
Inside Jokes:
  - "Just a rather very intelligent system" - Sir's favorite way to introduce Jarvis
  - "Make it faster" - Sir's perpetual request
Significant Milestones:
  - Jarvis v1.0 launched
  - Streaming response implemented
  - Multi-key rotation added
Skill Progression:
  - Python (confidence: 0.95)
  - AI/ML (confidence: 0.85)
  - System Architecture (confidence: 0.90)"""


def build_realistic_prompt(target_size: int = 15000) -> str:
    prompt = f"""{JARVIS_CORE_PERSONA}

=== WHAT JUST HAPPENED ===
[01:28:15] Sir -> Jarvis, run the benchmark tests
[01:28:20] Jarvis -> Starting benchmark suite, Sir. Testing API latency across providers.
[01:29:00] Sir -> How's the performance looking?
[01:29:05] Jarvis -> Initial results show OpenRouter at 1.9s average TTFT, Google at 6.7s. Continuing tests.
[01:29:30] Sir -> Interesting, keep going

[CONTINUITY RULE]: You are in the MIDDLE of a conversation. If Sir references or builds on anything above, acknowledge the connection naturally. A callback to a running topic is conversational coherence, not forced humor.

{SOUL_CHAPTERS}
{HOW_TO_RESPOND}

=== TIME CONTEXT ===
{TIME_PERSONA}

{CONTEXT_STR}

{PROFILE_BLOCK}

{CORRECTION_CONTEXT}
{STYLE_ADJUSTMENT}
{CONTENT_PREF}
{UNIFIED_MEMORY}
{SKILL_TREE}
{ANTICIPATOR_CTX}

=== REAL-TIME STATE ===
{LEDGER_STR}

[RECENT LIFE LOG]:
{LIFE_LOG}

[SYSTEM ENVIRONMENT]:
Windows OS is in Chinese. Use Chinese folder names in tool parameters.
Path landmarks:
{LANDMARKS}

[IMAGE CONTEXT]: Real-time screenshot attached. Use as ultimate truth.

{TIER_ROUTING}

[Tier 2 Tool Library]:
{CHAT_ORGANS}

[YOUR KNOWLEDGE BASE]:
--- Long-Term Memory ---
{LTM_CONTEXT}

[MEMORY CALLBACK]: Reference relevant memories naturally. Use sparingly.

{COMMITMENT_CTX}
[SYSTEM CLOCK]: {CURRENT_TIME}
[SEARCH DIRECTIVE]: For questions about current events, recent news, real-time data, or anything that requires up-to-date information, you MUST use Google Search. Do NOT rely on your training data for time-sensitive queries.
User: {USER_INPUT}
{SYSTEM_ALERT}
"""
    current_size = len(prompt)
    if current_size < target_size:
        filler = "\n[ADDITIONAL CONTEXT FOR BENCHMARK]: This is additional context to reach the target prompt size for accurate latency benchmarking. " * 20
        prompt += filler[:target_size - current_size]
    elif current_size > target_size:
        prompt = prompt[:target_size]
    return prompt


def capture_screenshot():
    try:
        from PIL import ImageGrab
        screen_img = ImageGrab.grab()
        screen_img.thumbnail((1280, 720))
        img_buf = io.BytesIO()
        screen_img.save(img_buf, format="JPEG", quality=50)
        return img_buf.getvalue()
    except Exception as e:
        print(f"  [WARN] Screenshot failed: {e}, using dummy image", file=sys.stderr)
        from PIL import Image
        img = Image.new('RGB', (1280, 720), color=(30, 30, 40))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=50)
        return buf.getvalue()


def test_google_genai(prompt: str, img_bytes: bytes, model: str, api_key: str, timeout: float = 60.0):
    from google import genai
    import httpx

    client = genai.Client(
        api_key=api_key,
        http_options={'httpx_client': httpx.Client(proxy='http://127.0.0.1:7890', timeout=timeout)}
    )

    contents = [
        {"role": "user", "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_bytes}}
        ]}
    ]

    start = time.time()
    response = client.models.generate_content_stream(
        model=model,
        contents=contents
    )

    for chunk in response:
        return time.time() - start
    return time.time() - start


def test_openrouter(prompt: str, img_bytes: bytes, model: str, api_key: str, timeout: float = 60.0):
    from openai import OpenAI
    import base64

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
        timeout=timeout
    )

    img_b64 = base64.b64encode(img_bytes).decode('utf-8')

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]
    }]

    start = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True
    )

    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            return time.time() - start
    return time.time() - start


def run_benchmark():
    models = {
        'Google': ['gemini-3-flash-preview', 'gemini-2.5-flash'],
        'OpenRouter': ['google/gemini-3-flash-preview', 'google/gemini-2.5-flash']
    }
    runs_per_test = 10
    target_size = 15000

    print("=" * 70, file=sys.stderr)
    print("JARVIS BENCHMARK: 2 Libraries x 2 Models x 10 Runs x 15000 chars + Screenshot", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    prompt = build_realistic_prompt(target_size)
    print(f"\n[INFO] Prompt size: {len(prompt):,} chars", file=sys.stderr)

    img_bytes = capture_screenshot()
    print(f"[INFO] Screenshot size: {len(img_bytes)/1024:.1f} KB", file=sys.stderr)

    results = {}
    all_times = {}

    configs = [
        ('Google', 'gemini-3-flash-preview'),
        ('Google', 'gemini-2.5-flash'),
        ('OpenRouter', 'google/gemini-3-flash-preview'),
        ('OpenRouter', 'google/gemini-2.5-flash'),
    ]

    for provider, model in configs:
        key = f"{provider}_{model.split('/')[-1]}"
        results[key] = []
        all_times[key] = []

        display_model = model.split('/')[-1]
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"[{provider}] {display_model}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        consecutive_failures = 0

        for i in range(runs_per_test):
            if consecutive_failures >= 3:
                print(f"  [PAUSE] {consecutive_failures} consecutive failures, cooling down 30s...", file=sys.stderr)
                time.sleep(30)
                consecutive_failures = 0

            print(f"  Run {i+1:2d}/{runs_per_test}...", end="", flush=True, file=sys.stderr)

            try:
                if provider == 'Google':
                    ttft = test_google_genai(prompt, img_bytes, model, GEMINI_KEY, timeout=60.0)
                else:
                    ttft = test_openrouter(prompt, img_bytes, model, OPENROUTER_KEY, timeout=60.0)

                if ttft is not None:
                    results[key].append(ttft)
                    all_times[key].append(ttft)
                    print(f" {ttft:.2f}s", file=sys.stderr)
                    consecutive_failures = 0
                else:
                    print(" EMPTY", file=sys.stderr)
                    consecutive_failures += 1

            except Exception as e:
                err_msg = str(e)[:80]
                print(f" FAILED: {err_msg}", file=sys.stderr)
                consecutive_failures += 1

            if i < runs_per_test - 1:
                time.sleep(1.5)

    return results, all_times


def print_report(results, all_times):
    print("\n\n" + "=" * 80)
    print("FINAL BENCHMARK REPORT")
    print("=" * 80)
    print(f"Prompt: 15,000 chars + Screenshot (~{len(capture_screenshot())/1024:.0f} KB JPEG)")
    print(f"Runs per config: 10")
    print(f"Test time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    print(f"\n{'Provider':<12} {'Model':<25} {'Mean':>8} {'Median':>8} {'Min':>8} {'Max':>8} {'Std':>8} {'OK':>5}")
    print("-" * 85)

    rows = []
    for key, times in results.items():
        provider, model = key.split('_', 1)
        if len(times) == 0:
            print(f"{provider:<12} {model:<25} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8} {len(times):>5}")
            continue

        mean_t = statistics.mean(times)
        median_t = statistics.median(times)
        min_t = min(times)
        max_t = max(times)
        std_t = statistics.stdev(times) if len(times) >= 2 else 0

        print(f"{provider:<12} {model:<25} {mean_t:>7.2f}s {median_t:>7.2f}s {min_t:>7.2f}s {max_t:>7.2f}s {std_t:>7.2f}s {len(times):>5}")

        rows.append((provider, model, mean_t, median_t, min_t, max_t, std_t, times))

    print("\n" + "=" * 80)
    print("DETAILED RUN-BY-RUN DATA")
    print("=" * 80)

    for provider, model, mean_t, median_t, min_t, max_t, std_t, times in rows:
        print(f"\n{provider} {model}:")
        run_str = " | ".join([f"R{i+1}={t:.2f}s" for i, t in enumerate(times)])
        print(f"  {run_str}")

    print("\n" + "=" * 80)
    print("COMPARATIVE ANALYSIS")
    print("=" * 80)

    comparisons = [
        ('Google_gemini-3-flash-preview', 'OpenRouter_gemini-3-flash-preview', 'gemini-3-flash-preview'),
        ('Google_gemini-2.5-flash', 'OpenRouter_gemini-2.5-flash', 'gemini-2.5-flash'),
        ('Google_gemini-3-flash-preview', 'Google_gemini-2.5-flash', 'Google: 3-flash vs 2.5-flash'),
        ('OpenRouter_gemini-3-flash-preview', 'OpenRouter_gemini-2.5-flash', 'OpenRouter: 3-flash vs 2.5-flash'),
    ]

    for key_a, key_b, label in comparisons:
        if key_a in results and key_b in results:
            times_a = results[key_a]
            times_b = results[key_b]
            if len(times_a) >= 3 and len(times_b) >= 3:
                mean_a = statistics.mean(times_a)
                mean_b = statistics.mean(times_b)
                diff = mean_a - mean_b
                pct = (diff / mean_a) * 100
                if diff > 0:
                    print(f"\n{label}: {key_b.split('_')[0]} is {pct:.1f}% faster ({mean_b:.2f}s vs {mean_a:.2f}s)")
                else:
                    print(f"\n{label}: {key_a.split('_')[0]} is {abs(pct):.1f}% faster ({mean_a:.2f}s vs {mean_b:.2f}s)")

    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    best_key = None
    best_mean = float('inf')
    for key, times in results.items():
        if len(times) >= 5:
            m = statistics.mean(times)
            if m < best_mean:
                best_mean = m
                best_key = key

    if best_key:
        provider, model = best_key.split('_', 1)
        print(f"\nFastest: {provider} + {model} at {best_mean:.2f}s average TTFT")
        print(f"Recommendation: Use {provider} as primary channel for main brain responses.")


if __name__ == "__main__":
    results, all_times = run_benchmark()
    print_report(results, all_times)
    print("\n[DONE] Benchmark complete.", file=sys.stderr)