from dataclasses import dataclass


@dataclass
class ResultInDTO:
    jobid: str
    prompt: str

    def to_dict(self) -> dict:
        return {
            "jobid": self.jobid,
            "prompt": self.prompt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResultInDTO":
        jobid = data.get("jobid")
        prompt = data.get("prompt")

        if not isinstance(jobid, str) or not jobid.strip():
            raise ValueError("jobid is required and must be a string")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")

        return cls(jobid=jobid, prompt=prompt)
