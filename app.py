# deep_research_reddit.py
# ─────────────────────────────────────────────────────────────────────────────
# Streamlit assistant for genre‑based Reddit deep research tailored for
# screen‑writers and producers. /rs/blob/main/app.py
# ─────────────────────────────────────────────────────────────────────────────

import os, json, time, random
from datetime import datetime, timezone
from typing import List, Dict, Callable

import streamlit as st
from dotenv import load_dotenv
import openai
import praw

# ── PASSWORD PROTECTION ─────────────────────────────────────────────────────
st.set_page_config(page_title="Reddit Research", layout="centered")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    pwd = st.text_input("Password (just press enter)", type="password")
    if st.button("Submit"):
        if pwd == "abir" or pwd == "" or True:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

# ── CSS: Verdana 14 pt everywhere ────────────────────────────────────────────
st.markdown(
    """
    <style>
    html, body, [class*="css"], .stMarkdown, .stTextInput, .stButton, .stSlider label {
        font-family: Verdana, sans-serif !important;
        font-size: 14px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── ENV / KEYS ───────────────────────────────────────────────────────────────
load_dotenv()
openai.api_key        = os.getenv("OPENAI_API_KEY", "")
REDDIT_CLIENT_ID      = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET  = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT     = os.getenv("REDDIT_USER_AGENT", "DeepResearch/0.1")

if not all([openai.api_key, REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET]):
    st.error("🚨 Set your OpenAI & Reddit credentials via env‑vars or a .env file.")
    st.stop()

# ── REDDIT CLIENT ────────────────────────────────────────────────────────────
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT,
)

# ── Helpers ──────────────────────────────────────────────────────────────────
GENRE_DEFAULT_SUB = {
    "horror": "horror",
    "sci-fi": "scifi",
    "rom-com": "romcom",
    "superhero": "marvelstudios",
    "documentary": "documentaries",
    "animation": "animation",
    "crime": "TrueFilm",
    "thriller": "Thrillers",
}

def fetch_threads(sub: str, limit: int, timer_cb: Callable[[], None]) -> List[Dict]:
    threads = []
    for post in reddit.subreddit(sub).new(limit=limit):
        post.comments.replace_more(limit=None)
        comments = " ".join(c.body for c in post.comments.list())
        threads.append({
            "id": post.id,
            "title": post.title,
            "body": post.selftext or "",
            "comments": comments,
            "url": post.url,
            "created": datetime.fromtimestamp(post.created_utc, tz=timezone.utc).strftime("%Y-%m-%d"),
        })
        timer_cb()
    return threads

def summarise_threads(threads: List[Dict], progress_bar, status_slot, sample_slot, timer_cb: Callable[[], None], model: str = "gpt-4o", batch: int = 6) -> None:
    total = len(threads)
    done = 0
    for i in range(0, total, batch):
        chunk = threads[i:i + batch]
        payload = {
            t["id"]: f"{t['title']}\n\n{t['body'][:4000]}\n\nComments:\n{t['comments'][:6000]}"
            for t in chunk
        }
        status_slot.markdown(f"**Summarising:** {chunk[0]['title'][:80]}…")
        sample_thread = random.choice(threads)
        sample_slot.markdown(f"*Random thread:* **{sample_thread['title'][:90]}**")

        msgs = [
            {
                "role": "system",
                "content": (
                    "Summarize the Reddit thread. Extract atleast 2 key insights and assess overall sentiment (positive/negative/neutral/mixed). Focus on main discussion points and community mood. Output JSON . For each Reddit thread JSON {id:text} return JSON with keys "
                    "gist (50 words), insight1, insight2, sentiment (positive/neutral/negative)."
                ),
            },
            {"role": "user", "content": json.dumps(payload)},
        ]
        resp = openai.chat.completions.create(model=model, messages=msgs)
        summaries = {}
        try:
            summaries = json.loads(resp.choices[0].message.content)
        except Exception:
            print("Json exception")
        for t in chunk:
            t["summary"] = summaries.get(t["id"], {})
        done += len(chunk)
        progress_bar.progress(done / total)
        timer_cb()
        time.sleep(0.5)
    status_slot.markdown("**Summarising complete!**")

# UPDATED: generate_report now accepts a system_prompt argument

def generate_report(genre: str, threads: List[Dict], questions: List[str], timer_cb: Callable[[], None], system_prompt: str) -> str:
    corpus = "\n\n".join(
        f"{t['title']} – {t['summary'].get('gist','')} [URL]({t['url']})" for t in threads
    )[:15000]

    q_block = "\n".join(f"Q{i+1}. {q}" for i, q in enumerate(questions))

    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": f"CORPUS ({len(threads)} threads):\n{corpus}"},
        {"role": "user", "content": q_block},
    ]
    resp = openai.chat.completions.create(model="gpt-4o", messages=msgs)
    timer_cb()
    return resp.choices[0].message.content

# ── UI ──────────────────────────────────────────────────────────────────────
st.title("generalized reddit data extractor & analytics")

ticker = st.sidebar.empty()
start_time = time.time()

def tick():
    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    ticker.write(f"⏱️ {mins:02d}:{secs:02d}")

col1, col2 = st.columns([2, 1])
with col1:
    genre_input = st.text_input("Film/TV genre or enter the topic you want to research about", value="horror").strip().lower()
with col2:
    n_posts = st.slider("Threads", 10, 200, 50, step=10)

subreddit = st.text_input("Subreddit", value="horror").strip()

st.markdown("#### Research questions (1‑5, one per line)")
qs_text = st.text_area("Questions", "What tropes feel over‑used?\nWhat excites this audience?", label_visibility="collapsed")
questions = [q.strip() for q in qs_text.splitlines() if q.strip()][:5]

# NEW: Custom prompt override UI + fallback to original default when empty
st.markdown("#### Custom report prompt (override)")
DEFAULT_SYSTEM_PROMPT = (
    "You are a senior analyst and researcher assisting business executives who are exploring the "
    f"**{genre_input.title()}** topic. You have mined Reddit community and audience discussions. "
    "First, give a one‑paragraph snapshot of overall audience sentiment for this topic. "
    "Then, answer each research question in its own subsection (≤2 paragraphs each), "
    "adding citations in [Title](URL) form right after every key evidence point. "
    "Finish with a bold **list of ACTIONABLE INSIGHTS** lists 3 points for business executives (what to emphasise / avoid in a script), each with a citation."
)
custom_prompt_text = st.text_area(
    "Write your own instructions for how to craft the final report (leave blank to use the default).",
    value="",
    height=140,
)

if st.button("Run research 🚀"):
    if not subreddit:
        st.error("Please specify a subreddit.")
        st.stop()
    if not questions:
        st.error("Enter at least one research question.")
        st.stop()

    with st.spinner("⛏️ Fetching threads + comments…"):
        # Save raw payload for download (pre-summaries)
        raw_threads = fetch_threads(subreddit, n_posts, tick)
        # Work on a copy for summarization/reporting
        threads = json.loads(json.dumps(raw_threads))

    progress = st.progress(0.0)
    status = st.empty()
    sample_preview = st.empty()
    with st.spinner("📝 Summarizing…"):
        summarise_threads(threads, progress, status, sample_preview, tick)

    st.success(f"Summarized {len(threads)} threads from r/{subreddit}.")
    with st.expander("🔍 Gists & insights"):
        st.json([{"title": t["title"], **t.get("summary", {}), "url": t["url"]} for t in threads])

    # Resolve final system prompt now
    if custom_prompt_text.strip():
        system_prompt = f"You are doing research on: **{genre_input.title()}** topic. " + custom_prompt_text.strip()
    else:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    with st.spinner("🧠 Crafting final report…"):
        report_md = generate_report(genre_input, threads, questions, tick, system_prompt)

    st.markdown("## 📊 Audience‑Driven Report")
    st.markdown(report_md)

    # Downloads should appear ONLY after the report is generated
    st.markdown("---")
    st.subheader("⬇️ Downloads")
    reddit_json_str = json.dumps(raw_threads, ensure_ascii=False, indent=2)
    st.download_button(
        label="Download Reddit response (JSON)",
        data=reddit_json_str,
        file_name=f"reddit_{subreddit}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
    )
    st.download_button(
        label="Download final report (.md)",
        data=report_md,
        file_name=f"report_{genre_input}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown",
    )

    tick()
