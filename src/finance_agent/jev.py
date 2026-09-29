from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from typesafe_sdk import Question, SystemOneResponse, TypeSafeClient


class JevClient:
    """Single entry point for TypeSafe System One decisions."""

    def __init__(self, client: TypeSafeClient | None = None):
        self.client = client

    def ask(
        self,
        state: dict[str, Any] | list[Any] | str,
        questions: Mapping[str, Question],
    ) -> SystemOneResponse:
        if self.client:
            response = self.client.system_one(state=state, questions=questions)
        else:
            with TypeSafeClient(
                api_key=os.getenv("TYPESAFE_API_KEY"),
                model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
                timeout=10,
            ) as client:
                response = client.system_one(state=state, questions=questions)
        missing = set(questions) - set(response.answers)
        if missing:
            raise ValueError(f"Jev omitted decisions: {sorted(missing)}")
        return response

    def noul_scores(
        self,
        state: dict[str, Any] | list[Any] | str,
        questions: Mapping[str, Question],
    ) -> dict[str, float]:
        response = self.ask(state, questions)
        missing = set(questions) - set(response.nouls)
        if missing:
            raise ValueError(f"Jev returned non-Noul decisions: {sorted(missing)}")
        return {name: response.nouls[name].noul for name in questions}
