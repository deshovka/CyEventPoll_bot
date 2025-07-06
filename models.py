from pydantic import BaseModel, field_validator
from datetime import datetime
from dateutil import parser
from typing import Optional
import pytz

class Event(BaseModel):
    title: str
    description: str
    date: str
    image_id: Optional[str] = None

    @field_validator("title")
    def validate_title(cls, value):
        if len(value) > 100:
            raise ValueError("Название события не должно превышать 100 символов")
        if len(value.strip()) == 0:
            raise ValueError("Название события не может быть пустым")
        return value

    @field_validator("description")
    def validate_description(cls, value):
        if len(value) > 1000:
            raise ValueError("Описание события не должно превышать 1000 символов")
        if len(value.strip()) == 0:
            raise ValueError("Описание события не может быть пустым")
        return value

    @field_validator("date")
    def validate_date(cls, value):
        try:
            # Parse the date and make it offset-aware with EET timezone
            parsed_date = parser.parse(value, dayfirst=True)
            eet_timezone = pytz.timezone("EET")
            # If parsed_date is naive, localize it to EET
            if parsed_date.tzinfo is None:
                parsed_date = eet_timezone.localize(parsed_date)
            current_date = datetime.now(eet_timezone)
            if parsed_date < current_date:
                raise ValueError("Дата события должна быть в будущем")
            return value
        except ValueError as e:
            if "Дата события" in str(e):
                raise
            raise ValueError("Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")