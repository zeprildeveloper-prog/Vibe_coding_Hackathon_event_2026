import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger("shalim.database")
DB_PATH = os.path.join(os.path.dirname(__file__), "shalim.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    logger.info(f"Initializing database at {DB_PATH}...")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Hubs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hubs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        website TEXT,
        wifi_ssid TEXT NOT NULL,
        wifi_password TEXT,
        flagged INTEGER DEFAULT 0,
        latitude REAL,
        longitude REAL
    )
    """)
    
    # 2. Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        age INTEGER NOT NULL,
        is_admin INTEGER DEFAULT 0,
        primary_hub_id INTEGER,
        is_guest_only INTEGER DEFAULT 0, -- Overrides to guest (e.g. Under 18 or manual demote)
        FOREIGN KEY (primary_hub_id) REFERENCES hubs(id)
    )
    """)
    
    # 3. Hub Memberships (Allows users to be members of multiple hubs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hub_memberships (
        user_id INTEGER,
        hub_id INTEGER,
        status TEXT NOT NULL, -- 'pending_admin_approval', 'member', 'guest'
        PRIMARY KEY (user_id, hub_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (hub_id) REFERENCES hubs(id) ON DELETE CASCADE
    )
    """)
    
    # 4. Resources (Library catalog, toolkits, supplies)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hub_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        type TEXT DEFAULT 'book', -- 'book', 'tool', 'medical', 'radio', 'other'
        added_by_user_id INTEGER,
        FOREIGN KEY (hub_id) REFERENCES hubs(id) ON DELETE CASCADE,
        FOREIGN KEY (added_by_user_id) REFERENCES users(id)
    )
    """)
    
    # 5. User Skills (Skills acquired by members)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_skills (
        user_id INTEGER,
        skill_name TEXT,
        acquired_at TEXT,
        derived_from_resource_id INTEGER,
        PRIMARY KEY (user_id, skill_name),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (derived_from_resource_id) REFERENCES resources(id) ON DELETE SET NULL
    )
    """)
    
    # 6. Meetings (Strictly restricted to hubs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        hub_id INTEGER NOT NULL,
        reason TEXT NOT NULL, -- Max 100 chars validation enforced
        status TEXT NOT NULL, -- 'pending', 'approved', 'rejected', 'completed'
        created_at TEXT NOT NULL,
        FOREIGN KEY (requester_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id),
        FOREIGN KEY (hub_id) REFERENCES hubs(id)
    )
    """)

    # Check if we need to seed initial mock data
    cursor.execute("SELECT COUNT(*) FROM hubs")
    if cursor.fetchone()[0] == 0:
        logger.info("Seeding initial mock data for Shalim...")
        
        # Seed Hubs
        hubs = [
            ("Encode London Hub", "41 Pitfield St, London N1 6DA", "https://encode.club", "Encode_WiFi_Resilient", "hackthefuture", 0, 51.5273, -0.0847),
            ("Hackney Community Library", "Hackney Town Hall, London E8 1EA", "https://hackney.gov.uk/libraries", "Hackney_Free_WiFi", "readbooks", 0, 51.5442, -0.0573),
            ("Tower Hamlets Resource Center", "Whitechapel Rd, London E1 1BU", "https://towerhamlets.gov.uk", "TH_Resilience_Mesh", "community1st", 0, 51.5194, -0.0601),
            ("Dodgy Safehouse (Flagged)", "Secret Alley, London EC1A 4JQ", "http://dodgywebsite.onion", "DarkNet_WiFi", "12345678", 1, 51.5201, -0.1011)
        ]
        cursor.executemany("""
        INSERT INTO hubs (name, address, website, wifi_ssid, wifi_password, flagged, latitude, longitude)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, hubs)
        
        # Seed Users (Admins, Members, Guests, Under-18s)
        # 1: Alice (Admin of Encode London)
        # 2: Bob (Member of Encode London - has permaculture and radio skills)
        # 3: Charlie (Member of Hackney Library - has solar and plumbing skills)
        # 4: Dave (U18 Guest at Encode London - can't search, can't request meetings except with Admin)
        # 5: Mallory (Member of Dodgy Safehouse - will be demoted to guest because hub is flagged)
        # 6: Eve (Admin of Hackney Community Library)
        users = [
            ("alice_admin", 32, 1, 1, 0),
            ("bob_builder", 28, 0, 1, 0),
            ("charlie_green", 45, 0, 2, 0),
            ("dave_junior", 16, 0, 1, 1), # under 18 -> guest only
            ("mallory_rogue", 29, 0, 4, 0), # primary hub is flagged -> guest only in other hubs
            ("eve_librarian", 38, 1, 2, 0)
        ]
        cursor.executemany("""
        INSERT INTO users (username, age, is_admin, primary_hub_id, is_guest_only)
        VALUES (?, ?, ?, ?, ?)
        """, users)
        
        # Seed Hub Memberships
        memberships = [
            (1, 1, 'member'), # Alice is admin/member of Encode
            (2, 1, 'member'), # Bob is member of Encode
            (2, 2, 'member'), # Bob is also member of Hackney
            (3, 2, 'member'), # Charlie is member of Hackney
            (4, 1, 'guest'),  # Dave is guest at Encode
            (5, 4, 'member'), # Mallory is member of flagged Dodgy Safehouse
            (5, 1, 'guest'),  # Mallory joins Encode as a guest
            (6, 2, 'member')  # Eve is admin/member of Hackney
        ]
        cursor.executemany("""
        INSERT INTO hub_memberships (user_id, hub_id, status)
        VALUES (?, ?, ?)
        """, memberships)

        # Seed Skills
        skills = [
            (2, "Agriculture", "2026-06-01", None),
            (2, "Gardening", "2026-06-01", None),
            (2, "Ham Radio", "2026-06-02", None),
            (2, "LoRa Communication", "2026-06-02", None),
            (3, "Solar Power Setup", "2026-06-03", None),
            (3, "Electrical Engineering", "2026-06-03", None),
            (3, "Plumbing", "2026-06-04", None),
            (3, "Water Purification", "2026-06-04", None)
        ]
        cursor.executemany("""
        INSERT INTO user_skills (user_id, skill_name, acquired_at, derived_from_resource_id)
        VALUES (?, ?, ?, ?)
        """, skills)

        # Seed Resources
        resources = [
            (1, "The Handbuilt Solar Generator Manual", "Complete guide to assembling off-grid generator kits using lithium batteries.", "tool", 1),
            (1, "LoRa Node Assembly Kit", "Hardware box containing 4 LoRa transceivers and instructions to assemble peer-to-peer messaging networks.", "radio", 2),
            (2, "Permaculture Principles for Flat Balconies", "Step-by-step instructions for small-scale balcony farming, vertical gardening, and composting.", "book", 3),
            (2, "Emergency First Aid Guide", "Official Red Cross handbook for dealing with severe trauma, wounds, and CPR without power.", "medical", 6)
        ]
        cursor.executemany("""
        INSERT INTO resources (hub_id, title, description, type, added_by_user_id)
        VALUES (?, ?, ?, ?, ?)
        """, resources)
        
        # Seed Meeting Requests
        now_str = datetime.now().isoformat()
        meetings = [
            (2, 1, 1, "Requesting membership verification at Encode London. Met at local orientation event.", "approved", now_str),
            (3, 6, 2, "Requesting membership verification at Hackney Library. Verified local utility bill.", "approved", now_str),
            (4, 1, 1, "Under-18 guest checking in with admin. Looking to participate in basic mesh network workshop.", "pending", now_str)
        ]
        cursor.executemany("""
        INSERT INTO meetings (requester_id, receiver_id, hub_id, reason, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, meetings)

    conn.commit()
    conn.close()
    logger.info("Database initialized and seeded.")

if __name__ == "__main__":
    init_db()
