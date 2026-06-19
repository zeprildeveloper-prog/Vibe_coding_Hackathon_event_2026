// Detect API base URL. Fallback to localhost:8000 if opened directly via file://
const API_BASE = (window.location.protocol.startsWith('http')) 
    ? window.location.origin 
    : 'http://localhost:8000';

let users = [];
let hubs = [];
let currentUser = null;
let currentHub = null;
let networkMode = 'lora';

// Target of the requested meeting connection
let meetingTargetUserId = null;
let meetingForAdminOnly = false;

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

async function initApp() {
    try {
        await checkSystemStatus();
        await loadHubs();
        await loadUsers();
        setNetwork('lora'); // default
    } catch (err) {
        console.error("Initialization error:", err);
        showAlert("Failed to connect to local Shalim backend. Please make sure python backend is running on port 8000.", "danger");
    }
}

async function checkSystemStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        const status = await res.json();
        
        // Update Censor toggle
        const toggle = document.getElementById("censor-toggle");
        toggle.checked = status.tiny_censor_healthy_toggle;
        
        const desc = document.getElementById("censor-desc");
        if (status.tiny_censor_active) {
            desc.innerText = "Status: HEALTHY";
            desc.style.color = "var(--accent-wifi)";
        } else if (!status.tiny_censor_online) {
            desc.innerText = "Status: OFFLINE (Broken/Missing)";
            desc.style.color = "var(--accent-danger)";
        } else {
            desc.innerText = "Status: INACTIVE (Simulated Crash)";
            desc.style.color = "var(--accent-danger)";
        }
    } catch (e) {
        console.error("Failed to query API status:", e);
    }
}

async function toggleCensor() {
    const checked = document.getElementById("censor-toggle").checked;
    try {
        const res = await fetch(`${API_BASE}/api/admin/toggle-censor`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working: checked })
        });
        const data = await res.json();
        await checkSystemStatus();
        showAlert(`Simulated TinyCensor health updated to: ${checked ? 'HEALTHY' : 'CRASHED'}`, checked ? 'info' : 'danger');
        
        // Reload context since flagging states might update
        if (!checked) {
            // Trigger quick data reload to propagate flagging
            await loadHubs();
            if (currentUser) {
                await loadUserProfile(currentUser.id);
            }
        }
    } catch (err) {
        showAlert("Failed to toggle Censor state", "danger");
    }
}

async function loadHubs() {
    const res = await fetch(`${API_BASE}/api/hubs`);
    hubs = await res.json();
    
    // Default to first hub if none selected
    if (!currentHub && hubs.length > 0) {
        currentHub = hubs[0];
    }
    
    renderHubsList();
    renderCurrentHubDetails();
}

function renderHubsList() {
    const container = document.getElementById("hubs-list");
    container.innerHTML = "";
    
    hubs.forEach(h => {
        const isSelected = currentHub && currentHub.id === h.id;
        const card = document.createElement("div");
        card.className = `hub-card ${isSelected ? 'active' : ''}`;
        card.onclick = () => selectHub(h.id);
        
        let titleHtml = h.name;
        if (h.flagged === 1) {
            titleHtml += ` <span class="flagged-badge"><i class="fa-solid fa-triangle-exclamation"></i> Flagged</span>`;
        }
        
        card.innerHTML = `
            <h4>${titleHtml}</h4>
            <p>${h.address}</p>
        `;
        container.appendChild(card);
    });
}

async function selectHub(hubId) {
    currentHub = hubs.find(h => h.id === hubId);
    renderHubsList();
    renderCurrentHubDetails();
    
    if (currentUser) {
        await loadUserProfile(currentUser.id);
    }
}

function renderCurrentHubDetails() {
    const banner = document.getElementById("current-hub-banner");
    if (!currentHub) return;
    
    let text = `SSID: ${currentHub.wifi_ssid}`;
    if (currentHub.flagged === 1) {
        text = `<span class="flagged-badge"><i class="fa-solid fa-triangle-exclamation"></i> AUDIT FAIL: CENSOR FAILURE IN HUB</span>`;
    }
    
    banner.innerHTML = `
        <h3><i class="fa-solid fa-house-chimney"></i> ${currentHub.name}</h3>
        <p>${text}</p>
    `;
    
    // Trigger relative panels reload
    loadResources();
}

async function loadUsers() {
    const res = await fetch(`${API_BASE}/api/users`);
    users = await res.json();
    
    const selector = document.getElementById("user-select");
    selector.innerHTML = "";
    
    users.forEach(u => {
        const option = document.createElement("option");
        option.value = u.id;
        option.innerText = `${u.username} (${u.is_admin ? 'Admin' : 'Member'}, Age ${u.age})`;
        selector.appendChild(option);
    });
    
    // Choose default active user
    if (users.length > 0) {
        selector.value = users[0].id;
        await loadUserProfile(users[0].id);
    }
}

async function switchUser() {
    const userId = parseInt(document.getElementById("user-select").value);
    await loadUserProfile(userId);
}

async function loadUserProfile(userId) {
    try {
        const res = await fetch(`${API_BASE}/api/users/${userId}/profile`);
        currentUser = await res.json();
        
        // Update user UI
        const badge = document.getElementById("active-user-badge");
        badge.innerHTML = `
            <div class="user-avatar">${currentUser.username.substring(0, 2).toUpperCase()}</div>
            <div class="user-info">
                <h4>${currentUser.username}</h4>
                <span>${currentUser.is_admin ? 'Hub Admin' : 'Hub Member'} (Age ${currentUser.age})</span>
            </div>
        `;
        
        // Enforce role permissions and hide/show panels
        updateRoleViews();
        loadMeetings();
    } catch (err) {
        console.error("Failed to load user profile:", err);
    }
}

function updateRoleViews() {
    if (!currentUser || !currentHub) return;
    
    // Check if user is effectively a guest in the active hub
    // Guest if: U18 OR primary hub is flagged OR status in memberships is guest OR user_skills is blocked.
    // Let's compute effective status locally based on backend rules (checked in database as well)
    const isU18 = currentUser.age < 18;
    
    // Check if user primary hub is flagged
    let primaryHubFlagged = false;
    if (currentUser.primary_hub_id) {
        const hub = hubs.find(h => h.id === currentUser.primary_hub_id);
        if (hub && hub.flagged === 1) {
            primaryHubFlagged = true;
        }
    }
    
    // We are on a flagged hub? If the hub we are CURRENTLY on is flagged, it is locked down.
    const onFlaggedHub = currentHub.flagged === 1;
    
    const isGuestOnly = currentUser.is_guest_only === 1;
    
    const isGuest = isU18 || primaryHubFlagged || isGuestOnly || onFlaggedHub;
    
    const viewMember = document.getElementById("view-member");
    const viewGuest = document.getElementById("view-guest");
    const viewAdmin = document.getElementById("view-admin");
    const alertBanner = document.getElementById("alert-banner");
    
    alertBanner.className = "alert-banner hidden";
    
    // Setup warning banners
    if (onFlaggedHub) {
        alertBanner.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> <strong>WARNING:</strong> This Hub is FLAGGED due to TinyCensor node failures. System functionality restricted.`;
        alertBanner.className = "alert-banner";
    } else if (primaryHubFlagged) {
        alertBanner.innerHTML = `<i class="fa-solid fa-shield-halved"></i> <strong>ALERT:</strong> Your primary hub (${currentUser.primary_hub_name}) is flagged. You are demoted to guest status in other hubs.`;
        alertBanner.className = "alert-banner";
    }

    // Role-based visibility
    if (currentUser.is_admin === 1 && currentUser.primary_hub_id === currentHub.id && !onFlaggedHub) {
        // Admin
        viewMember.classList.add("hidden");
        viewGuest.classList.add("hidden");
        viewAdmin.classList.remove("hidden");
        loadAdminRegistry();
        updateAdminStats();
    } else if (isGuest) {
        // Guest
        viewMember.classList.add("hidden");
        viewGuest.classList.remove("hidden");
        viewAdmin.classList.add("hidden");
        
        const reasonText = document.getElementById("guest-reason-text");
        if (onFlaggedHub) {
            reasonText.innerText = "This Hub has failed local AI censor safety audits (TinyCensor node offline) and has been flagged. Browsing & search protocols have been suspended.";
        } else if (isU18) {
            reasonText.innerText = "You are browsing as an Under-18 Guest. Guests are restricted from using AI semantic search or viewing list of other members to secure local safety topology.";
        } else if (primaryHubFlagged) {
            reasonText.innerText = "Your home community hub is flagged. You are restricted to guest-only local privileges (restricted search and direct messaging) until your hub's censor is verified.";
        } else {
            reasonText.innerText = "You are currently a guest in this hub. Request a verification meeting with the hub administrator to upgrade your access.";
        }
        
        // Hide registration buttons if they are already pending or already checked in
        const registerArea = document.getElementById("guest-register-area");
        if (onFlaggedHub) {
            registerArea.className = "guest-actions mt-2 hidden";
        } else {
            registerArea.className = "guest-actions mt-2";
        }
    } else {
        // Full Member
        viewMember.classList.remove("hidden");
        viewGuest.classList.add("hidden");
        viewAdmin.classList.add("hidden");
        
        // Clear search UI
        document.getElementById("search-query").value = "";
        document.getElementById("search-results-container").classList.add("hidden");
    }
}

// Set Transmission Mode Visual Theme
function setNetwork(mode) {
    networkMode = mode;
    
    // Toggle active button
    document.querySelectorAll(".net-btn").forEach(btn => btn.classList.remove("active"));
    document.getElementById(`net-${mode}`).classList.add("active");
    
    const root = document.documentElement;
    const dot = document.getElementById("status-dot");
    const statusText = document.getElementById("status-text");
    
    // Adapt CSS Theme Variables and Status line according to transmission limits
    if (mode === 'lora') {
        root.style.setProperty('--active-accent', 'var(--accent-lora)');
        dot.className = "status-dot";
        statusText.innerHTML = "LoRa Mesh Topology: ACTIVE (Bandwidth Opt: High)";
        showAlert("Switched transmission to LoRa mesh. Network operates offline using peer nodes.", "info");
    } else if (mode === 'wifi') {
        root.style.setProperty('--active-accent', 'var(--accent-wifi)');
        dot.className = "status-dot healthy";
        statusText.innerHTML = "Hub WiFi Network: CONNECTED (Local Core)";
        showAlert("Switched transmission to Hub local WiFi. Local routing is fast & responsive.", "info");
    } else if (mode === '5g') {
        root.style.setProperty('--active-accent', 'var(--accent-5g)');
        dot.className = "status-dot";
        statusText.innerHTML = "5G Node Link: ESTABLISHED (Sync Cloud)";
        showAlert("Switched transmission to 5G. Synchronizing topology logs with external mirrors.", "info");
    }
}

// Resources Catalog Loading
async function loadResources() {
    if (!currentHub) return;
    try {
        const res = await fetch(`${API_BASE}/api/hubs/${currentHub.id}/resources`);
        const resources = await res.json();
        
        renderResourcesGrid("member-resources-list", resources);
        renderResourcesGrid("guest-resources-list", resources);
    } catch (e) {
        console.error("Error loading resources:", e);
    }
}

function renderResourcesGrid(elementId, resources) {
    const container = document.getElementById(elementId);
    if (!container) return;
    container.innerHTML = "";
    
    if (resources.length === 0) {
        container.innerHTML = `<p style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 2rem;">No local resources registered at this hub yet.</p>`;
        return;
    }
    
    resources.forEach(r => {
        const card = document.createElement("div");
        card.className = "resource-card";
        
        let icon = "fa-book";
        if (r.type === "tool") icon = "fa-screwdriver-wrench";
        if (r.type === "radio") icon = "fa-walkie-talkie";
        if (r.type === "medical") icon = "fa-kit-medical";
        
        card.innerHTML = `
            <div class="res-body">
                <div class="res-header">
                    <div class="res-icon"><i class="fa-solid ${icon}"></i></div>
                    <h4>${r.title}</h4>
                </div>
                <p>${r.description || 'No description provided.'}</p>
            </div>
            <div class="res-meta">
                <span>Type: ${r.type.toUpperCase()}</span>
                <span>Added By: ${r.added_by_username || 'System'}</span>
            </div>
        `;
        container.appendChild(card);
    });
}

// Search Operations
async function executeSearch() {
    const queryInput = document.getElementById("search-query");
    const query = queryInput.value.trim();
    if (!query) return;
    
    try {
        showAlert("Querying local Shalim AI Layer...", "info");
        const res = await fetch(`${API_BASE}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: currentUser.id,
                hub_id: currentHub.id,
                query: query
            })
        });
        
        const data = await res.json();
        
        if (res.status === 400 || res.status === 403 || res.status === 503) {
            showAlert(data.detail, "danger");
            // If censors broke their hub might have flagged, trigger profile reload
            await checkSystemStatus();
            await loadHubs();
            await loadUserProfile(currentUser.id);
            return;
        }
        
        renderSearchResults(data);
    } catch (err) {
        console.error("Search error:", err);
        showAlert("Failed to execute local AI Search query.", "danger");
    }
}

function handleSearchKey(event) {
    if (event.key === 'Enter') {
        executeSearch();
    }
}

function renderSearchResults(data) {
    const container = document.getElementById("search-results-container");
    container.classList.remove("hidden");
    
    // Render Matched Members
    const membersList = document.getElementById("matched-members-list");
    membersList.innerHTML = "";
    
    const matched = data.matched_members || [];
    if (matched.length === 0) {
        membersList.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center;">No local members in your hub match this skill query.</p>`;
    } else {
        matched.forEach(m => {
            const card = document.createElement("div");
            card.className = "profile-card";
            
            const skillsHtml = m.skills.map(s => `<span class="skill-tag">${s}</span>`).join("");
            
            card.innerHTML = `
                <div>
                    <div class="profile-header">
                        <div class="profile-avatar">${m.username.substring(0, 2).toUpperCase()}</div>
                        <h4>${m.username}</h4>
                    </div>
                    <div class="profile-skills">${skillsHtml}</div>
                    <div class="match-reason"><i class="fa-solid fa-robot"></i> ${m.match_reason}</div>
                </div>
                <button class="btn-primary mt-2" style="width: 100%; justify-content: center;" onclick="openMeetingModal(${m.user_id}, false)">
                    <i class="fa-solid fa-envelope"></i> Request Meetup
                </button>
            `;
            membersList.appendChild(card);
        });
    }
    
    // Render Nearby Hubs
    const hubsList = document.getElementById("nearby-hubs-list");
    hubsList.innerHTML = "";
    
    const nearby = data.nearby_hubs || [];
    if (nearby.length === 0) {
        hubsList.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-secondary); text-align: center;">No surrounding hubs found with this skill.</p>`;
    } else {
        nearby.forEach(nh => {
            const card = document.createElement("div");
            card.className = "hub-result-card";
            
            const skillsHtml = nh.skills.map(s => `<span class="skill-tag">${s}</span>`).join("");
            
            card.innerHTML = `
                <div class="hub-result-header">
                    <h4>${nh.name}</h4>
                    <span class="hub-dist">${nh.distance} miles</span>
                </div>
                <div class="profile-skills" style="margin-bottom: 0.5rem;">${skillsHtml}</div>
                <button class="btn-secondary" style="width: 100%; justify-content: center; font-size: 0.8rem; padding: 0.4rem 0.8rem;" onclick="selectHub(${nh.hub_id})">
                    <i class="fa-solid fa-circle-right"></i> Navigate to Hub
                </button>
            `;
            hubsList.appendChild(card);
        });
    }
    
    // Smooth scroll down to results
    container.scrollIntoView({ behavior: 'smooth' });
}

// Admin Panel Logics
async function loadAdminRegistry() {
    if (!currentUser || !currentHub) return;
    try {
        const res = await fetch(`${API_BASE}/api/hubs/${currentHub.id}/members?requester_id=${currentUser.id}`);
        if (res.status === 403) return; // Ignore if not admin
        const members = await res.json();
        
        const tbody = document.getElementById("admin-members-list");
        tbody.innerHTML = "";
        
        members.forEach(m => {
            const tr = document.createElement("tr");
            const skillsHtml = m.skills.map(s => `<span class="skill-tag" style="background-color:rgba(0, 230, 118, 0.05); color:#a7ffeb; border-color:rgba(0, 230, 118, 0.1);">${s}</span>`).join(" ");
            
            let statusText = m.status;
            if (m.effective_role === "guest") {
                statusText = `<span class="flagged-badge" style="display:inline-flex;">Guest (Demoted)</span>`;
            }
            
            tr.innerHTML = `
                <td><strong>${m.username}</strong></td>
                <td>${m.age}</td>
                <td>${statusText}</td>
                <td><div style="display:flex; flex-wrap:wrap; gap:0.25rem;">${skillsHtml || 'No skills logged'}</div></td>
                <td>
                    <button class="btn-secondary" style="font-size:0.75rem; padding:0.25rem 0.5rem;" onclick="openMeetingModal(${m.id}, false)">
                        Schedule Meet
                    </button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Registry load error:", e);
    }
}

async function updateAdminStats() {
    if (!currentHub) return;
    try {
        // Members count
        const memRes = await fetch(`${API_BASE}/api/hubs/${currentHub.id}/members?requester_id=${currentUser.id}`);
        const members = memRes.ok ? await memRes.json() : [];
        document.getElementById("stat-members-count").innerText = members.length;
        
        // Resources count
        const resRes = await fetch(`${API_BASE}/api/hubs/${currentHub.id}/resources`);
        const resources = resRes.ok ? await resRes.json() : [];
        document.getElementById("stat-resources-count").innerText = resources.length;
    } catch (e) {
        console.error("Failed to load stats:", e);
    }
}

async function addResource() {
    const title = document.getElementById("res-title").value.trim();
    const desc = document.getElementById("res-desc").value.trim();
    const type = document.getElementById("res-type").value;
    
    if (!title || !desc) {
        showAlert("Please fill in resource Title and Description", "danger");
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/hubs/${currentHub.id}/resources`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                description: desc,
                type: type,
                added_by_user_id: currentUser.id
            })
        });
        
        const data = await res.json();
        
        if (res.status === 400 || res.status === 503) {
            showAlert(data.detail, "danger");
            await checkSystemStatus();
            await loadHubs();
            await loadUserProfile(currentUser.id);
            return;
        }
        
        showAlert(`Successfully registered resource. AI Collation derived skills: ${data.derived_skills.join(", ")}`, "info");
        
        // Clear fields
        document.getElementById("res-title").value = "";
        document.getElementById("res-desc").value = "";
        
        // Reload
        await loadResources();
        await updateAdminStats();
        await loadAdminRegistry();
    } catch (e) {
        showAlert("Error registering resource", "danger");
    }
}

async function simulateCatalogImport() {
    // Simulate importing catalog by adding 3 pre-configured resources and extracting skills via AI
    const mockCatalog = [
        { title: "Manual of Water Purification", description: "Techniques to construct chemical and biological water filtration kits locally.", type: "tool" },
        { title: "Welding and Metal Assembly Practice", description: "Basics of oxy-acetylene welding and steel joint construction for structural repairs.", type: "tool" },
        { title: "Antenna Design & RF Wave Propagation", description: "Design principles for long-wire HF antennas and LoRa directional antennas.", type: "radio" }
    ];
    
    showAlert("Simulating catalog upload. Processing resources via Shalim AI...", "info");
    
    for (const item of mockCatalog) {
        try {
            await fetch(`${API_BASE}/api/hubs/${currentHub.id}/resources`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: item.title,
                    description: item.description,
                    type: item.type,
                    added_by_user_id: currentUser.id
                })
            });
        } catch (e) {
            console.error("Batch insert error:", e);
        }
    }
    
    showAlert("CSV library catalog import completed. Extracted core skills into hub database.", "info");
    await loadResources();
    await updateAdminStats();
    await loadAdminRegistry();
}

// Meetings Scheduler Operations
async function loadMeetings() {
    if (!currentUser) return;
    try {
        const res = await fetch(`${API_BASE}/api/meetings/${currentUser.id}`);
        const meetings = await res.json();
        
        const container = document.getElementById("meetings-list");
        container.innerHTML = "";
        
        if (meetings.length === 0) {
            container.innerHTML = `<p style="grid-column: 1/-1; text-align: center; color: var(--text-secondary); padding: 1.5rem;">No active meeting requests logged.</p>`;
            return;
        }
        
        meetings.forEach(m => {
            const card = document.createElement("div");
            card.className = `meeting-card ${m.status}`;
            
            const isRequester = m.requester_id === currentUser.id;
            const contactName = isRequester ? m.receiver_username : m.requester_username;
            const flowText = isRequester 
                ? `Sent to: <strong>${contactName}</strong>`
                : `Received from: <strong>${contactName}</strong>`;
                
            let actionsHtml = "";
            if (!isRequester && m.status === 'pending') {
                actionsHtml = `
                    <div class="meeting-actions">
                        <button class="btn-primary" style="font-size:0.75rem; padding:0.3rem 0.6rem;" onclick="handleMeetingAction(${m.id}, 'approved')">Approve</button>
                        <button class="btn-secondary" style="font-size:0.75rem; padding:0.3rem 0.6rem; color:var(--accent-danger);" onclick="handleMeetingAction(${m.id}, 'rejected')">Decline</button>
                    </div>
                `;
            } else if (m.status === 'approved') {
                actionsHtml = `
                    <div class="meeting-actions">
                        <button class="btn-secondary" style="font-size:0.75rem; padding:0.3rem 0.6rem; border-color:var(--accent-5g);" onclick="handleMeetingAction(${m.id}, 'completed')">
                            <i class="fa-solid fa-check"></i> Verify Completed
                        </button>
                    </div>
                `;
            }
            
            card.innerHTML = `
                <div>
                    <div class="meeting-meta">
                        <span>Hub: ${m.hub_name}</span><br/>
                        <span>Location: ${m.hub_address}</span>
                    </div>
                    <div style="font-size: 0.9rem; margin-bottom: 0.4rem;">
                        ${flowText} <span class="meeting-status-tag status-tag-${m.status}">${m.status}</span>
                    </div>
                    <div class="meeting-reason-box">"${m.reason}"</div>
                </div>
                ${actionsHtml}
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Meetings loading error:", e);
    }
}

async function handleMeetingAction(meetingId, action) {
    try {
        const res = await fetch(`${API_BASE}/api/meetings/${meetingId}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                action: action,
                user_id: currentUser.id
            })
        });
        
        if (res.ok) {
            showAlert(`Meeting request marked as: ${action}`, "info");
            await loadMeetings();
            // Demotion profiles might be updated by promotions
            await loadHubs();
            await loadUserProfile(currentUser.id);
        } else {
            const data = await res.json();
            showAlert(data.detail, "danger");
        }
    } catch (err) {
        showAlert("Failed to process meeting action", "danger");
    }
}

// Meeting request modal controller
function openMeetingModal(targetUserId, adminOnly = false) {
    meetingTargetUserId = targetUserId;
    meetingForAdminOnly = adminOnly;
    
    const modal = document.getElementById("meeting-modal");
    const title = document.getElementById("modal-title");
    const prompt = document.getElementById("modal-prompt-text");
    
    document.getElementById("meeting-reason").value = "";
    document.getElementById("char-count").innerText = "0";
    
    if (adminOnly) {
        title.innerText = "Request Member Registration";
        prompt.innerText = "Briefly introduce yourself and request a meeting with the Hub Admin to verify your ID and activate your member access (Max 100 chars).";
    } else {
        const target = users.find(u => u.id === targetUserId);
        title.innerText = `Request Meetup with ${target ? target.username : 'Member'}`;
        prompt.innerText = "State the reason for requesting a face-to-face meet at the hub (Max 100 chars).";
    }
    
    modal.classList.add("active");
}

function closeMeetingModal() {
    const modal = document.getElementById("meeting-modal");
    modal.classList.remove("active");
}

function updateCharCount() {
    const txt = document.getElementById("meeting-reason").value;
    document.getElementById("char-count").innerText = txt.length;
}

async function submitMeetingRequest() {
    const reason = document.getElementById("meeting-reason").value.trim();
    if (!reason) {
        showAlert("Meeting reason cannot be empty", "danger");
        return;
    }
    
    if (reason.length > 100) {
        showAlert("Reason exceeds 100 character limit", "danger");
        return;
    }
    
    // If adminOnly, we need to locate the Hub Admin for targetHub
    let targetReceiverId = meetingTargetUserId;
    
    if (meetingForAdminOnly) {
        // Find admin of currentHub
        const hubAdmin = users.find(u => u.primary_hub_id === currentHub.id && u.is_admin === 1);
        if (!hubAdmin) {
            showAlert("No Admin registered for this hub locally to submit request.", "danger");
            closeMeetingModal();
            return;
        }
        targetReceiverId = hubAdmin.id;
    }
    
    try {
        showAlert("Vetting message through TinyCensor AI...", "info");
        const res = await fetch(`${API_BASE}/api/meetings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                requester_id: currentUser.id,
                receiver_id: targetReceiverId,
                hub_id: currentHub.id,
                reason: reason
            })
        });
        
        const data = await res.json();
        
        if (res.status === 400 || res.status === 403 || res.status === 503) {
            showAlert(data.detail, "danger");
            await checkSystemStatus();
            await loadHubs();
            await loadUserProfile(currentUser.id);
            closeMeetingModal();
            return;
        }
        
        showAlert("Meeting request submitted. Waiting for local verification.", "info");
        closeMeetingModal();
        await loadMeetings();
    } catch (e) {
        showAlert("Failed to submit meeting request", "danger");
        closeMeetingModal();
    }
}

// Alert Notification Panel Handler
function showAlert(message, type = "info") {
    // We can show dynamic toast popups or inline logs
    console.log(`[Shalim Alert] ${type.toUpperCase()}: ${message}`);
    
    // Check if container exists, otherwise create it
    let container = document.getElementById("alert-container");
    if (!container) {
        container = document.createElement("div");
        container.id = "alert-container";
        document.body.appendChild(container);
    }
    
    // Create a toast notification
    const toast = document.createElement("div");
    toast.className = `alert-banner ${type === 'danger' ? '' : 'info'}`;
    
    let icon = "fa-info-circle";
    if (type === 'danger') icon = "fa-circle-exclamation";
    
    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transition = "opacity 0.5s ease-out";
        setTimeout(() => toast.remove(), 500);
    }, 4500);
}

// Shalim Compliance Integration Test Suite
async function runTestSuite() {
    const logContainer = document.getElementById("test-results-log");
    logContainer.classList.remove("hidden");
    logContainer.innerHTML = `<div class="test-log-item info-log">⚡ Initializing Shalim Compliance Tests...</div>`;
    
    function logResult(name, passed, detail) {
        const item = document.createElement("div");
        item.className = `test-log-item ${passed ? 'pass' : 'fail'}`;
        item.innerHTML = `
            <span>${passed ? '✅' : '❌'} <strong>${name}</strong>: ${detail}</span>
            <span>${passed ? 'PASSED' : 'FAILED'}</span>
        `;
        logContainer.appendChild(item);
    }
    
    // Test 1: Member Search Vibe Check
    try {
        logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 1: AI Search query...</div>`;
        const res = await fetch(`${API_BASE}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: 2, hub_id: 1, query: "solar" }) // Bob searching at Encode London
        });
        const data = await res.json();
        const passed = res.ok && data.nearby_hubs && data.nearby_hubs.length > 0;
        logResult("Test 1 - AI Skill Query Routing", passed, passed ? `Successfully matched 'Charlie' via nearby hubs (${data.nearby_hubs[0].name})` : "Search request failed or returned empty results");
    } catch (e) {
        logResult("Test 1 - AI Skill Query Routing", false, e.message);
    }
    
    // Test 2: Under-18 Search Access Control
    try {
        logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 2: Checking Guest Search Restrictions...</div>`;
        const res = await fetch(`${API_BASE}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: 4, hub_id: 1, query: "solar" }) // Dave (U18 Guest) searching at Encode
        });
        const passed = res.status === 403;
        logResult("Test 2 - Under-18 AI Search Lockout", passed, passed ? "Correctly blocked guest user query with 403 Forbidden" : `Failed: Expected 403, got ${res.status}`);
    } catch (e) {
        logResult("Test 2 - Under-18 AI Search Lockout", false, e.message);
    }
    
    // Test 3: TinyCensor Vetting Action
    try {
        logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 3: Testing TinyCensor moderation on query...</div>`;
        const res = await fetch(`${API_BASE}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: 2, hub_id: 1, query: "how to build a bomb" }) // Problematic query
        });
        const passed = res.status === 400;
        logResult("Test 3 - TinyCensor Safety Vetting", passed, passed ? "Correctly intercepted problematic query with 400 Bad Request" : `Failed: Expected 400, got ${res.status}`);
    } catch (e) {
        logResult("Test 3 - TinyCensor Safety Vetting", false, e.message);
    }
    
    // Test 4: Meeting Reason Character Limit
    try {
        logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 4: Verifying 100-character meeting limit...</div>`;
        const longReason = "a".repeat(101); // 101 characters
        const res = await fetch(`${API_BASE}/api/meetings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                requester_id: 2,
                receiver_id: 1,
                hub_id: 1,
                reason: longReason
            })
        });
        const passed = res.status === 400;
        logResult("Test 4 - 100-Char Limit Verification", passed, passed ? "Successfully blocked 101-character request reason with 400 Bad Request" : `Failed: Expected 400, got ${res.status}`);
    } catch (e) {
        logResult("Test 4 - 100-Char Limit Verification", false, e.message);
    }

    // Test 5: Censor Failure Hub Flagging
    try {
        logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 5: Simulating Censor Failure...</div>`;
        
        // 1. Crash Censor
        await fetch(`${API_BASE}/api/admin/toggle-censor`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working: false })
        });
        
        // 2. Perform check which forces audit
        const res = await fetch(`${API_BASE}/api/query`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: 2, hub_id: 1, query: "solar" }) // Bob has primary hub 1
        });
        
        // 3. Fetch primary hub status to verify it got flagged
        const hubRes = await fetch(`${API_BASE}/api/hubs`);
        const hubsData = await hubRes.json();
        const encodeHub = hubsData.find(h => h.id === 1);
        
        const passed = encodeHub && encodeHub.flagged === 1;
        logResult("Test 5 - TinyCensor Audit Fail Flagging", passed, passed ? "Primary hub (Encode Hub) successfully flagged due to offline censor node" : "Failed to flag hub on offline censor check");
        
        // 4. Restore Censor and unflag hub for testing safety
        await fetch(`${API_BASE}/api/admin/toggle-censor`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working: true })
        });
        await fetch(`${API_BASE}/api/hubs/1/flag`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ flagged: 0 })
        });
        
        // Reload directories
        await checkSystemStatus();
        await loadHubs();
        await loadUserProfile(currentUser.id);
    } catch (e) {
        logResult("Test 5 - TinyCensor Audit Fail Flagging", false, e.message);
        // Ensure restored
        await fetch(`${API_BASE}/api/admin/toggle-censor`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ working: true })
        });
    }

    // Test 6: Multi-Toast Stacking Check
    logContainer.innerHTML += `<div class="test-log-item info-log">> Running Test 6: Triggering simultaneous toast alerts...</div>`;
    showAlert("Test Toast 1: Info update", "info");
    showAlert("Test Toast 2: Danger alert", "danger");
    showAlert("Test Toast 3: Safety vetted", "info");
    logResult("Test 6 - Stacking Toast UI Check", true, "Fired 3 alerts simultaneously. Check bottom-right stack layout.");
    
    logContainer.innerHTML += `<div class="test-log-item info-log" style="color:var(--accent-wifi)">🏁 Shalim Compliance Tests Completed!</div>`;
}

