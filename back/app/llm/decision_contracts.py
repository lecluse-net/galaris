"""Provider-neutral closed-choice decisions; probabilities are never fabricated."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] = Field(min_length=1, max_length=255)


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, Probability] | None = None
    confidence: Probability | None = None


class DecisionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: dict[str, str]


class DecisionResult(BaseModel):
    schema_version: Literal["galaris.decision-result/v1"] = "galaris.decision-result/v1"
    answers: dict[str, ChoiceAnswer]
    source: Literal["specialized", "text"] = "specialized"
    model: str
    fallback_reason: str | None = None

    def validate_questions(self, questions: dict[str, ChoiceQuestion]) -> None:
        if self.answers.keys() != questions.keys():
            raise ValueError("Decision response questions do not match the request.")
        for key, answer in self.answers.items():
            options = questions[key].criteria
            if answer.choice not in options:
                raise ValueError("Decision response selected an unavailable option.")
            probabilities = answer.probabilities
            if probabilities is not None and (
                probabilities.keys() != options.keys()
                or abs(sum(probabilities.values()) - 1) > 0.02
            ):
                raise ValueError("Invalid decision probability distribution.")


class DecisionUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ProviderDecisionResponse(BaseModel):
    model: str
    answers: dict[str, ChoiceAnswer]
    usage: DecisionUsage = Field(default_factory=DecisionUsage)
    id: str | None = None


class DecisionUnavailable(RuntimeError):
    """Recoverable provider failure; cancellation and access refusal never use this."""
