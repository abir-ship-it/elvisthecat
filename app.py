# deep_research_reddit.py (stateful, single-zip download, empty prompt override)
# Streamlit assistant for genre-based Reddit deep research tailored for screen-writers and producers.

import os, json, time, random, io, zipfile
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
        if pwd == "abir":
            st.session_state["authenticated"] = True
            st.rerun()
            st.stop()
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

# ── ENV / KEYS 4 keys, fourth placeholder───────────────────────────────────────────────────────
load_dotenv()
openai.api_key        = os.getenv("OPENAI_API_KEY", "")
REDDIT_CLIENT_ID      = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET  = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT     = os.getenv("REDDIT_USER_AGENT", "DeepResearch/0.1")

if not all([openai.api_key, REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET]):
    st.error("🚨 Set your OpenAI & Reddit credentials via env-vars or a .env file.")
    st.stop()

# ── REDDIT CLIENT ────────────────────────────────────────────────────────────
reddit = praw.Reddit(
    client_id=REDDIT_CLIENT_ID,
    client_secret=REDDIT_CLIENT_SECRET,
    user_agent=REDDIT_USER_AGENT,
)

# ── Helpers ──────────────────────────────────────────────────────────────────
### This is default. This can be overridden on the streamlit app.
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

## Fetches the threads from Sub Reddit as decided by the slider and the string
def fetch_threads(sub: str, limit: int, timer_cb: Callable[[], None]) -> List[Dict]:
    threads = []
    ## The limit variable is populated by the slider using "st.slider" in line : 170 ish
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

## Each of these the threads fetched from Reddit might be in a weird form. We need to summarize them so that i can be fit into the final prompt
## in the future, iff OpenAI comes up with a model with unlimited context , we may not need to summarise the thread
## also, its a matter of cost. If we use O3 for everything, cost will be a concern.

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
        resp = openai.chat.completions.create(model=model, messages=msgs) ### If openAI is deprecating 4o, you have the change the model here.
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

## Once you have all the summaries, the questions, this is the final prompt that generates the report.
## Input are the topic, summarized threads, questions.
## There are two options, 1) Either user can use the default prompt in the box Custom report prompt (override)
##  or can override it from the app and it takes effect in line :156
## 
def generate_report(genre: str, threads: List[Dict], questions: List[str], user_prompt: str, timer_cb: Callable[[], None]) -> str:
    corpus = "\n\n".join(
        f"{t['title']} – {t['summary'].get('gist','')} [URL]({t['url']})" for t in threads
    )[:15000]

    q_block = "\n".join(f"Q{i+1}. {q}" for i, q in enumerate(questions))

    # If user_prompt is empty, use the original default prompt verbatim
    if not user_prompt.strip():
        prompt = (
            "You are a senior analyst and researcher assisting business executives who are exploring the "
            f"**{genre.title()}** topic. You have mined Reddit community and audience discussions. "
            "First, give a one-paragraph snapshot of overall audience sentiment for this topic. "
            "Then, answer each research question in its own subsection (≤2 paragraphs each), "
            "adding citations in [Title](URL) form right after every key evidence point. "
            "Finish with a bold **list of ACTIONABLE INSIGHTS** lists 3 points for business executives (what to emphasise / avoid in a script), each with a citation."
        )
    else:
        ## This prompt is used if the user overrides in the Streamlit UI
        prompt = f"You are doing research on: **{genre.title()}** topic. " + user_prompt.strip()

    msgs = [
        {"role": "system", "content": prompt},
        {"role": "assistant", "content": f"CORPUS ({len(threads)} threads):\n{corpus}"},
        {"role": "user", "content": q_block},
    ]
    ## Make the call to the Open AI chat completions endpoint.
    ## if they deprecate change line :165
    resp = openai.chat.completions.create(model="gpt-4o", messages=msgs)
    timer_cb()
    return resp.choices[0].message.content

# ── UI ──────────────────────────────────────────────────────────────────────
## This is where streamlit magic comes from. St.title creates a title
st.title("Generalized Reddit Extractor & Analytics")

ticker = st.sidebar.empty()
start_time = time.time()

## clock you see on the left hand side
def tick():
    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    ticker.write(f"⏱️ {mins:02d}:{secs:02d}")

col1, col2 = st.columns([2, 1])
with col1:
    genre_input = st.text_input(" enter the topic you want to research about", value="horror").strip().lower()
with col2:
    n_posts = st.slider("Threads", 10, 200, 50, step=10) ## This information is used to decide the number of reddit threads to fetch

subreddit = st.text_input("Subreddit", value="horror").strip()

st.markdown("#### Research questions (1-5, one per line)")
qs_text = st.text_area("Questions", "What tropes feel over-used?\nWhat excites this audience?", label_visibility="collapsed")
questions = [q.strip() for q in qs_text.splitlines() if q.strip()][:5]

# Empty prompt override (no default text shown)
st.markdown("#### Custom report prompt (override)")
custom_prompt= "You are a senior analyst and researcher assisting business executives who are exploring the topic mentiond here \n"+ "You have mined Reddit community and audience discussions. \n" + "First, give a one-paragraph snapshot of overall audience sentiment for this topic. \n" + "Then, answer each research question in its own subsection (≤2 paragraphs each),\n "
custom_prompt +=  "adding citations in [Title](URL) form right after every key evidence point. \n"
custom_prompt += "Finish with a bold **list of ACTIONABLE INSIGHTS** lists 3 points for business executives (what to emphasise / avoid in a script), each with a citation."
user_prompt_input = st.text_area(
    "Write your own instructions for how to craft the final report.",
    value= custom_prompt,
    height=180,
)

# ── Run pipeline and persist to session state ───────────────────────────────
## Next line creates a button
run_clicked = st.button("Run research 🚀")

## Below we do a series of validations.
if run_clicked:
    if not subreddit:
        st.error("Please specify a subreddit.")
        st.stop()
    if not questions:
        st.error("Enter at least one research question.")
        st.stop()

    ## Standard error validation for missing subreddits, questions boxes

    with st.spinner("⛏️ Fetching threads + comments…"):
        raw_threads = fetch_threads(subreddit, n_posts, tick)
        threads = json.loads(json.dumps(raw_threads))  # safe copy for summaries

    progress = st.progress(0.0)
    status = st.empty()
    sample_preview = st.empty()
    with st.spinner("📝 Summarizing…"):
        summarise_threads(threads, progress, status, sample_preview, tick)

    with st.spinner("🧠 Crafting final report…"):
        report_md = generate_report(genre_input, threads, questions, user_prompt_input, tick)

    ## streamlit user interface ends here, below this is code to download the report.
    ## So once, the report is generated, Streamlit will lose context and memory, so, we are asking streamlit to preserve the content
    ## And if the user wants to download, the raw json from reddit + final report can be zipped and downloaded. 
    # Persist results to session so a rerun (e.g., after download) does NOT lose state
    st.session_state["raw_threads"] = raw_threads
    st.session_state["threads"] = threads
    st.session_state["report_md"] = report_md
    st.session_state["subreddit_val"] = subreddit
    st.session_state["genre_val"] = genre_input

# ── Render results if present in state ───────────────────────────────────────
if "report_md" in st.session_state and "threads" in st.session_state:
    st.success(f"Summarized {len(st.session_state['threads'])} threads from r/{st.session_state['subreddit_val']}.")
    with st.expander("🔍 Gists & insights"):
        st.json([
            {"title": t["title"], **t.get("summary", {}), "url": t["url"]}
            for t in st.session_state["threads"]
        ])

    st.markdown("## 📊 Audience-Driven Report")
    st.markdown(st.session_state["report_md"])

    ## Downloading a zip file instead of two files.
    # Build a ZIP containing both files for a single-button download
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_name = f"reddit_{st.session_state['subreddit_val']}_{ts}.json"
    md_name = f"report_{st.session_state['genre_val']}_{ts}.md"

    reddit_json_str = json.dumps(st.session_state["raw_threads"], ensure_ascii=False, indent=2)

    ## Below is the code to combine both (final report + raw reddit json) into one .zip file 
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(json_name, reddit_json_str)
        zf.writestr(md_name, st.session_state["report_md"])
    zip_buffer.seek(0)

    st.markdown("---")
    st.subheader("⬇️ Download results")
    st.download_button(
        label="Download JSON + Markdown (.zip)",
        data=zip_buffer.getvalue(),
        file_name=f"reddit_research_{ts}.zip",
        mime="application/zip",
    )

    tick()
