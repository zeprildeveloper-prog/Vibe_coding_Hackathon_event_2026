import json
import logging
import re

logger = logging.getLogger("shalim.query")

# A dictionary mapping keywords to derived skills for high-fidelity fallback collation
MOCK_SKILL_DATABASE = {
    "permaculture": ["Agriculture", "Organic Gardening", "Soil Science", "Sustainable Farming"],
    "garden": ["Agriculture", "Gardening", "Botany", "Composting"],
    "soil": ["Agriculture", "Soil Science", "Composting"],
    "electrical": ["Electrical Engineering", "Wiring", "Power Systems", "Solar Power Setup"],
    "wiring": ["Electrical Engineering", "Wiring", "Home Maintenance"],
    "solar": ["Solar Power Setup", "Renewable Energy", "Electrical Engineering", "Battery Storage"],
    "battery": ["Battery Storage", "Electronics Repair", "Power Systems"],
    "radio": ["Ham Radio", "LoRa Communication", "RF Engineering", "Emergency Signaling"],
    "lora": ["LoRa Communication", "Mesh Networking", "IoT Programming"],
    "mesh": ["Mesh Networking", "LoRa Communication", "Network Topology"],
    "medical": ["First Aid", "Emergency Medicine", "Wound Care", "CPR"],
    "first aid": ["First Aid", "CPR", "Emergency Medicine"],
    "wound": ["Wound Care", "First Aid", "Hygiene"],
    "carpentry": ["Woodworking", "Construction", "Structural Repair", "Tool Handling"],
    "wood": ["Woodworking", "Carpentry", "Fuel Management"],
    "water": ["Water Purification", "Plumbing", "Rainwater Harvesting", "Sanitation"],
    "plumbing": ["Plumbing", "Water Purification", "Structural Repair"],
    "filter": ["Water Purification", "Sanitation"],
    "generator": ["Generator Maintenance", "Small Engine Repair", "Mechanical Engineering", "Fuel Management"],
    "engine": ["Small Engine Repair", "Mechanical Engineering", "Auto Repair"],
    "weld": ["Welding", "Metalworking", "Structural Repair"],
}

class QwenQueryLayer:
    def __init__(self):
        self.model_name = "Qwen/Qwen2.5-1.5B-Instruct"
        self.tokenizer = None
        self.model = None
        self.initialized = False
        
    def initialize(self):
        try:
            logger.info(f"Loading Qwen2.5-1.5B-Instruct ({self.model_name})...")
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float32,
                low_cpu_mem_usage=True,
                device_map="cpu"
            )
            self.initialized = True
            logger.info("Qwen2.5-1.5B loaded successfully on CPU.")
        except Exception as e:
            logger.warning(f"Failed to load Qwen2.5-1.5B: {e}. Running in Resilient Fallback Mode.")
            self.initialized = False

    def derive_skills_from_resource(self, title: str, description: str) -> list:
        """
        Derives a list of skills from a resource's title and description.
        Uses Qwen2.5 if loaded, otherwise falls back to smart semantic matching.
        """
        text_to_analyze = f"{title} {description}".lower()
        
        # 1. Try Qwen2.5 if initialized
        if self.initialized and self.model and self.tokenizer:
            try:
                import torch
                prompt = (
                    f"You are Shalim AI. Extract a list of up to 4 core physical/practical skills "
                    f"that a person could acquire or practice using this resource: '{title}' ({description}). "
                    f"Respond ONLY with a JSON array of strings, e.g. [\"First Aid\", \"Gardening\"]. "
                    f"Do not write conversational text."
                )
                messages = [{"role": "user", "content": prompt}]
                text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                model_inputs = self.tokenizer([text], return_tensors="pt").to("cpu")
                
                generated_ids = self.model.generate(
                    **model_inputs,
                    max_new_tokens=64,
                    temperature=0.1
                )
                generated_ids = [
                    output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
                ]
                response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
                
                # Try to parse the JSON array
                skills = json.loads(response.strip())
                if isinstance(skills, list):
                    return [str(s).title() for s in skills]
            except Exception as e:
                logger.error(f"Qwen skill derivation error: {e}. Falling back...")
        
        # 2. Resilient semantic fallback
        derived = set()
        for key, skills in MOCK_SKILL_DATABASE.items():
            if key in text_to_analyze:
                for skill in skills:
                    derived.add(skill)
        
        # Default skill if nothing matches
        if not derived:
            derived.add("General Maintenance")
            
        return list(derived)

    def match_query(self, query: str, members: list, hubs: list) -> dict:
        """
        Matches a naturalistic user query against a list of members' skills and hubs.
        Returns:
            dict: {
                "matched_members": [{"user_id": int, "username": str, "skills": list, "match_reason": str}],
                "nearby_hubs": [{"hub_id": int, "name": str, "distance": float, "skills": list}]
            }
        """
        query_lower = query.lower()
        
        # 1. Try Qwen2.5 if initialized
        if self.initialized and self.model and self.tokenizer:
            try:
                import torch
                members_data = [{"id": m["id"], "username": m["username"], "skills": m["skills"]} for m in members]
                hubs_data = [{"id": h["id"], "name": h["name"], "distance": h["distance"], "skills": h["skills"]} for h in hubs]
                
                prompt = (
                    f"You are Shalim AI. Answer a local community search query: '{query}'.\n"
                    f"Here are the available hub members and their skills: {json.dumps(members_data)}\n"
                    f"Here are nearby hubs with their skills and distances: {json.dumps(hubs_data)}\n"
                    f"Select the members who have skills relevant to the query. If none, select the closest hubs that have relevant skills.\n"
                    f"Respond ONLY with a JSON object in this format:\n"
                    f"{{\n"
                    f"  \"matched_member_ids\": [list of integer IDs],\n"
                    f"  \"matched_hub_ids\": [list of integer IDs]\n"
                    f"}}\n"
                    f"Do not write conversational text."
                )
                
                messages = [{"role": "user", "content": prompt}]
                text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                model_inputs = self.tokenizer([text], return_tensors="pt").to("cpu")
                
                generated_ids = self.model.generate(
                    **model_inputs,
                    max_new_tokens=128,
                    temperature=0.1
                )
                generated_ids = [
                    output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
                ]
                response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
                
                result = json.loads(response.strip())
                matched_member_ids = result.get("matched_member_ids", [])
                matched_hub_ids = result.get("matched_hub_ids", [])
                
                matched_members = []
                for m in members:
                    if m["id"] in matched_member_ids:
                        matched_members.append({
                            "user_id": m["id"],
                            "username": m["username"],
                            "skills": m["skills"],
                            "match_reason": f"AI matched skills for query '{query}'"
                        })
                
                nearby_hubs = []
                for h in hubs:
                    if h["id"] in matched_hub_ids:
                        nearby_hubs.append({
                            "hub_id": h["id"],
                            "name": h["name"],
                            "distance": h["distance"],
                            "skills": h["skills"]
                        })
                        
                return {"matched_members": matched_members, "nearby_hubs": nearby_hubs}
            except Exception as e:
                logger.error(f"Qwen query matching error: {e}. Falling back...")
                
        # 2. Resilient semantic fallback (checks keyword intersection)
        matched_members = []
        
        # Identify key skill categories based on query
        matching_categories = []
        for key, skills in MOCK_SKILL_DATABASE.items():
            if key in query_lower:
                matching_categories.extend(skills)
                
        # Fallback keyword match in user profile skills
        for m in members:
            match_reasons = []
            for skill in m["skills"]:
                # Check direct word overlap or category match
                if any(word in skill.lower() for word in query_lower.split() if len(word) > 3) or skill in matching_categories:
                    match_reasons.append(skill)
                    
            if match_reasons:
                matched_members.append({
                    "user_id": m["id"],
                    "username": m["username"],
                    "skills": m["skills"],
                    "match_reason": f"Matches skills: {', '.join(match_reasons)}"
                })
                
        # If no members matched, search other hubs
        nearby_hubs = []
        if not matched_members:
            for h in hubs:
                hub_matched_skills = []
                for skill in h["skills"]:
                    if any(word in skill.lower() for word in query_lower.split() if len(word) > 3) or skill in matching_categories:
                        hub_matched_skills.append(skill)
                if hub_matched_skills:
                    nearby_hubs.append({
                        "hub_id": h["id"],
                        "name": h["name"],
                        "distance": h["distance"],
                        "skills": hub_matched_skills
                    })
            # Sort hubs by distance
            nearby_hubs = sorted(nearby_hubs, key=lambda x: x["distance"])
            
        return {
            "matched_members": matched_members,
            "nearby_hubs": nearby_hubs
        }

query_layer = QwenQueryLayer()
