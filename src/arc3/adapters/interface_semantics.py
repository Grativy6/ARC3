"""Source-bound interface facts granted by the official competition documentation."""

from __future__ import annotations

from dataclasses import dataclass

from arc3.types import ActionName, JSONValue


@dataclass(frozen=True, slots=True)
class InterfaceSemantics:
    """Documented action intents that are not gameplay observations."""

    source_url: str
    source_commit: str
    source_blob: str
    source_sha256: str
    translations: tuple[tuple[ActionName, tuple[int, int]], ...]
    undo_action: ActionName
    evidence_driven_actions: tuple[ActionName, ...]

    def translation_for(self, action: ActionName) -> tuple[int, int] | None:
        """Return the documented directional intent, if one is granted."""

        return next((delta for handle, delta in self.translations if handle is action), None)

    def is_granted(self, action: ActionName) -> bool:
        """Return whether the interface grants a fixed role for this handle."""

        return self.translation_for(action) is not None or action is self.undo_action

    def to_dict(self) -> dict[str, JSONValue]:
        """Return a canonical, source-identifiable trace projection."""

        return {
            "evidence_driven_actions": [item.value for item in self.evidence_driven_actions],
            "source_blob": self.source_blob,
            "source_commit": self.source_commit,
            "source_sha256": self.source_sha256,
            "source_url": self.source_url,
            "translations": {
                action.value: [delta[0], delta[1]] for action, delta in self.translations
            },
            "undo_action": self.undo_action.value,
        }


OFFICIAL_COMPETITION_INTERFACE = InterfaceSemantics(
    source_url="https://docs.arcprize.org/actions",
    source_commit="a5dfc0b64c625fb4a19cf074af845ebe0bb88ff8",
    source_blob="2ebe7dc536e07aabf4f52727e6012ca0df485c30",
    source_sha256="sha256:a0125637f035b1f4e5f445ec939d0cce848e1b95b310fe1afb34b14421667662",
    translations=(
        (ActionName.ACTION1, (0, -1)),
        (ActionName.ACTION2, (0, 1)),
        (ActionName.ACTION3, (-1, 0)),
        (ActionName.ACTION4, (1, 0)),
    ),
    undo_action=ActionName.ACTION7,
    evidence_driven_actions=(ActionName.ACTION5, ActionName.ACTION6),
)


__all__ = ["OFFICIAL_COMPETITION_INTERFACE", "InterfaceSemantics"]
