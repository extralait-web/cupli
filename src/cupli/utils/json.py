"""JSON encoder/decoder utilities tailored for cupli value types."""

import json
from pathlib import Path


class CupliJsonEncoder(json.JSONEncoder):
    """JSON encoder that serialises :class:`pathlib.Path` as a string."""

    def default(self, o: object) -> object:
        """Stringify ``Path`` instances; delegate other types to the base encoder."""
        if isinstance(o, Path):
            return str(o)
        return super().default(o)
