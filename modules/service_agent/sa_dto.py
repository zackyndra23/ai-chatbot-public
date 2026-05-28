from pydantic import BaseModel
from typing import List

class CrispPickerChoice(BaseModel):
    value: str
    label: str
    selected: bool = False

class CrispPickerContent(BaseModel):
    id: str
    text: str
    choices: List[CrispPickerChoice]

class CrispPickerMessage(BaseModel):
    type: str = "picker"
    content: CrispPickerContent
    from_: str = "operator"  # "from" reserved in Python
    origin: str = "chat"