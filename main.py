import json, re, time
from datetime import datetime
import pytz
import requests

# Load logs
json_logs = []
text_logs = []


def load_logs():
    global json_logs, text_logs
    try:
        with open("logs/structured_logs.json", "r") as f:
            json_logs = json.load(f)
    except Exception as e:
        print("Error loading JSON logs:", e)

    try:
        with open("logs/plain_logs.log", "r") as f:
            text_logs = parse_text_logs(f.readlines())
    except Exception as e:
        print("Error loading plain logs:", e)


def parse_text_logs(lines):
    parsed = []
    for line in lines:
        m = re.match(r"\[JobID: (.*?)\] .*?Status: (.*?) \| Source: (.*?) \| Timestamp: (.*?)$", line)
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
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3.2",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
        )
        response.raise_for_status()
        result = response.json()
        elapsed_time = time.time() - start_time
        seconds = round(elapsed_time, 2)
        return result.get("message", {}).get("content",
                                             "No answer generated.") + f"\n(Result fetched in {seconds} seconds)"
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    load_logs()
    while True:
        try:
            question = input("\nType your question here (or type 'exit' to quit): ")
            if question.lower() == "exit":
                break
            answer = query_bot(question)
            print(f"\nAnswer: {answer}")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
