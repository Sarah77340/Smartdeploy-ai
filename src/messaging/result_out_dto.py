from dataclasses import dataclass, asdict


@dataclass
class ResultOutDTO:
    jobid: str
    name: str
    path: str
    lang: str
    preview: str
    size: int

    def to_dict(self) -> dict:
        return asdict(self)
