from dataclasses import dataclass

@dataclass
class Card:
    uuid: str
    id: str
    name: str
    type: str
    rarity: str
    cost: int
    upgrades: int
    is_playable: bool
    has_target: bool
    exhausts: bool
    ethereal: bool

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            uuid=data["uuid"],
            id=data["id"],
            name=data["name"],
            type=data["type"],
            rarity=data["rarity"],
            cost=data["cost"],
            upgrades=data["upgrades"],
            is_playable=data["is_playable"],
            has_target=data["has_target"],
            exhausts=data["exhausts"],
            ethereal=data["ethereal"],
        )