from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator


class IncidentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class AcknowledgeIncident(IncidentAction):
    action: Literal["acknowledge"]


class ResolveIncident(IncidentAction):
    action: Literal["resolve"]
    disposition: Literal["confirmed_incident", "false_positive"]
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    window_from: AwareDatetime
    window_to: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self):
        if self.window_from >= self.window_to:
            raise ValueError("window_from must be earlier than window_to")
        return self


IncidentPatch = Annotated[AcknowledgeIncident | ResolveIncident, Field(discriminator="action")]
