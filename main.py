import logging
from datetime import date, time, datetime, timedelta
from functools import cache
from typing import Optional, Iterator, List

import arrow
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}
TIMEOUT = 20
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_FILENAME = "cska.ics"
MATCH_DURATION_MIN = 120
CSKA = "ЦСКА"
SPORTS_RU_HOME = "дома"
VEVENT_TEMPLATE = """
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{created}
DTSTART:{start}
DTEND:{end}
SUMMARY:{summary}
END:VEVENT"""
VCALENDAR_HEADER = """
BEGIN:VCALENDAR
VERSION:2.0"""
VCALENDAR_FOOTER = """
END:VCALENDAR
"""

NOW = datetime.now()


class Match(BaseModel):
    home_team: str
    away_team: str
    date: date
    time: Optional[time]
    tournament: str

    def get_uid(self) -> str:
        return f"{self.tournament}_{self.home_team}_{self.away_team}_{self.date.year}"

    def get_summary(self) -> str:
        return f"{self.home_team} - {self.away_team} ({self.tournament})"

    def in_future(self) -> bool:
        if not self.time:
            return False

        return datetime.combine(self.date, self.time) > NOW


def fetch_html_from_sports_ru() -> Optional[str]:
    url = "https://www.sports.ru/football/club/cska/calendar/"

    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.exception("Failed to load matches from sports.ru")
        return None

    return response.text


def yield_matches_from_sports_ru() -> Iterator[Match]:
    html_text = fetch_html_from_sports_ru()
    if not html_text:
        logger.warning("No html fetched :(")
        return

    soup = BeautifulSoup(html_text, 'html.parser')

    table = soup.find('table', class_='stat-table')
    tbody = table.find('tbody')
    for row in tbody.find_all('tr'):
        cells = row.find_all(['td', "a"])
        row_data = [cell.get_text(strip=True) for cell in cells]

        """
        Structure:
        ['10.02.2026|10:00', 'Winline Зимний кубок РПЛ', 'Зенит', 'В гостях']
        ['18.02.2026', 'Товарищеские матчи (клубы)', 'Ростов', 'Дома']
        """

        dt, tournament, team, away = row_data[0], row_data[2], row_data[5], row_data[6]
        if "|" in dt:
            match_date, match_time = dt.split("|")
        else:
            match_date, match_time = dt, None

        match_date = f"{match_date[6:]}-{match_date[3:5]}-{match_date[:2]}"

        if away.lower() == SPORTS_RU_HOME:
            home_team = CSKA
            away_team = team
        else:
            home_team = team
            away_team = CSKA

        try:
            match = Match(
                home_team=home_team,
                away_team=away_team,
                date=match_date,
                time=match_time,
                tournament=tournament
            )
        except ValidationError as e:
            logger.exception("Parsing error: %s", row_data)
            continue

        logger.debug("Match: %s", match)
        yield match


def get_datetime_text(dt: datetime, tz_name: str = DEFAULT_TIMEZONE) -> str:
    naive_in_utc = arrow.get(dt, tz_name).to("UTC").naive
    return naive_in_utc.strftime("%Y%m%dT%H%M%SZ")


@cache
def get_now_text() -> str:
    return get_datetime_text(NOW)


def generate_vevent_text(match: Match) -> str:
    assert match.time, "No time in Match"

    start = datetime.combine(match.date, match.time)
    end = start + timedelta(minutes=MATCH_DURATION_MIN)

    return VEVENT_TEMPLATE.format(
        uid=match.get_uid(),
        created=get_now_text(),
        start=get_datetime_text(start),
        end=get_datetime_text(end),
        summary=match.get_summary()
    )


def generate_vcalendar_text(matches: List[Match]) -> str:
    body = "".join(generate_vevent_text(match) for match in matches)
    return f"{VCALENDAR_HEADER}{body}{VCALENDAR_FOOTER}"


def save_to_file(text: str, filename: str = DEFAULT_FILENAME) -> None:
    with open(filename, "w") as f:
        f.write(text)


def main() -> None:
    matches = [match for match in yield_matches_from_sports_ru() if match.in_future()]
    text = generate_vcalendar_text(matches)
    save_to_file(text)
    logger.info("Done")


if __name__ == '__main__':
    main()
