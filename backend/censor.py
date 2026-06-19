import re
import logging

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
        
    def initialize(self):
        try:
            logger.info(f"Loading TinyCensor RoBERTa model ({self.model_name})...")
            from transformers import pipeline
            # Using hate-speech classification pipeline
            self.pipeline = pipeline("text-classification", model=self.model_name, device=-1) # -1 is CPU
            self.initialized = True
            logger.info("TinyCensor RoBERTa model loaded successfully.")
        except Exception as e:
            logger.warning(f"Failed to load TinyCensor RoBERTa model: {e}. Falling back to rule-based Censor.")
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

        # If RoBERTa model is initialized, use it
        if self.initialized and self.pipeline:
            try:
                res = self.pipeline(text)[0]
                label = res["label"] # label is 'hate' or 'nothate'
                score = res["score"]
                
                # In facebook/roberta-hate-speech, 'hate' means problematic content
                # label 'hate' corresponds to class 1
                is_problematic = label.lower() in ["hate", "class 1", "label_1"]
                
                # If confidence is high enough
                if is_problematic and score > 0.5:
                    logger.warning(f"TinyCensor RoBERTa Match: Text flagged with score {score:.2f}")
                    return {
                        "is_problematic": True,
                        "score": float(score),
                        "method": "roberta",
                        "reason": f"Flagged by TinyCensor AI ({label} - {score:.1%})"
                    }
                else:
                    return {
                        "is_problematic": False,
                        "score": float(score) if is_problematic else 1.0 - float(score),
                        "method": "roberta",
                        "reason": "Passed TinyCensor AI checks"
                    }
            except Exception as e:
                logger.error(f"Error during TinyCensor RoBERTa inference: {e}. Using rule-based fallback pass.")
        
        # Default pass if no matches found
        return {
            "is_problematic": False,
            "score": 0.0,
            "method": "rules",
            "reason": "Passed rules checks"
        }

censor = CensorModel()
