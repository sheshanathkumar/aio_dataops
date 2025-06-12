import json, re, time
import requests
import streamlit as st

# --- Streamlit UI Setup ---
st.set_page_config(page_title="Log Chatbot", page_icon="💬")
st.title("🔍 AIO DataOps")

# Initialize session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "input" not in st.session_state:
    st.session_state.input = ""

# --- Constants ---
LLM_API_URL = "https://api.groq.com/openai/v1/chat/completions"
LLM_API_KEY = st.secrets["GROQ_API_KEY"] if "GROQ_API_KEY" in st.secrets else "your-fallback-api-key"
LLM_MODEL = "llama3-70b-8192"

# --- Log Loading ---
json_logs = []
text_logs = []

def load_logs():
    global json_logs, text_logs
    try:
        with open("logs/structured_logs.json", "r") as f:
            json_logs = json.load(f)
    except Exception as e:
        st.warning(f"Error loading JSON logs: {e}")

    try:
        with open("logs/plain_logs.log", "r") as f:
            text_logs = parse_text_logs(f.readlines())
    except Exception as e:
        st.warning(f"Error loading plain logs: {e}")

def parse_text_logs(lines):
    parsed = []
    for line in lines:
        m = re.match(r"\[JobID: (.*?)\] .*?Status: (.*?) \| Source: (.*?) \| Timestamp: (.*?)$", line.strip())
        if m:
            job_id, status, source, timestamp = m.groups()
            parsed.append({
                "job_id": job_id,
                "status": status,
                "source": source,
                "timestamp": timestamp,
                "log": line.strip()
            })
    return parsed

# --- Query Bot Function ---
def query_bot(question):
    logs_summary = "\n".join([
        f"JobID: {log['job_id']}, Status: {log['status']}, Source: {log['source']}, Timestamp: {log['timestamp']}, Log: {log.get('log', '')[:100]}"
        for log in (json_logs + text_logs)[-50:]
    ])

    prompt = f"""
You are a helpful assistant analyzing job logs.
Logs:
{logs_summary}

User question: {question}
Answer in natural language:
"""

    try:
        start_time = time.time()
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}]
        }
        response = requests.post(LLM_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        elapsed_time = round(time.time() - start_time, 2)
        return result.get("choices", [{}])[0].get("message", {}).get("content", "No answer generated.") + f"\n\n⏱️ Response in {elapsed_time}s"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# --- Load Logs (on app load) ---
load_logs()

with st.form("chat_form", clear_on_submit=True):
    user_input = st.text_input("Ask about the logs:", key="chat_input")
    submitted = st.form_submit_button("Send")

if submitted and user_input:
    st.session_state.chat_history.append(("user", user_input))
    with st.spinner("Analyzing logs..."):
        response = query_bot(user_input)
    st.session_state.chat_history.append(("bot", response))

# --- Display Chat History ---
for sender, message in st.session_state.chat_history:
    if sender == "user":
        st.markdown(f"🧑‍💻 **You:** {message}")
    else:
        st.markdown(f"🤖 **Bot:** {message}")
