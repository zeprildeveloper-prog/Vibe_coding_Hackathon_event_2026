import os
import threading
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, constr

from database import init_db, get_db_connection
from censor import censor
from query_layer import query_layer

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shalim.app")

# Initialize FastAPI
app = FastAPI(title="Shalim - Knowledge Redundancy App")

# Allow CORS for local frontend testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global flag to simulate TinyCensor health status
censor_working = True

# Threaded AI initialization to start FastAPI instantly
def load_ai_models():
    logger.info("Starting AI models loading in background thread...")
    censor.initialize()
    query_layer.initialize()
    logger.info("AI models loading thread completed.")

@app.on_event("startup")
def startup_event():
    # 1. Initialize SQLite Database
    init_db()
    
    # 2. Start background thread to load AI models
    threading.Thread(target=load_ai_models, daemon=True).start()

# --- Helpers to implement Shalim's strict business rules ---

def get_user_effective_status(conn, user_id: int, hub_id: int) -> str:
    """
    Computes a user's effective membership status in a hub.
    Rules:
      1. Under-18s are ALWAYS guests.
      2. If the user's primary hub is flagged, they are DEMOTED to guest everywhere.
      3. Otherwise, check hub_memberships status.
    """
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return "guest"
        
    # Rule 1: Under 18 are guests
    if user["age"] < 18 or user["is_guest_only"] == 1:
        return "guest"
        
    # Rule 2: Primary hub flagged
    if user["primary_hub_id"]:
        primary_hub = conn.execute("SELECT flagged FROM hubs WHERE id = ?", (user["primary_hub_id"],)).fetchone()
        if primary_hub and primary_hub["flagged"] == 1:
            return "guest" # Demoted!

    # Rule 3: Check specific hub membership status
    membership = conn.execute(
        "SELECT status FROM hub_memberships WHERE user_id = ? AND hub_id = ?",
        (user_id, hub_id)
    ).fetchone()
    
    if membership:
        return membership["status"]
    return "guest" # Default fallback for guests/non-members

def check_tiny_censor_health(conn, source_hub_id: int = None):
    """
    Checks if TinyCensor is working.
    If NOT working, the originating hub is immediately flagged!
    """
    global censor_working
    if not censor_working or not censor.initialized:
        if source_hub_id:
            conn.execute("UPDATE hubs SET flagged = 1 WHERE id = ?", (source_hub_id,))
            conn.commit()
            logger.error(f"TinyCensor failure detected! Hub #{source_hub_id} has been FLAGGED. All members demoted.")
        return False
    return True

# --- API Models ---

class QueryRequest(BaseModel):
    user_id: int
    hub_id: int
    query: str

class MeetingRequestPayload(BaseModel):
    requester_id: int
    receiver_id: int
    hub_id: int
    reason: str # We validate length in the code to return a clean error message

class ResourcePayload(BaseModel):
    title: str
    description: str
    type: str
    added_by_user_id: int

# --- API Routes ---

@app.get("/api/status")
def get_status():
    global censor_working
    return {
        "tiny_censor_online": censor.initialized,
        "tiny_censor_healthy_toggle": censor_working,
        "tiny_censor_active": censor.initialized and censor_working,
        "qwen_online": query_layer.initialized,
        "db_initialized": os.path.exists(os.path.join(os.path.dirname(__file__), "shalim.db"))
    }

@app.post("/api/admin/toggle-censor")
def toggle_censor(working: bool = Body(..., embed=True)):
    global censor_working
    censor_working = working
    logger.info(f"Admin toggled TinyCensor working status to: {censor_working}")
    return {"status": "success", "tiny_censor_healthy_toggle": censor_working}

@app.get("/api/hubs")
def list_hubs():
    conn = get_db_connection()
    try:
        hubs = conn.execute("SELECT * FROM hubs").fetchall()
        return [dict(h) for h in hubs]
    finally:
        conn.close()

@app.post("/api/hubs")
def create_hub(name: str = Body(...), address: str = Body(...), website: str = Body(None), wifi_ssid: str = Body(...), wifi_password: str = Body(None)):
    conn = get_db_connection()
    try:
        # Check Censor first
        if not check_tiny_censor_health(conn):
            raise HTTPException(status_code=503, detail="TinyCensor is offline! Hub creation aborted and audit logged.")

        # Censor text
        for field, val in [("name", name), ("address", address), ("wifi_ssid", wifi_ssid)]:
            censored = censor.check_text(val)
            if censored["is_problematic"]:
                raise HTTPException(status_code=400, detail=f"Flagged by TinyCensor: {censored['reason']}")

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO hubs (name, address, website, wifi_ssid, wifi_password, flagged) VALUES (?, ?, ?, ?, ?, 0)",
            (name, address, website, wifi_ssid, wifi_password)
        )
        conn.commit()
        return {"status": "success", "hub_id": cursor.lastrowid}
    finally:
        conn.close()

@app.get("/api/users")
def list_users():
    conn = get_db_connection()
    try:
        users = conn.execute("SELECT users.*, hubs.name as primary_hub_name FROM users LEFT JOIN hubs ON users.primary_hub_id = hubs.id").fetchall()
        return [dict(u) for u in users]
    finally:
        conn.close()

@app.get("/api/users/{user_id}/profile")
def get_user_profile(user_id: int):
    conn = get_db_connection()
    try:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        skills = conn.execute("SELECT skill_name, acquired_at FROM user_skills WHERE user_id = ?", (user_id,)).fetchall()
        
        # Determine if this user is effectively a guest in other hubs
        primary_hub_flagged = False
        if user["primary_hub_id"]:
            hub = conn.execute("SELECT flagged FROM hubs WHERE id = ?", (user["primary_hub_id"],)).fetchone()
            if hub and hub["flagged"] == 1:
                primary_hub_flagged = True
                
        is_guest_everywhere = (user["age"] < 18) or (user["is_guest_only"] == 1) or primary_hub_flagged
        
        return {
            **dict(user),
            "skills": [dict(s) for s in skills],
            "is_guest_everywhere": is_guest_everywhere,
            "primary_hub_flagged": primary_hub_flagged
        }
    finally:
        conn.close()

@app.post("/api/hubs/{hub_id}/flag")
def flag_hub(hub_id: int, flagged: int = Body(..., embed=True)):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE hubs SET flagged = ? WHERE id = ?", (flagged, hub_id))
        conn.commit()
        logger.warning(f"Hub #{hub_id} flagging updated to {flagged}.")
        return {"status": "success", "hub_id": hub_id, "flagged": flagged}
    finally:
        conn.close()

@app.get("/api/hubs/{hub_id}/members")
def get_hub_members(hub_id: int, requester_id: int):
    """
    Returns all members associated with a hub.
    STRICT SECURITY RULE: Only accessible if the requester is an admin of this hub.
    Regular members cannot browse the hub member list.
    """
    conn = get_db_connection()
    try:
        # Verify requester is Admin
        requester = conn.execute("SELECT * FROM users WHERE id = ?", (requester_id,)).fetchone()
        if not requester or requester["is_admin"] != 1 or requester["primary_hub_id"] != hub_id:
            raise HTTPException(status_code=403, detail="Access denied. Only Hub Admins can view all member profiles.")

        # Find members
        memberships = conn.execute("""
            SELECT u.id, u.username, u.age, m.status, u.primary_hub_id
            FROM users u
            JOIN hub_memberships m ON u.id = m.user_id
            WHERE m.hub_id = ?
        """, (hub_id,)).fetchall()
        
        results = []
        for m in memberships:
            skills = conn.execute("SELECT skill_name FROM user_skills WHERE user_id = ?", (m["id"],)).fetchall()
            # Calculate effective role (considering demotion/age)
            effective_role = get_user_effective_status(conn, m["id"], hub_id)
            results.append({
                **dict(m),
                "skills": [s["skill_name"] for s in skills],
                "effective_role": effective_role
            })
        return results
    finally:
        conn.close()

@app.get("/api/hubs/{hub_id}/resources")
def get_hub_resources(hub_id: int):
    conn = get_db_connection()
    try:
        resources = conn.execute("SELECT r.*, u.username as added_by_username FROM resources r LEFT JOIN users u ON r.added_by_user_id = u.id WHERE r.hub_id = ?", (hub_id,)).fetchall()
        return [dict(r) for r in resources]
    finally:
        conn.close()

@app.post("/api/hubs/{hub_id}/resources")
def add_hub_resource(hub_id: int, payload: ResourcePayload):
    conn = get_db_connection()
    try:
        # Check Censor Health
        if not check_tiny_censor_health(conn, hub_id):
            raise HTTPException(status_code=503, detail="TinyCensor is broken! Originating hub has been FLAGGED.")
            
        # TinyCensor checks resource
        title_censored = censor.check_text(payload.title)
        desc_censored = censor.check_text(payload.description)
        if title_censored["is_problematic"] or desc_censored["is_problematic"]:
            raise HTTPException(status_code=400, detail=f"Flagged by TinyCensor: {title_censored['reason'] if title_censored['is_problematic'] else desc_censored['reason']}")

        # Insert Resource
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO resources (hub_id, title, description, type, added_by_user_id) VALUES (?, ?, ?, ?, ?)",
            (hub_id, payload.title, payload.description, payload.type, payload.added_by_user_id)
        )
        resource_id = cursor.lastrowid
        
        # AI Collation: derive skills from resource automatically
        derived_skills = query_layer.derive_skills_from_resource(payload.title, payload.description)
        
        # Link skills to adding user (simulating skill acquisition)
        acquired_at = datetime.now().strftime("%Y-%m-%d")
        for skill in derived_skills:
            conn.execute(
                "INSERT OR IGNORE INTO user_skills (user_id, skill_name, acquired_at, derived_from_resource_id) VALUES (?, ?, ?, ?)",
                (payload.added_by_user_id, skill, acquired_at, resource_id)
            )
            
        conn.commit()
        return {"status": "success", "resource_id": resource_id, "derived_skills": derived_skills}
    finally:
        conn.close()

@app.post("/api/query")
def run_query(payload: QueryRequest):
    conn = get_db_connection()
    try:
        # 1. Determine effective status in the target hub
        role = get_user_effective_status(conn, payload.user_id, payload.hub_id)
        
        # Rule Check: Guests cannot use AI Search
        if role == "guest":
            raise HTTPException(status_code=403, detail="Guests (including Under-18s and members of flagged hubs) are not permitted to use AI search.")
            
        # 2. Check Censor Health
        # Retrieve requester's primary hub
        user = conn.execute("SELECT primary_hub_id FROM users WHERE id = ?", (payload.user_id,)).fetchone()
        primary_hub_id = user["primary_hub_id"] if user else None
        
        if not check_tiny_censor_health(conn, primary_hub_id):
            raise HTTPException(status_code=503, detail="TinyCensor is offline! Your primary hub has been flagged, and you are demoted to guest status.")

        # 3. Moderation of query using TinyCensor
        censored = censor.check_text(payload.query)
        if censored["is_problematic"]:
            raise HTTPException(status_code=400, detail=f"Flagged by TinyCensor: {censored['reason']}")

        # 4. Fetch potential candidate members (in same hub, not guests, not self)
        candidates = conn.execute("""
            SELECT u.id, u.username
            FROM users u
            JOIN hub_memberships m ON u.id = m.user_id
            WHERE m.hub_id = ? AND u.id != ?
        """, (payload.hub_id, payload.user_id)).fetchall()
        
        members_list = []
        for c in candidates:
            # Check if this candidate is demoted to guest
            cand_role = get_user_effective_status(conn, c["id"], payload.hub_id)
            if cand_role == "guest":
                continue # Guests do NOT show up in search
                
            skills = conn.execute("SELECT skill_name FROM user_skills WHERE user_id = ?", (c["id"],)).fetchall()
            members_list.append({
                "id": c["id"],
                "username": c["username"],
                "skills": [s["skill_name"] for s in skills]
            })

        # 5. Fetch nearby hubs (other hubs, not the current hub)
        all_hubs = conn.execute("SELECT * FROM hubs WHERE id != ? AND flagged = 0", (payload.hub_id,)).fetchall()
        hubs_list = []
        
        for h in all_hubs:
            # Compute mock distance based on lat/lon
            curr_hub = conn.execute("SELECT latitude, longitude FROM hubs WHERE id = ?", (payload.hub_id,)).fetchone()
            distance = 5.0 # Default fallback
            if curr_hub and h["latitude"] and h["longitude"]:
                # Quick Pythagorean distance scaled to miles approx
                distance = round(((h["latitude"] - curr_hub["latitude"])**2 + (h["longitude"] - curr_hub["longitude"])**2)**0.5 * 69, 1)
            
            # Fetch skills available in this hub
            hub_skills = conn.execute("""
                SELECT DISTINCT s.skill_name 
                FROM user_skills s
                JOIN hub_memberships m ON s.user_id = m.user_id
                WHERE m.hub_id = ?
            """, (h["id"],)).fetchall()
            
            hubs_list.append({
                "id": h["id"],
                "name": h["name"],
                "distance": distance,
                "skills": [s["skill_name"] for s in hub_skills]
            })

        # 6. Run Qwen query matching layer
        results = query_layer.match_query(payload.query, members_list, hubs_list)
        return results
    finally:
        conn.close()

@app.post("/api/meetings")
def request_meeting(payload: MeetingRequestPayload):
    # Enforce strict 100 character reason limit
    if len(payload.reason) > 100:
        raise HTTPException(status_code=400, detail="Meeting request reason is limited to a maximum of 100 characters to encourage face-to-face talk.")
        
    conn = get_db_connection()
    try:
        # Check Censor Health
        user = conn.execute("SELECT primary_hub_id FROM users WHERE id = ?", (payload.requester_id,)).fetchone()
        primary_hub_id = user["primary_hub_id"] if user else None
        
        if not check_tiny_censor_health(conn, primary_hub_id):
            raise HTTPException(status_code=503, detail="TinyCensor is broken! Meeting request rejected, and your hub has been flagged.")
            
        # Moderate reason
        censored = censor.check_text(payload.reason)
        if censored["is_problematic"]:
            raise HTTPException(status_code=400, detail=f"Flagged by TinyCensor: {censored['reason']}")

        # Role checks
        role = get_user_effective_status(conn, payload.requester_id, payload.hub_id)
        receiver = conn.execute("SELECT * FROM users WHERE id = ?", (payload.receiver_id,)).fetchone()
        
        if not receiver:
            raise HTTPException(status_code=404, detail="Requested user not found")
            
        # RULE: Guests can ONLY request meetings with Hub Admins
        if role == "guest":
            if receiver["is_admin"] != 1 or receiver["primary_hub_id"] != payload.hub_id:
                raise HTTPException(status_code=403, detail="Guest restriction: Guests can only request meetings with the Hub Admin (e.g. to register).")

        # Save Meeting
        created_at = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO meetings (requester_id, receiver_id, hub_id, reason, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (payload.requester_id, payload.receiver_id, payload.hub_id, payload.reason, created_at)
        )
        conn.commit()
        return {"status": "success", "meeting_id": cursor.lastrowid}
    finally:
        conn.close()

@app.get("/api/meetings/{user_id}")
def get_user_meetings(user_id: int):
    conn = get_db_connection()
    try:
        meetings = conn.execute("""
            SELECT m.*, u1.username as requester_username, u2.username as receiver_username, h.name as hub_name, h.address as hub_address
            FROM meetings m
            JOIN users u1 ON m.requester_id = u1.id
            JOIN users u2 ON m.receiver_id = u2.id
            JOIN hubs h ON m.hub_id = h.id
            WHERE m.requester_id = ? OR m.receiver_id = ?
            ORDER BY m.created_at DESC
        """, (user_id, user_id)).fetchall()
        return [dict(m) for m in meetings]
    finally:
        conn.close()

@app.post("/api/meetings/{meeting_id}/action")
def update_meeting_status(meeting_id: int, action: str = Body(..., embed=True), user_id: int = Body(..., embed=True)):
    """
    Action can be 'approved', 'rejected', or 'completed'.
    Only the receiver can approve/reject. Either can complete.
    """
    if action not in ["approved", "rejected", "completed"]:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    conn = get_db_connection()
    try:
        meeting = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")

        # Security check
        if action in ["approved", "rejected"] and meeting["receiver_id"] != user_id:
            raise HTTPException(status_code=403, detail="Only the meeting recipient can approve or decline request.")
            
        if action == "completed" and user_id not in [meeting["requester_id"], meeting["receiver_id"]]:
            raise HTTPException(status_code=403, detail="Only meeting participants can mark it as completed.")

        # Update
        conn.execute("UPDATE meetings SET status = ? WHERE id = ?", (action, meeting_id))
        
        # If a guest request to join was approved by admin, promote guest to member!
        if action == "approved" and meeting["status"] == "pending":
            requester = conn.execute("SELECT * FROM users WHERE id = ?", (meeting["requester_id"],)).fetchone()
            receiver = conn.execute("SELECT * FROM users WHERE id = ?", (meeting["receiver_id"],)).fetchone()
            # If receiver is admin and requester has a membership
            if receiver and receiver["is_admin"] == 1:
                # Update hub_memberships to member
                conn.execute(
                    "INSERT OR REPLACE INTO hub_memberships (user_id, hub_id, status) VALUES (?, ?, 'member')",
                    (meeting["requester_id"], meeting["hub_id"])
                )
                logger.info(f"User #{meeting['requester_id']} promoted to MEMBER of hub #{meeting['hub_id']} by admin approval.")

        conn.commit()
        return {"status": "success", "meeting_id": meeting_id, "new_status": action}
    finally:
        conn.close()

@app.post("/api/hubs/{hub_id}/join")
def join_hub(hub_id: int, user_id: int = Body(..., embed=True)):
    conn = get_db_connection()
    try:
        # Check if already has membership
        membership = conn.execute("SELECT * FROM hub_memberships WHERE user_id = ? AND hub_id = ?", (user_id, hub_id)).fetchone()
        if membership:
            return {"status": "success", "message": "Already registered with this status", "current_status": membership["status"]}
            
        # Determine initial membership status
        # Under-18 is guest. Everyone else starts as 'pending_admin_approval' (requests meeting with admin to verify).
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        initial_status = "pending_admin_approval"
        if user["age"] < 18 or user["is_guest_only"] == 1:
            initial_status = "guest"
            
        conn.execute(
            "INSERT INTO hub_memberships (user_id, hub_id, status) VALUES (?, ?, ?)",
            (user_id, hub_id, initial_status)
        )
        conn.commit()
        return {"status": "success", "membership_status": initial_status}
    finally:
        conn.close()

# Serves static frontend files if directory exists
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    logger.warning(f"Frontend directory not found at: {FRONTEND_DIR}. API only mode.")
