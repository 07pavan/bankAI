"""
Live test of the BankAI AI Agent — runs against the local server.
Usage: python test_agent_live.py
"""
import requests
import json
import sys

BASE = "http://localhost:8000/api/v1"

def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def main():
    # Step 1: KYC Submit
    sep("STEP 1: KYC Submission → Get Auth Token")
    resp = requests.post(f"{BASE}/kyc/submit", json={
        "aadhaar": "9876 5432 1098",
        "pan": "FGHIJ5678K"
    })
    print(f"  Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"  Error: {resp.text}")
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token", "")
    print(f"  Token: {'✅ Received' if token else '❌ Missing'}")
    print(f"  User ID: {data.get('user_id', 'N/A')}")

    headers = {"Authorization": f"Bearer {token}"}

    # Step 2: Chat greeting
    sep("STEP 2: Chat — Greeting")
    resp = requests.post(f"{BASE}/conversation/chat",
        json={"message": "Hello! What can you help me with?"},
        headers=headers)
    print(f"  Status: {resp.status_code}")
    chat = resp.json()
    print(f"  Intent: {chat.get('intent', 'N/A')}")
    print(f"  Message: {chat.get('message', 'N/A')[:300]}")

    # Step 3: Ask about forms
    sep("STEP 3: Chat — Ask About Available Forms")
    resp = requests.post(f"{BASE}/conversation/chat",
        json={"message": "What forms are available? I want to open an account"},
        headers=headers)
    print(f"  Status: {resp.status_code}")
    chat = resp.json()
    print(f"  Intent: {chat.get('intent', 'N/A')}")
    print(f"  Message: {chat.get('message', 'N/A')[:400]}")

    # Step 4: Start a submission
    sep("STEP 4: Start Submission (form_id=1)")
    resp = requests.post(f"{BASE}/submissions/start",
        json={"form_id": 1},
        headers=headers)
    print(f"  Status: {resp.status_code}")
    sub = resp.json()
    sub_id = sub.get("id")
    print(f"  Submission ID: {sub_id}")
    print(f"  Submission Status: {sub.get('status')}")

    if not sub_id:
        print("  ❌ Could not create submission")
        sys.exit(1)

    # Step 5: First form field
    sep("STEP 5: Conversation Turn — Answer First Field")
    resp = requests.post(f"{BASE}/conversation/next",
        json={"submission_id": sub_id, "message": "My name is Pavan Hegade"},
        headers=headers)
    print(f"  Status: {resp.status_code}")
    turn = resp.json()
    print(f"  Agent Response: {turn.get('next_question', 'N/A')[:300]}")
    print(f"  Field Key: {turn.get('field_key', 'N/A')}")
    print(f"  Status: {turn.get('status', 'N/A')}")

    # Step 6: Second form field
    sep("STEP 6: Conversation Turn — Answer Second Field")
    resp = requests.post(f"{BASE}/conversation/next",
        json={"submission_id": sub_id, "message": "My date of birth is June 15 1995"},
        headers=headers)
    print(f"  Status: {resp.status_code}")
    turn = resp.json()
    print(f"  Agent Response: {turn.get('next_question', 'N/A')[:300]}")
    print(f"  Field Key: {turn.get('field_key', 'N/A')}")
    print(f"  Status: {turn.get('status', 'N/A')}")

    sep("✅ ALL LIVE TESTS COMPLETE")
    print(f"  Server: http://localhost:8000")
    print(f"  Agent Mode: LLM (xAI Grok) with keyword fallback")
    print()

if __name__ == "__main__":
    main()
