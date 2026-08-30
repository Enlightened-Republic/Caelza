from __future__ import annotations

PLACEHOLDER = "«redacted»"


class Redactor:
    def __init__(self, secrets):
        self.secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        for s in self.secrets:
            text = text.replace(s, PLACEHOLDER)
        return text

    def scrub_obj(self, obj):
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, list):
            return [self.scrub_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        return obj
