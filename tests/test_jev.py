import pytest
from typesafe_sdk import Choice, Noul, SystemOneResponse

from finance_agent.jev import JevClient


class FakeClient:
    def __init__(self, answers):
        self.response = SystemOneResponse.model_validate(
            {"model": "jev-test", "usage": {}, "answers": answers}
        )

    def system_one(self, state, questions):
        return self.response


def test_centralized_jev_client_supports_generic_questions_and_noul_scores() -> None:
    client = JevClient(
        FakeClient(
            {
                "relevant": {"type": "noul", "noul": 0.9},
                "topic": {
                    "type": "choice",
                    "choice": "finance",
                    "confidence": 0.8,
                    "probabilities": {"finance": 0.8, "other": 0.2},
                },
            }
        )
    )
    response = client.ask(
        "ledger",
        {
            "relevant": Noul(instructions="Is it relevant?"),
            "topic": Choice(instructions="Topic?", criteria={"finance": None, "other": None}),
        },
    )

    assert response.choices["topic"].choice == "finance"
    assert JevClient(FakeClient({"relevant": {"type": "noul", "noul": 0.9}})).noul_scores(
        "ledger", {"relevant": Noul(instructions="Is it relevant?")}
    ) == {"relevant": 0.9}


def test_centralized_jev_client_rejects_missing_answers() -> None:
    with pytest.raises(ValueError, match="omitted decisions"):
        JevClient(FakeClient({})).ask(
            "ledger", {"relevant": Noul(instructions="Is it relevant?")}
        )
