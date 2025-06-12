import json, re, time
import requests
import streamlit as st

st.set_page_config(page_title="Log Chatbot", page_icon="💬")
st.title("🔍 AIO DataOps")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "input" not in st.session_state:
    st.session_state.input = ""

LLM_API_URL = "https://api.groq.com/openai/v1/chat/completions"
LLM_API_KEY = st.secrets["GROQ_API_KEY"] if "GROQ_API_KEY" in st.secrets else "your-fallback-api-key"
LLM_MODEL = "llama3-70b-8192"

json_logs = []
text_logs = []


def load_logs():
    global json_logs, text_logs, splunk_logs
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

    try:
        with open("logs/splunk_pipe.log", "r") as f:
            text_logs = parse_text_logs(f.readlines())
    except Exception as e:
        st.warning(f"Error loading plain logs: {e}")


def parse_text_logs(lines):
    parsed_logs = []
    current_multiline_log = None

    def extract_common_fields_from_message(message_text):
        m_common = re.search(r"JobID: ([0-9a-fA-F]+).*?Status: (\w+).*?Source: (\w+)", message_text)
        if m_common:
            return m_common.groups()
        return None, None, None

    for i, line in enumerate(lines):
        line = line.strip()

        if not line:
            if current_multiline_log:
                parsed_logs.append(current_multiline_log)
                current_multiline_log = None
            continue

        # --- Attempt to parse JSON log ---
        if line.startswith('{') and line.endswith('}'):
            try:
                json_data = json.loads(line)
                inner_log_message = json_data.get('log', '')

                # Try to get job_id, status, source from the top-level fields
                job_id = json_data.get("job_id")
                status = json_data.get("status")
                source = json_data.get("source")
                timestamp = json_data.get("timestamp")

                # If any key is missing from the top-level, try to extract from the 'log' message
                if not all([job_id, status, source, timestamp]):
                    j_id, s_status, s_source = extract_common_fields_from_message(inner_log_message)
                    if not job_id: job_id = j_id
                    if not status: status = s_status
                    if not source: source = s_source

                    # For timestamp, if top-level is missing, regex it directly from the inner_log_message
                    if not timestamp:
                        ts_match = re.search(r"Timestamp: ([\d-]{10}T[\d:]{8}(?:\.\d{3,6})?[\+\-]\d{2}(?::\d{2})?)",
                                             inner_log_message)
                        if ts_match:
                            timestamp = ts_match.group(1)

                log_entry = {
                    "log_type": "JSON",
                    "job_id": job_id,
                    "status": status,
                    "source": source,
                    "timestamp": timestamp,
                    "full_log": line  # Store the original full line
                }
                parsed_logs.append(log_entry)
                current_multiline_log = None  # Reset multi-line tracking
                continue
            except json.JSONDecodeError:
                # Not a valid JSON, try other formats
                pass

        splunk_match = re.match(
            r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[\+\-]\d{2}:\d{2})\s+"  # Timestamp
            r".*?job_id=(?P<job_id>[0-9a-fA-F]+)\s+"  # job_id
            r"source=(?P<source>\w+)\s+"  # source
            r"status=(?P<status>\w+)\s+"  # status
            r"(?:error_type=(?P<error_type>\"[^\"]+\")\s+)?"  # Optional error_type (non-capturing group with ? for optionality)
            r"message=(?P<message>\".*?\")$",  # Message at the end
            line
        )
        if splunk_match:
            data = splunk_match.groupdict()
            log_entry = {
                "log_type": "Splunk-like",
                "job_id": data['job_id'],
                "status": data['status'],
                "source": data['source'],
                "timestamp": data['timestamp'],
                "error_type": data['error_type'].strip('"') if data['error_type'] else None,  # Clean quotes
                "message": data['message'].strip('"') if data['message'] else None,  # Clean quotes
                "full_log": line  # Store the original full line
            }
            # If status is FAILED, we anticipate a stack trace
            if log_entry['status'] == "FAILED":
                current_multiline_log = log_entry  # Set for multi-line capture
            else:
                current_multiline_log = None  # Reset if not a FAILED status

            parsed_logs.append(log_entry)
            continue

        # --- Attempt to parse Custom Plain Text log (starts with [JobID: ...]) ---
        # Matches: [JobID: ...] Execution completed/failed/Status update | Status: ... | Source: ... | Timestamp: ...
        custom_match = re.match(
            r"^\[JobID: (?P<job_id>[0-9a-fA-F]+)\].*?Status: (?P<status>\w+)\s*\|\s*Source: (?P<source>\w+)\s*\|\s*Timestamp: (?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3,6})?)",
            line
        )
        if custom_match:
            data = custom_match.groupdict()
            log_entry = {
                "log_type": "Custom-Plain",
                "job_id": data['job_id'],
                "status": data['status'],
                "source": data['source'],
                "timestamp": data['timestamp'],
                "full_log": line  # Store the original full line
            }
            # Start tracking for potential multi-line stack trace
            current_multiline_log = log_entry
            parsed_logs.append(log_entry)
            continue

        if current_multiline_log:
            # Check if it's clearly a stack trace line
            if re.match(r"^\s+(at|\.\.\.)\s+", line) or line.startswith("Caused by:"):
                # Append to the 'full_log' of the current multi-line entry
                current_multiline_log['full_log'] += "\n" + line
                # Keep current_multiline_log active for more lines
                continue
            else:
                current_multiline_log = None  # Reset multi-line tracking

    if current_multiline_log:
        parsed_logs.append(current_multiline_log)

    return parsed_logs


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
        return result.get("choices", [{}])[0].get("message", {}).get("content",
                                                                     "No answer generated.") + f"\n\n⏱️ Response in {elapsed_time}s"
    except Exception as e:
        return f"❌ Error: {str(e)}"


load_logs()

with st.form("chat_form", clear_on_submit=True):
    user_input = st.text_input("Ask about the logs:", key="chat_input")
    submitted = st.form_submit_button("Send")

if submitted and user_input:
    st.session_state.chat_history.append(("user", user_input))
    with st.spinner("Analyzing logs..."):
        response = query_bot(user_input)
    st.session_state.chat_history.append(("bot", response))

for sender, message in reversed(st.session_state.chat_history):
    st.markdown("<hr style='margin-top:10px; margin-bottom:10px;'>", unsafe_allow_html=True)
    if sender == "user":
        st.markdown(f"🧑‍💻 **You:** {message}")
    else:
        st.markdown(f"🤖 **Bot:** {message}")
