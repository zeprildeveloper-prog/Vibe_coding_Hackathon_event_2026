import re
import os
import logging
import httpx

logger = logging.getLogger("shalim.censor")

# Setup default rule-based censor list
PROBLEMATIC_KEYWORDS = [
    r"\bweapon(s)?\b", r"\bbomb(s)?\b", r"\bexplosive(s)?\b",
    r"\bterrorist(s)?\b", r"\bterrorism\b", r"\bdrug(s)?\b",
    r"\bcocaine\b", r"\bheroin\b", r"\bmeth\b",
    r"\bkill\b", r"\bmurder\b", r"\battack\b",
    r"\bpaedophile(s)?\b", r"\bpedophile(s)?\b", r"\bchild abuse\b"
]

class CensorModel:
    def __init__(self):
        self.pipeline = None
        self.model_name = "facebook/roberta-hate-speech-dynabench-to-decisive-sensation"
        self.initialized = False
        self.use_api = False
        self.api_token = None
        
    def initialize(self):
        # Check if Hugging Face API token is provided in the environment
        self.api_token = os.getenv("HF_API_TOKEN") or os.getenv("HF_TOKEN")
        
        if self.api_token:
            logger.info("HF_API_TOKEN detected. Configuring TinyCensor to use Hugging Face Serverless Inference API (Cloud).")
            self.use_api = True
            self.initialized = True
            return

        try:
            logger.info(f"Loading TinyCensor RoBERTa model ({self.model_name}) locally on CPU...")
            from transformers import pipeline
            self.pipeline = pipeline("text-classification", model=self.model_name, device=-1) # -1 is CPU
            self.initialized = True
            logger.info("TinyCensor RoBERTa model loaded successfully locally.")
        except Exception as e:
            logger.warning(f"Failed to load TinyCensor RoBERTa model locally: {e}. Falling back to rule-based Censor.")
            self.pipeline = None
            self.initialized = False

    def check_text(self, text: str) -> dict:
        """
        Checks if text contains problematic content.
        Returns:
            dict: {"is_problematic": bool, "score": float, "method": str, "reason": str}
        """
        if not text or not text.strip():
            return {"is_problematic": False, "score": 0.0, "method": "none", "reason": "Empty text"}

        # Always check rule-based first for high-confidence flags (speed & fallback safety)
        for pattern in PROBLEMATIC_KEYWORDS:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"TinyCensor Rule-based Match: Found problematic pattern matching '{pattern}' in text.")
                return {
                    "is_problematic": True,
                    "score": 1.0,
                    "method": "rules",
                    "reason": f"Flagged by safety rules (matched keyword pattern)"
                }

        # 1. Use Hugging Face Inference API if configured
        if self.use_api and self.api_token:
            try:
                headers = {"Authorization": f"Bearer {self.api_token}"}
                api_url = f"https://api-inference.huggingface.co/models/{self.model_name}"
                
                response = httpx.post(api_url, headers=headers, json={"inputs": text}, timeout=10.0)
                if response.status_code == 200:
                    res = response.json()
                    
                    # Unpack list of lists if returned
                    if isinstance(res, list) and len(res) > 0:
                        if isinstance(res[0], list):
                            res = res[0]
                        
                        is_problematic = False
                        max_hate_score = 0.0
                        label_name = "nothate"
                        
                        for pred in res:
                            label = pred.get("label", "").lower()
                            score = float(pred.get("score", 0.0))
                            if label in ["hate", "class 1", "label_1"]:
                                max_hate_score = score
                                if score > 0.5:
                                    is_problematic = True
                                    label_name = label
                        
                        if is_problematic:
                            logger.warning(f"TinyCensor API Match: Text flagged with score {max_hate_score:.2f}")
                            return {
                                "is_problematic": True,
                                "score": max_hate_score,
                                "method": "huggingface_api",
                                "reason": f"Flagged by TinyCensor API (hate - {max_hate_score:.1%})"
                            }
                        else:
                            return {
                                "is_problematic": False,
                                "score": 1.0 - max_hate_score,
                                "method": "huggingface_api",
                                "reason": "Passed TinyCensor API checks"
                            }
                else:
                    logger.error(f"HF Inference API returned status {response.status_code}: {response.text}. Using rule-based fallback.")
            except Exception as e:
                logger.error(f"Error during Hugging Face API call: {e}. Using rule-based fallback.")

        # 2. Use Local Pipeline if initialized
        if self.pipeline:
            try:
                res = self.pipeline(text)[0]
                label = res["label"] # label is 'hate' or 'nothate'
                score = res["score"]
                
                is_problematic = label.lower() in ["hate", "class 1", "label_1"]
                
                if is_problematic and score > 0.5:
                    logger.warning(f"TinyCensor RoBERTa Match: Text flagged with score {score:.2f}")
                    return {
                        "is_problematic": True,
                        "score": float(score),
                        "method": "roberta_local",
                        "reason": f"Flagged by TinyCensor Local ({label} - {score:.1%})"
                    }
                else:
                    return {
                        "is_problematic": False,
                        "score": float(score) if is_problematic else 1.0 - float(score),
                        "method": "roberta_local",
                        "reason": "Passed TinyCensor local checks"
                    }
            except Exception as e:
                logger.error(f"Error during local RoBERTa inference: {e}. Using rule-based fallback.")
        
        # Default pass if no matches found
        return {
            "is_problematic": False,
            "score": 0.0,
            "method": "rules",
            "reason": "Passed rules checks"
        }

censor = CensorModel()

