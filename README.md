# Shalim (शालिम) - Resilient Local Topology Network

Shalim is a decentralized, offline-first knowledge redundancy platform designed to preserve and navigate local community skill structures during severe internet outages. It runs on local Wi-Fi hotspots, 5G nodes, or peer-to-peer LoRa mesh networks to guarantee community resilience and continuity.

Developed at the **Encode Vibe Coding Hackathon (London, June 2026)**.

---

## 🗺️ Core System Concept

Shalim maps a physical topology of your local community based on skills acquisition and resource sharing. In the event of a crisis, conflict, or internet outage, Shalim ensures communities can coordinate vital resources and skills without relying on global web services.

*   **Offline-First**: Operates seamlessly over low-bandwidth LoRa mesh nodes or isolated local Wi-Fi routers.
*   **Encourages Physical Connection**: Completely strips out instant messaging to prevent spam, scams, and digital stalking. To connect, users must schedule physical meetups at verified hub addresses.
*   **Privacy-Centric**: Strictly controls profile browsing. Members can only find profiles recommended by the AI semantic layer; raw profile database browsing is completely restricted.

---

## 🧠 Core AI Layers

Shalim implements two distinct AI models tailored to operate locally on low-resource hardware:

### 1. TinyCensor (RoBERTa Classifier)
*   **Purpose**: Real-time safety audit and content vetting.
*   **Functionality**: Monitors user queries, added resource names, and meeting request details to detect problematic topics (weapons, explosives, illegal activity).
*   **The Fail-Safe Mechanism**: If a Hub's local TinyCensor node goes offline or fails an audit, the entire Hub is flagged. Once a hub is flagged, all its members are immediately demoted to **Guest** status across the entire network topology.

### 2. AI Query Layer (Qwen2.5-1.5B Model)
*   **Resource to Skill Collation**: Scans raw unstructured datasets (e.g. library book databases, tool shed inventories) and automatically derives acquired skills for the community members who interact with them.
*   **Natural Language Matchmaking**: Accepts naturalistic search queries (e.g., *"I am trying to set up a small permaculture garden on my flat's balcony, who can teach me?"*) and recommends matching member profiles.
*   **Radius Routing**: If no matching skills are found within a member's active hub, Qwen searches surrounding hubs within a 5-10 mile radius and recommends them.

---

## 🔒 Permission & Roles Registry

To ensure local security and protect vulnerable users, Shalim enforces strict role-based access:

| Role | Browse Directory | AI Semantic Search | Meetup Requests | Demotion Trigger |
| :--- | :--- | :--- | :--- | :--- |
| **Hub Admin** | Full visibility of all hub members. | Yes | Yes (Approve/Decline) | N/A |
| **Hub Member** | Restricted (No directory access). | Yes | Limited to recommended profiles. | Demoted to guest if home hub is flagged. |
| **Guest / Under-18** | Restricted. | No | Restricted to Hub Admin only. | Under-18s are permanently Guests. |

---

## 🛠️ Technology Stack
*   **Backend**: FastAPI, Python 3, SQLite
*   **AI Integration**: Hugging Face Transformers (`distilroberta`, `Qwen2.5-1.5B`) with smart keyword-semantic fallback for offline/CPU environments.
*   **Frontend**: HTML5, Vanilla CSS, and JavaScript. Optimized for quick load times and high-contrast styling (Solar-punk aesthetic).

---

## 🚀 Setting Up & Running Locally

### 1. Prerequisites
Ensure you have Python 3 and Node.js (npm) installed.

### 2. Initialize Virtual Environment
```bash
cd Vibe_coding_Hackathon_event_2026
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt   # Or pip install torch transformers fastapi uvicorn huggingface_hub
```

### 3. Run the Development Server
```bash
# Runs uvicorn with hot-reload active
./venv/bin/uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

### 4. Open the Interface
Navigate to **[http://localhost:8000](http://localhost:8000)** in your browser.

---

## 🧪 Interactive Walkthrough Guides
1.  **Semantic Match**: Log in as `bob_builder` and type *"I need solar panel setup"* to see Qwen recommend members or surrounding hubs.
2.  **Add Resources**: Switch to `alice_admin` and add a new book (e.g. *"First Aid Manual"*). Watch the AI collate it into skills.
3.  **Simulate Comms Break**: Toggle **TinyCensor AI** to "Offline/Broken". Try to perform any action; watch the hub get flagged, and Bob immediately get demoted to a guest.
