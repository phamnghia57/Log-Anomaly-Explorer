"""Bounded TF-IDF augmentation; exact rule groups remain the fallback."""
import json
import logging
import math
import os
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class TfidfAugmenter:
    def __init__(self, state_path, *, threshold=0.9, margin=0.05, max_templates=2000):
        if not (math.isfinite(threshold) and 0 < threshold <= 1
                and math.isfinite(margin) and 0 <= margin <= 1 and max_templates > 0):
            raise ValueError("Invalid ML similarity threshold, margin or template limit")
        self.state_path = Path(state_path)
        self.threshold = threshold
        self.margin = margin
        self.max_templates = max_templates

    @staticmethod
    def _guards(text):
        # Preserve explicit exception classes and numeric error/status codes.
        return (tuple(sorted(re.findall(r'\b\w*(?:error|exception)\b', text.lower()))),
                tuple(sorted(re.findall(r'\b(?:code|status)\s*[:=]?\s*(\d+)\b', text.lower()))))

    def map_groups(self, groups):
        """Return stable key mappings, or identity for the entire failed operation.

        The state file belongs to one worker. Existing assignments never change.
        A policy change should use a new state path and rebuilt historical baseline.
        """
        identity = {key: key for key in groups}
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            import numpy as np

            state = {"version": 1, "services": {}}
            if self.state_path.exists():
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state["version"] != 1 or not isinstance(state["services"], dict):
                raise ValueError("Unsupported ML state")
            services = state["services"]
            count = sum(len(templates) for templates in services.values())
            new_count = sum(signature not in services.get(service, {}) for service, signature in groups)
            if count + new_count > self.max_templates:
                raise ValueError("ML template budget exceeded")
            result = {}
            for service in sorted({key[0] for key in groups}):
                known = services.setdefault(service, {})
                if any(not isinstance(k, str) or not isinstance(v, str) or v not in known
                       or known[v] != v for k, v in known.items()):
                    raise ValueError("Invalid canonical mapping")
                signatures = sorted(key[1] for key in groups if key[0] == service)
                # Compute guards once per log, rather than rescanning every group
                # for every candidate/template pair.
                guards = {signature: {self._guards(log.get("message", ""))
                                      for log in groups[(service, signature)]}
                          for signature in signatures}
                canonical_guards = {}
                for signature in signatures:
                    canonical_guards.setdefault(known.get(signature, signature), set()).update(guards[signature])
                unseen = [s for s in signatures if s not in known]
                representatives = sorted(set(known.values()))
                documents = sorted(set(representatives + unseen))
                if unseen and documents:
                    matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                             max_features=20000, dtype=np.float32
                                             ).fit_transform(documents)
                    rows = {text: i for i, text in enumerate(documents)}
                    for signature in unseen:
                        candidates = [r for r in representatives
                                      if len(guards[signature]) == 1
                                      and guards[signature] == canonical_guards.get(r, set())]
                        canonical = signature
                        if candidates:
                            scores = (matrix[[rows[signature]]] @
                                      matrix[[rows[r] for r in candidates]].T).toarray()[0]
                            ranked = sorted(zip(scores, candidates), key=lambda item: (-item[0], item[1]))
                            best, candidate = ranked[0]
                            runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
                            if best >= self.threshold and best - runner_up >= self.margin:
                                canonical = candidate
                        known[signature] = canonical
                        canonical_guards.setdefault(canonical, set()).update(guards[signature])
                        if canonical == signature:
                            representatives.append(signature)
                for signature in signatures:
                    result[(service, signature)] = (service, known[signature])
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.state_path)
            return result
        except Exception:
            logger.warning("ML augmentation unavailable; using rule groups", exc_info=True)
            return identity
