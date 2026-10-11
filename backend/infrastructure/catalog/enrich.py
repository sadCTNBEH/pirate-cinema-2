"""Catalog enrichment, disk cache, and poster caching service."""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from backend.core.settings import get_data_dir
from backend.infrastructure.catalog import cinemeta
from backend.infrastructure.catalog.cinemeta import CinemetaProvider
from backend.infrastructure.catalog.wikidata import WikidataProvider

logger = logging.getLogger(__name__)

IMDB_REGEX = re.compile(r"^tt\d{1,12}$")
DEFAULT_CACHE_TTL = 86400  # 24 hours
DEFAULT_POSTER_TIMEOUT = 8.0
MAX_POSTER_SIZE = 5 * 1024 * 1024  # 5MB


def is_valid_imdb(id_: str | None) -> bool:
    if not id_:
        return False
    return bool(IMDB_REGEX.match(id_.strip()))


# ─── Hardcoded Fallback Lists (Offline / Network Down) ───

FALLBACK_POPULAR_MOVIES: list[dict[str, Any]] = [
    {
        "id": "tt0111161",
        "title": "The Shawshank Redemption",
        "original_title": "The Shawshank Redemption",
        "title_ru": "Побег из Шоушенка",
        "year": 1994,
        "rating": 9.3,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMDAyY2FhYjctNDc5OS00MDNlLThiMGUtY2UxYWVkNGY2ZjljXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.",
        "overview_ru": "Американская драма 1994 года режиссёра Фрэнка Дарабонта по повести Стивена Кинга. Рассказывает историю банкира Энди Дюфрейна, несправедливо осуждённого на пожизненное заключение в тюрьме Шоушенк.",
        "genres": ["Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0068646",
        "title": "The Godfather",
        "original_title": "The Godfather",
        "title_ru": "Крёстный отец",
        "year": 1972,
        "rating": 9.2,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNGEwYjgwOGQtYjg5ZS00Njc1LTk2ZGEtMDRjZWQ3NjFhZTk4XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The aging patriarch of an organized crime dynasty transfers control of his clandestine empire to his reluctant son.",
        "overview_ru": "Эпическая гангстерская драма 1972 года режиссёра Фрэнсиса Форда Копполы по роману Марио Пьюзо о жизни нью-йоркской сицилийской мафиозной семьи Корлеоне.",
        "genres": ["Crime", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0468569",
        "title": "The Dark Knight",
        "original_title": "The Dark Knight",
        "title_ru": "Тёмный рыцарь",
        "year": 2008,
        "rating": 9.0,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMTMxNTMwODM0NF5BMl5BanBnXkFtZTcwODAyMTk2Mw@@._V1_.jpg",
        "poster_local_url": None,
        "overview": "When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests of his ability to fight injustice.",
        "overview_ru": "Супергеройский неонуарный боевик Кристофера Нолана. Бэтмен вместе с лейтенантом Гордоном и прокурором Дентом противостоят гениальному криминальному манипулятору Джокеру.",
        "genres": ["Action", "Crime", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0109830",
        "title": "Forrest Gump",
        "original_title": "Forrest Gump",
        "title_ru": "Форрест Гамп",
        "year": 1994,
        "rating": 8.8,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNDYwNzVjMTItZmU5YS00YjQ5LTljYjgtMjY2NDVmZmUzMzFmXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The history of the United States from the 1950s to the '70s unfolds from the perspective of an Alabama man with an IQ of 75.",
        "overview_ru": "Американский комедийно-драматический фильм 1994 года режиссёра Роберта Земекиса с Томом Хэнксом в главной роли. Картина завоевала шесть премий «Оскар».",
        "genres": ["Drama", "Romance"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0137523",
        "title": "Fight Club",
        "original_title": "Fight Club",
        "title_ru": "Бойцовский клуб",
        "year": 1999,
        "rating": 8.8,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BOTgyOGQ1NDItNGU3Ny00MjU3LTg2YWEtNmEyYjBiMjI1Y2M5XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "An insomniac office worker and a devil-may-care soap maker form an underground fight club that evolves into much more.",
        "overview_ru": "Американский психологический триллер 1999 года режиссёра Дэвида Финчера по роману Чака Паланика. Терзаемый бессонницей клерк знакомится с торговцем мылом Тайлером Дёрденом.",
        "genres": ["Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0133093",
        "title": "The Matrix",
        "original_title": "The Matrix",
        "title_ru": "Матрица",
        "year": 1999,
        "rating": 8.7,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BN2NmN2VhMTQtMDNiOS00NDlhLTliMjgtODE2ZTY0ODQyNDRhXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "When a beautiful stranger leads computer hacker Neo to a forbidding underworld, he discovers the shocking truth about reality.",
        "overview_ru": "Культовый научно-фантастический боевик сестёр Вачовски. Программист Томас Андерсон узнаёт, что привычный мир — иллюзия, созданная машинами.",
        "genres": ["Action", "Sci-Fi"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0167260",
        "title": "The Lord of the Rings: The Return of the King",
        "original_title": "The Lord of the Rings: The Return of the King",
        "title_ru": "Властелин колец: Возвращение короля",
        "year": 2003,
        "rating": 9.0,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMTZkMjBjNWMtZGI5OC00MGU0LTk4ZTItODg2NWM3NTVmNWQ4XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "Gandalf and Aragorn lead the World of Men against Sauron's army to draw his gaze from Frodo and Sam as they approach Mount Doom.",
        "overview_ru": "Заключительная часть трилогии Питера Джексона по роману Толкина, удостоенная 11 премий «Оскар». Битва за Средиземье и судьба Кольца Всевластья.",
        "genres": ["Action", "Adventure", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0110912",
        "title": "Pulp Fiction",
        "original_title": "Pulp Fiction",
        "title_ru": "Криминальное чтиво",
        "year": 1994,
        "rating": 8.9,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BYTViYTE3NWMtPCs2Ni00NzY1LTkyYjMtODQ0MGE3MjYxNWI0XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The lives of two mob hitmen, a boxer, a gangster and his wife, and a pair of diner bandits intertwine in four tales of violence and redemption.",
        "overview_ru": "Культовая криминальная комедия Квентина Тарантино. Несколько нелинейных историй о гангстерах, боксёре и ограблении в закусочной Лос-Анджелеса.",
        "genres": ["Crime", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0816692",
        "title": "Interstellar",
        "original_title": "Interstellar",
        "title_ru": "Интерстеллар",
        "year": 2014,
        "rating": 8.7,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BYzdjMDAxZGItMjI2My00ODA1LTlkNzItOWFjMDU5ZDJlYWY3XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "When Earth becomes uninhabitable in the future, a farmer and ex-NASA pilot is tasked to pilot a spacecraft to find a new home.",
        "overview_ru": "Научно-фантастический фильм Кристофера Нолана о путешествии исследователей через червоточину в поисках нового дома для человечества.",
        "genres": ["Adventure", "Drama", "Sci-Fi"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt1375666",
        "title": "Inception",
        "original_title": "Inception",
        "title_ru": "Начало",
        "year": 2010,
        "rating": 8.8,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMjAxMzY3NjcxNF5BMl5BanBnXkFtZTcwNTI5OTM0Mw@@._V1_.jpg",
        "poster_local_url": None,
        "overview": "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea.",
        "overview_ru": "Научно-фантастический триллер Кристофера Нолана о краже и внедрении идей в подсознание людей через совместные сновидения.",
        "genres": ["Action", "Adventure", "Sci-Fi"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0120737",
        "title": "The Lord of the Rings: The Fellowship of the Ring",
        "original_title": "The Lord of the Rings: The Fellowship of the Ring",
        "title_ru": "Властелин колец: Братство Кольца",
        "year": 2001,
        "rating": 8.9,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNzIxMDQ2YTctNDY4MC00ZTk4LTk4NWUtZWY0Njc2NTJhN2QxXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "A meek Hobbit from the Shire and eight companions set out on a journey to destroy the powerful One Ring.",
        "overview_ru": "Первая часть эпической трилогии Питера Джексона по роману Толкина. Хоббит Фродо отправляется в поход, чтобы уничтожить Кольцо Всевластья в Мордоре.",
        "genres": ["Action", "Adventure", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
    {
        "id": "tt0108052",
        "title": "Schindler's List",
        "original_title": "Schindler's List",
        "title_ru": "Список Шиндлера",
        "year": 1993,
        "rating": 9.0,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNjM1ZDQxYWUtMzQyZS00MTE1LWJmZGYtNGUyNTdlYjM3ZmVmXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "In German-occupied Poland during World War II, industrialist Oskar Schindler gradually becomes concerned for his Jewish workforce.",
        "overview_ru": "Историческая драма Стивена Спилберга о немецком бизнесмене Оскаре Шиндлере, спасшем более тысячи польских евреев во время Холокоста.",
        "genres": ["Biography", "Drama", "History"],
        "background_url": None,
        "source": "fallback",
        "type": "movie",
    },
]

FALLBACK_POPULAR_SERIES: list[dict[str, Any]] = [
    {
        "id": "tt0903747",
        "title": "Breaking Bad",
        "original_title": "Breaking Bad",
        "title_ru": "Во все тяжкие",
        "year": 2008,
        "rating": 9.5,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMzU5ZGYzNmQtMTdhYy00OGRiLTg4YjQtNTkzMmM3NzNcMDkyXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "A chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.",
        "overview_ru": "Американская криминальная драма о школьном учителе химии Уолтере Уайте, который начинает производить метамфетамин ради будущего семьи.",
        "genres": ["Crime", "Drama", "Thriller"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0944947",
        "title": "Game of Thrones",
        "original_title": "Game of Thrones",
        "title_ru": "Игра престолов",
        "year": 2011,
        "rating": 9.2,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMTNhMDJmNmYtNDBlNy00ODU5LWExNGUtNmNmZDNkZjhhMjlkXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "Nine noble families fight for control over the lands of Westeros, while an ancient enemy returns.",
        "overview_ru": "Эпический фэнтези-сериал по циклу романов Джорджа Р. Р. Мартина «Песнь льда и пламени» о борьбе влиятельных домов за Железный трон Вестероса.",
        "genres": ["Action", "Adventure", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt1475582",
        "title": "Sherlock",
        "original_title": "Sherlock",
        "title_ru": "Шерлок",
        "year": 2010,
        "rating": 9.1,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNTQzNGZjNDEtOTMwYi00MzFjLWE2ZTYtYzYxYzMwMjZkMGM5XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "A modern update finds the famous sleuth and his doctor partner solving crime in 21st century London.",
        "overview_ru": "Британский детективный сериал от BBC, переносящий классических персонажей Артура Конан Дойла в современный Лондон XXI века.",
        "genres": ["Crime", "Drama", "Mystery"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0455275",
        "title": "Prison Break",
        "original_title": "Prison Break",
        "title_ru": "Побег",
        "year": 2005,
        "rating": 8.3,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMTg5NzY0MzEwMl5BMl5BanBnXkFtZTcwNDc3ODk2Mw@@._V1_.jpg",
        "poster_local_url": None,
        "overview": "An engineer installs himself in a prison he helped design, in order to save his falsely accused brother from death row.",
        "overview_ru": "Драматический сериал об инженере-строителе Майкле Скофилде, намеренно севшем в тюрьму, чтобы спасти невинно осуждённого брата от смертной казни.",
        "genres": ["Action", "Crime", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0411008",
        "title": "Lost",
        "original_title": "Lost",
        "title_ru": "Остаться в живых",
        "year": 2004,
        "rating": 8.3,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNzFlNTYwYTgtOTU0Zi00MTY2LWJjZDQtNDQyNWFjMjk3NTE3XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The survivors of a plane crash are forced to work together in order to survive on a seemingly deserted tropical island.",
        "overview_ru": "Приключенческий сериал о выживших пассажирах авиарейса 815, потерпевшего крушение на загадочном тропическом острове в Океании.",
        "genres": ["Adventure", "Drama", "Fantasy"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0108778",
        "title": "Friends",
        "original_title": "Friends",
        "title_ru": "Друзья",
        "year": 1994,
        "rating": 8.9,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BOTU2YmM5ZjctOGRhMC00NmE2LTg5ZjEtNjNmOWQ1OGE4MGYwXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "Follows the personal and professional lives of six twenty to thirty-something-year-old friends living in Manhattan.",
        "overview_ru": "Культовый комедийный ситком о жизни, дружбе и романах шестерых неразлучных приятелей на Манхэттене в Нью-Йорке.",
        "genres": ["Comedy", "Romance"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt4574334",
        "title": "Stranger Things",
        "original_title": "Stranger Things",
        "title_ru": "Очень странные дела",
        "year": 2016,
        "rating": 8.7,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMjg2NmM0NWUtZjgyNi00NmFkLTgyZjktNDEzOWYxZDY3NGMxXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "When a young boy vanishes, a small town uncovers a mystery involving secret experiments and terrifying supernatural forces.",
        "overview_ru": "Фантастический сериал братьев Даффер о таинственных событиях в городке Хоукинс 1980-х годов, секретных лабораториях и потусторонней Изнанке.",
        "genres": ["Drama", "Fantasy", "Horror"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0974015",
        "title": "Chernobyl",
        "original_title": "Chernobyl",
        "title_ru": "Чернобыль",
        "year": 2019,
        "rating": 9.3,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNTEzNjBiMTctYmNmNi00Zjc1LTgyZTItNTAzMWQ0MmYwNDk2XkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "In April 1986, an explosion at the Chernobyl nuclear power plant becomes one of the world's worst man-made catastrophes.",
        "overview_ru": "Исторический мини-сериал HBO о катастрофе на Чернобыльской АЭС в 1986 году, ликвидаторах последствий взрыва и сокрытии правды.",
        "genres": ["Drama", "History", "Thriller"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0306414",
        "title": "The Wire",
        "original_title": "The Wire",
        "title_ru": "Прослушка",
        "year": 2002,
        "rating": 9.3,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BZmY5ZDMxODEtNWIwOS00NjdkLTkyMjktNWRjMDhmYjJjN2RmXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The Baltimore drug scene, as seen through the eyes of drug dealers and law enforcement.",
        "overview_ru": "Глубокая криминальная драма Дэвида Саймона о борьбе полиции с наркоторговлей и системных проблемах американского Балтимора.",
        "genres": ["Crime", "Drama", "Thriller"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt0238784",
        "title": "Band of Brothers",
        "original_title": "Band of Brothers",
        "title_ru": "Братья по оружию",
        "year": 2001,
        "rating": 9.4,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BMTI3ODc2ODc0M15BMl5BanBnXkFtZTYwMTgzOTE5._V1_.jpg",
        "poster_local_url": None,
        "overview": "The story of Easy Company of the U.S. Army 101st Airborne Division and their mission in World War II Europe.",
        "overview_ru": "Военный драматический мини-сериал Стивена Спилберга и Тома Хэнкса о боевом пути роты «Easy» 101-й воздушно-десантной дивизии США во Второй мировой войне.",
        "genres": ["Action", "Drama", "History"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt2560140",
        "title": "Attack on Titan",
        "original_title": "Attack on Titan",
        "title_ru": "Атака титанов",
        "year": 2013,
        "rating": 9.1,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BNDFjYTIxMjctYTQ2ZC00OGQ4LWE3OGYtNDdiMzNiNDZlMDAwXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "After his hometown is destroyed, young Eren Jaeger vows to cleanse the earth of the giant humanoid Titans.",
        "overview_ru": "Постапокалиптический аниме-сериал о борьбе последних уцелевших людей, укрытых за гигантскими стенами, против плотоядных титанов-великанов.",
        "genres": ["Animation", "Action", "Adventure"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
    {
        "id": "tt3032476",
        "title": "Better Call Saul",
        "original_title": "Better Call Saul",
        "title_ru": "Лучше звоните Солу",
        "year": 2015,
        "rating": 9.0,
        "poster_url": "https://m.media-amazon.com/images/M/MV5BZDA4YmE0OTYtMmRmNS00Mzk2LTlhM2MtNjk4NzBjZGE1MmIyXkEyXkFqcGc@._V1_.jpg",
        "poster_local_url": None,
        "overview": "The trials and tribulations of criminal lawyer Jimmy McGill before his fateful run-in with Walter White and Jesse Pinkman.",
        "overview_ru": "Криминальная драма, спин-офф сериала «Во все тяжкие». Превращение мелкого адвоката Джимми Макгилла в беспринципного Сола Гудмана.",
        "genres": ["Crime", "Drama"],
        "background_url": None,
        "source": "fallback",
        "type": "series",
    },
]


def resolve_local_poster_url(
    imdb_id: str | None, posters_dir: Path | None = None
) -> str | None:
    """Return local API URL if poster exists on disk, otherwise None."""
    if not is_valid_imdb(imdb_id):
        return None
    p_dir = posters_dir or (get_data_dir() / "posters" / "catalog")
    target = p_dir / f"{imdb_id}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return f"/api/posters/catalog/{imdb_id}.jpg"
    if posters_dir is None:
        legacy_target = get_data_dir() / "cache" / "popular" / f"{imdb_id}.jpg"
        if legacy_target.is_file() and legacy_target.stat().st_size > 0:
            return f"/api/posters/catalog/{imdb_id}.jpg"
    return None


def _resolve_items_posters(
    items: list[dict[str, Any]], posters_dir: Path | None = None
) -> None:
    """Update poster_local_url in-place for all items based on disk availability, and ensure remote fallback is 350px."""
    p_dir = posters_dir or (get_data_dir() / "posters" / "catalog")
    for item in items:
        item["poster_local_url"] = resolve_local_poster_url(item.get("id"), p_dir)
        p_url = item.get("poster_url")
        if p_url and isinstance(p_url, str) and "m.media-amazon.com" in p_url and "._V1_" in p_url:
            item["poster_url"] = re.sub(r"\._V1_.*?\.jpg", "._V1_QL75_UX350_.jpg", p_url)


# ─── Metadata Helpers (IMDb CDN & Wikipedia) ───


async def fetch_imdb_poster_url(client: httpx.AsyncClient, imdb_id: str) -> str | None:
    """Query IMDb official Suggest API for high-resolution CloudFront CDN poster."""
    if not is_valid_imdb(imdb_id):
        return None
    try:
        first_char = imdb_id[0].lower()
        url = f"https://sg.media-imdb.com/suggests/{first_char}/{imdb_id}.json"
        r = await client.get(url, timeout=4.0)
        if r.status_code == 200:
            m = re.search(r"\(({.*})\)", r.text)
            if m:
                d = json.loads(m.group(1)).get("d", [])
                if d and isinstance(d, list) and "i" in d[0]:
                    img = d[0]["i"][0]
                    if isinstance(img, str) and img.startswith("http"):
                        return img
    except Exception as e:
        logger.debug("IMDb suggest query error for %s: %s", imdb_id, e)
    return None


async def fetch_wikipedia_summaries(
    client: httpx.AsyncClient, ru_titles: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Query Russian Wikipedia for introductory plot extract and image."""
    if not ru_titles:
        return {}

    query_parts = []
    title_to_id: dict[str, str] = {}
    for imdb_id, title in ru_titles.items():
        if not title:
            continue
        clean_t = title.strip()
        query_parts.extend([clean_t, f"{clean_t} (фильм)", f"{clean_t} (сериал)"])
        title_to_id[clean_t.lower()] = imdb_id
        title_to_id[f"{clean_t} (фильм)".lower()] = imdb_id
        title_to_id[f"{clean_t} (сериал)".lower()] = imdb_id

    results: dict[str, dict[str, Any]] = {}
    chunk_size = 40
    for i in range(0, len(query_parts), chunk_size):
        chunk = query_parts[i : i + chunk_size]
        titles_param = "|".join(chunk)
        try:
            r = await client.get(
                "https://ru.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts|pageimages",
                    "exintro": "1",
                    "explaintext": "1",
                    "pithumbsize": "600",
                    "titles": titles_param,
                    "redirects": "1",
                    "format": "json",
                },
                timeout=6.0,
            )
            if r.status_code == 200:
                pages = r.json().get("query", {}).get("pages", {})
                for pid, p in pages.items():
                    if pid == "-1":
                        continue
                    t = p.get("title", "")
                    ext = p.get("extract", "").strip()
                    thumb = (
                        p.get("thumbnail", {}).get("source")
                        if isinstance(p.get("thumbnail"), dict)
                        else None
                    )
                    if "может означать:" in ext or "значения в Википедии" in ext:
                        continue
                    matched_id = title_to_id.get(t.lower())
                    if not matched_id and " (" in t:
                        base = t.split(" (")[0].strip().lower()
                        matched_id = title_to_id.get(base)

                    if matched_id and ext and len(ext) > 30:
                        existing = results.get(matched_id, {})
                        if not existing.get("extract") or len(ext) > len(
                            existing.get("extract", "")
                        ):
                            results[matched_id] = {
                                "extract": ext,
                                "poster_url": thumb,
                            }
        except Exception as e:
            logger.debug("Wikipedia batch extract error: %s", e)

    return results


# ─── Enrichment Logic ───


async def enrich_catalog(
    items: list[dict[str, Any]],
    wikidata_provider: WikidataProvider | None = None,
) -> list[dict[str, Any]]:
    """Enrich catalog items with Russian titles, rich Russian synopses, and working poster URLs."""
    if not items:
        return []

    provider = wikidata_provider or WikidataProvider()
    valid_ids = [
        it.get("id") for it in items if it.get("id") and is_valid_imdb(it.get("id"))
    ]

    wikidata_map: dict[str, dict[str, Any]] = {}
    if valid_ids:
        try:
            wikidata_map = await provider.lookup_batch_imdb(valid_ids)
        except Exception as e:
            logger.warning("Wikidata catalog enrichment failed: %s", e)
            wikidata_map = {}

    # Collect Russian titles for Wikipedia synopsis search
    ru_titles: dict[str, str] = {}
    for item in items:
        iid = item.get("id", "")
        if iid in wikidata_map and wikidata_map[iid].get("title_ru"):
            ru_titles[iid] = wikidata_map[iid]["title_ru"]

    wp_summaries: dict[str, dict[str, Any]] = {}
    if ru_titles:
        headers = {
            "User-Agent": "PirateCinema/2.0 (contact@piratecinema.local)",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=8.0, follow_redirects=True
            ) as client:
                wp_summaries = await fetch_wikipedia_summaries(client, ru_titles)
        except Exception as e:
            logger.debug("Wikipedia enrichment failed: %s", e)

    enriched: list[dict[str, Any]] = []
    for item in items:
        copy_item = dict(item)
        item_id = copy_item.get("id", "")
        wiki_entry = wikidata_map.get(item_id, {})
        wp_entry = wp_summaries.get(item_id, {})

        # Title
        title_ru = wiki_entry.get("title_ru")
        if title_ru:
            copy_item["title_ru"] = title_ru

        # Description / Overview
        wp_extract = wp_entry.get("extract")
        wiki_overview = wiki_entry.get("overview_ru")

        if wp_extract and len(wp_extract) > 40:
            copy_item["overview_ru"] = wp_extract
        elif wiki_overview:
            copy_item["overview_ru"] = wiki_overview

        # Poster candidates
        wp_poster = wp_entry.get("poster_url")
        wiki_image = wiki_entry.get("image_url")
        if not copy_item.get("poster_url") and (wiki_image or wp_poster):
            copy_item["poster_url"] = wiki_image or wp_poster
        if wp_poster:
            copy_item["_wp_image"] = wp_poster
        if wiki_image:
            copy_item["_wikidata_image"] = wiki_image

        enriched.append(copy_item)

    return enriched


def make_thumbnail(
    image_bytes: bytes,
    max_width: int = 350,
    max_height: int = 525,
    quality: int = 85,
) -> bytes:
    """Resize image bytes to crisp 350x525 thumbnail using PIL for sharp lightweight display."""
    if not image_bytes or len(image_bytes) < 100:
        return image_bytes
    try:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(image_bytes)) as img:
            # If already within target bounds and reasonable size, keep as is
            if img.width <= max_width and img.height <= max_height and len(image_bytes) <= 80 * 1024:
                return image_bytes
            img = img.convert("RGB")
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()
    except Exception as e:
        logger.debug("Failed to create thumbnail with PIL: %s", e)
        return image_bytes


def optimize_existing_posters(posters_dir: Path | None = None) -> int:
    """Optimize any existing poster files on disk that exceed 80KB down to 350x525."""
    p_dir = posters_dir or (get_data_dir() / "posters" / "catalog")
    if not p_dir.is_dir():
        return 0
    count = 0
    for file_path in p_dir.glob("*.jpg"):
        try:
            if file_path.stat().st_size > 80 * 1024:
                data = file_path.read_bytes()
                thumb = make_thumbnail(data, max_width=350, max_height=525, quality=85)
                if len(thumb) < len(data):
                    file_path.write_bytes(thumb)
                    count += 1
        except Exception as e:
            logger.debug("Error optimizing existing poster %s: %s", file_path.name, e)
    return count


# ─── Poster Downloading ───


async def _download_one_poster(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    imdb_id: str,
    candidates: list[str],
    target_dir: Path,
    timeout: float = DEFAULT_POSTER_TIMEOUT,
    max_size: int = MAX_POSTER_SIZE,
    min_existing_size: int = 1024,
) -> tuple[str, str | None]:
    """Download poster from candidate URLs and store as crisp 350x525 thumbnail on disk. Returns (imdb_id, successful_url)."""
    target_path = target_dir / f"{imdb_id}.jpg"
    if target_path.is_file() and target_path.stat().st_size >= min_existing_size:
        return imdb_id, candidates[0] if candidates else None

    async with sem:
        for url in candidates:
            if not url or not isinstance(url, str):
                continue
            clean_url = url.strip()
            if clean_url.startswith("//"):
                clean_url = f"https:{clean_url}"
            elif not clean_url.startswith(("http://", "https://")):
                clean_url = f"https://{clean_url}"

            try:
                r = await client.get(clean_url, timeout=timeout)
                if r.status_code != 200:
                    continue

                content = r.content
                if len(content) < 100 or len(content) > max_size:
                    continue

                content_type = r.headers.get("content-type", "").lower()
                if content_type and not (
                    "image" in content_type
                    or "octet-stream" in content_type
                    or "binary" in content_type
                ):
                    continue

                thumb_bytes = make_thumbnail(content, max_width=350, max_height=525, quality=85)
                tmp_path = target_dir / f"{imdb_id}.tmp"
                tmp_path.write_bytes(thumb_bytes)
                tmp_path.replace(target_path)
                return imdb_id, clean_url
            except Exception as e:
                logger.debug(
                    "Candidate poster download failed for %s (%s): %s",
                    imdb_id,
                    clean_url,
                    e,
                )
                continue

    return imdb_id, None


async def download_catalog_posters(
    items: list[dict[str, Any]],
    target_dir: Path | None = None,
    concurrency: int = 8,
    timeout: float = DEFAULT_POSTER_TIMEOUT,
    max_size: int = MAX_POSTER_SIZE,
) -> None:
    """Resolve working poster URLs from Amazon CDN/Wikipedia and download to disk."""
    p_dir = target_dir or (get_data_dir() / "posters" / "catalog")
    p_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=5.0),
        follow_redirects=True,
        headers=headers,
    ) as client:
        # 1. Fetch high-res Amazon CloudFront posters for all IMDb IDs concurrently
        sem_imdb = asyncio.Semaphore(10)

        async def _get_imdb(item: dict[str, Any]):
            i_id = item.get("id", "")
            if not is_valid_imdb(i_id):
                return
            target_file = p_dir / f"{i_id}.jpg"
            if target_file.is_file() and target_file.stat().st_size >= 1024:
                return
            async with sem_imdb:
                imdb_img = await fetch_imdb_poster_url(client, i_id)
                if imdb_img:
                    item["_imdb_image"] = imdb_img

        await asyncio.gather(*[_get_imdb(it) for it in items], return_exceptions=True)

        # 2. Build prioritized candidate list for each item
        items_to_download: list[tuple[str, list[str]]] = []
        for item in items:
            imdb_id = item.get("id")
            if not is_valid_imdb(imdb_id):
                continue

            target_file = p_dir / f"{imdb_id}.jpg"
            if target_file.is_file() and target_file.stat().st_size > 0:
                item["poster_local_url"] = f"/api/posters/catalog/{imdb_id}.jpg"
                if target_file.stat().st_size >= 1024:
                    continue

            urls: list[str] = []
            # Priority 1: IMDb CDN (Amazon CloudFront) with 350px candidate
            if item.get("_imdb_image"):
                raw_imdb = str(item["_imdb_image"])
                if "._V1_" in raw_imdb:
                    thumb_imdb = re.sub(r"\._V1_.*?\.jpg", "._V1_QL75_UX350_.jpg", raw_imdb)
                    urls.append(thumb_imdb)
                    ux350_imdb = re.sub(r"\._V1_.*?\.jpg", "._V1_UX350_.jpg", raw_imdb)
                    urls.append(ux350_imdb)
                urls.append(raw_imdb)
            # Priority 2: Russian Wikipedia article poster
            if item.get("_wp_image"):
                urls.append(item["_wp_image"])
            # Priority 3: Wikidata image
            if item.get("_wikidata_image"):
                urls.append(item["_wikidata_image"])
            # Priority 4: Cinemeta fallback (only if not metahub or last resort)
            if item.get("poster_url"):
                urls.append(item["poster_url"])

            if urls:
                items_to_download.append((imdb_id, urls))

        # 3. Download posters concurrently
        if items_to_download:
            sem_dl = asyncio.Semaphore(concurrency)
            tasks = [
                _download_one_poster(
                    client=client,
                    sem=sem_dl,
                    imdb_id=imdb_id,
                    candidates=candidates,
                    target_dir=p_dir,
                    timeout=timeout,
                    max_size=max_size,
                )
                for imdb_id, candidates in items_to_download
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # If working remote URL was discovered, update poster_url fallback
            for res in results:
                if isinstance(res, tuple) and res[1]:
                    r_id, good_url = res
                    for it in items:
                        if it.get("id") == r_id and (
                            not it.get("poster_url")
                            or "metahub.space" in str(it.get("poster_url"))
                        ):
                            it["poster_url"] = good_url

    for item in items:
        # Update poster_url if an IMDb/Wikipedia CDN URL is available and current poster is broken metahub
        best_remote = item.get("_imdb_image") or item.get("_wp_image")
        if best_remote and (
            not item.get("poster_url") or "metahub.space" in str(item.get("poster_url"))
        ):
            item["poster_url"] = best_remote

        item.pop("_imdb_image", None)
        item.pop("_wp_image", None)
        item.pop("_wikidata_image", None)
        item["poster_local_url"] = resolve_local_poster_url(item.get("id"), p_dir)


# ─── Disk Cache ───


def load_catalog_cache(
    cache_file: Path,
    ttl_seconds: int = DEFAULT_CACHE_TTL,
    posters_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Read catalog cache if file exists and age is within TTL."""
    if not cache_file.is_file():
        return None
    try:
        content = cache_file.read_text(encoding="utf-8")
        data = json.loads(content)
        if not isinstance(data, dict):
            return None
        updated_at = data.get("updated_at")
        if updated_at is None:
            updated_at = cache_file.stat().st_mtime
        if time.time() - float(updated_at) > ttl_seconds:
            return None
        items = data.get("items")
        if not isinstance(items, list):
            return None
        _resolve_items_posters(items, posters_dir)
        missing_posters = any(it.get("poster_local_url") is None for it in items)
        if missing_posters and posters_dir is not None:
            p_key = "refresh_posters_" + cache_file.stem
            schedule_background_enrichment(
                p_key,
                items,
                cache_file=cache_file,
                posters_dir=posters_dir,
            )
        return items
    except Exception as e:
        logger.warning("Error reading catalog cache %s: %s", cache_file, e)
        return None


def load_stale_catalog_cache(
    cache_file: Path,
    posters_dir: Path | None = None,
) -> list[dict[str, Any]] | None:
    """Read catalog cache regardless of age (stale fallback for instant response)."""
    if not cache_file.is_file():
        return None
    try:
        content = cache_file.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
            _resolve_items_posters(items, posters_dir)
            return items
    except Exception as e:
        logger.warning("Error reading stale catalog cache %s: %s", cache_file, e)
    return None


def save_catalog_cache(cache_file: Path, items: list[dict[str, Any]]) -> None:
    """Save enriched catalog items to disk cache atomically."""
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": time.time(),
            "items": items,
        }
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_file.replace(cache_file)
    except Exception as e:
        logger.warning("Failed to save catalog cache to %s: %s", cache_file, e)


# ─── Background Enrichment & Cache Workers ───

_active_background_tasks: dict[str, asyncio.Task] = {}


async def _background_enrich_and_save(
    catalog_key: str,
    raw_items: list[dict[str, Any]],
    cache_file: Path,
    posters_dir: Path,
    wikidata_provider: WikidataProvider | None = None,
) -> None:
    """Background runner for Wikidata/Wikipedia enrichment, poster downloading, and cache saving."""
    try:
        enriched = await enrich_catalog(raw_items, wikidata_provider)
        await download_catalog_posters(enriched, target_dir=posters_dir)
        save_catalog_cache(cache_file, enriched)
        logger.info(
            "Background catalog enrichment completed for %s (%d items)",
            catalog_key,
            len(enriched),
        )
    except Exception as e:
        logger.warning("Background catalog enrichment failed for %s: %s", catalog_key, e)
    finally:
        _active_background_tasks.pop(catalog_key, None)


def schedule_background_enrichment(
    catalog_key: str,
    raw_items: list[dict[str, Any]],
    cache_file: Path,
    posters_dir: Path,
    wikidata_provider: WikidataProvider | None = None,
) -> None:
    """Schedule background enrichment task if not already in flight."""
    existing_task = _active_background_tasks.get(catalog_key)
    if existing_task and not existing_task.done():
        logger.debug("Background task for %s already running, skipping duplicate", catalog_key)
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    task = loop.create_task(
        _background_enrich_and_save(
            catalog_key=catalog_key,
            raw_items=raw_items,
            cache_file=cache_file,
            posters_dir=posters_dir,
            wikidata_provider=wikidata_provider,
        )
    )
    _active_background_tasks[catalog_key] = task


# ─── High-Level Catalog Accessors ───


async def get_popular_movies(
    cinemeta_provider: Any = None,
    wikidata_provider: WikidataProvider | None = None,
    cache_dir: Path | None = None,
    posters_dir: Path | None = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL,
    background: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve popular movies with disk caching, Wikidata RU enrichment, and local posters.

    If background=True:
      - Returns fresh or stale disk cache immediately (<1ms) for instant paint.
      - If no cache exists, returns Cinemeta / fallback immediately and enriches + downloads in the background.
    """
    c_dir = cache_dir or (get_data_dir() / "catalog")
    p_dir = posters_dir or (get_data_dir() / "posters" / "catalog")
    cache_file = c_dir / "popular.json"

    # 1. Fresh cache hit (< TTL) -> return immediately
    cached = load_catalog_cache(cache_file, ttl_seconds=ttl_seconds, posters_dir=p_dir)
    if cached is not None and len(cached) > 0:
        return cached

    # 2. If background=True and stale cache exists -> return stale cache immediately, refresh in background
    if background:
        stale = load_stale_catalog_cache(cache_file, posters_dir=p_dir)
        if stale is not None and len(stale) > 0:
            async def _bg_refresh_movies():
                try:
                    p = cinemeta_provider or CinemetaProvider()
                    fresh_items = await (p.popular() if hasattr(p, "popular") else cinemeta.popular())
                    if fresh_items:
                        await _background_enrich_and_save("movies", fresh_items, cache_file, p_dir, wikidata_provider)
                except Exception as e:
                    logger.debug("Background refresh failed for movies: %s", e)
            if "movies" not in _active_background_tasks or _active_background_tasks["movies"].done():
                try:
                    loop = asyncio.get_running_loop()
                    _active_background_tasks["movies"] = loop.create_task(_bg_refresh_movies())
                except RuntimeError:
                    pass
            return stale

    # 3. Fetch from Cinemeta
    fetch_failed = False
    items: list[dict[str, Any]] = []
    try:
        provider = cinemeta_provider or CinemetaProvider()
        if hasattr(provider, "popular"):
            items = await provider.popular()
        else:
            items = await cinemeta.popular()
        if not items:
            fetch_failed = True
    except Exception as e:
        logger.warning("Cinemeta popular movies query failed: %s", e)
        fetch_failed = True

    if not fetch_failed and items:
        _resolve_items_posters(items, p_dir)
        if background:
            # Immediate return for instant first paint; background handles RU enrichment & thumb downloads
            schedule_background_enrichment(
                "movies",
                items,
                cache_file=cache_file,
                posters_dir=p_dir,
                wikidata_provider=wikidata_provider,
            )
            return items

        # Synchronous execution (background=False)
        try:
            enriched = await enrich_catalog(items, wikidata_provider)
            await download_catalog_posters(enriched, target_dir=p_dir)
            save_catalog_cache(cache_file, enriched)
            return enriched
        except Exception as e:
            logger.error("Enrichment error for popular movies: %s", e)
            _resolve_items_posters(items, p_dir)
            return items

    # 4. Cinemeta failed -> serve stale cache if available
    stale = load_stale_catalog_cache(cache_file, posters_dir=p_dir)
    if stale is not None and len(stale) > 0:
        logger.info("Serving stale popular movies cache (%d items)", len(stale))
        return stale

    # 5. Hardcoded fallback catalog (like TOP_MOVIES)
    logger.warning("Serving hardcoded fallback popular movies")
    fallback = [dict(m) for m in FALLBACK_POPULAR_MOVIES]
    _resolve_items_posters(fallback, p_dir)
    if background:
        schedule_background_enrichment(
            "movies_fallback",
            fallback,
            cache_file=cache_file,
            posters_dir=p_dir,
            wikidata_provider=wikidata_provider,
        )
    else:
        try:
            await download_catalog_posters(fallback, target_dir=p_dir)
        except Exception:
            pass
        _resolve_items_posters(fallback, p_dir)
    return fallback


async def get_popular_series(
    cinemeta_provider: Any = None,
    wikidata_provider: WikidataProvider | None = None,
    cache_dir: Path | None = None,
    posters_dir: Path | None = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL,
    background: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve popular series with disk caching, Wikidata RU enrichment, and local posters.

    If background=True:
      - Returns fresh or stale disk cache immediately (<1ms) for instant paint.
      - If no cache exists, returns Cinemeta / fallback immediately and enriches + downloads in the background.
    """
    c_dir = cache_dir or (get_data_dir() / "catalog")
    p_dir = posters_dir or (get_data_dir() / "posters" / "catalog")
    cache_file = c_dir / "popular-series.json"

    # 1. Fresh cache hit (< TTL) -> return immediately
    cached = load_catalog_cache(cache_file, ttl_seconds=ttl_seconds, posters_dir=p_dir)
    if cached is not None and len(cached) > 0:
        return cached

    # 2. If background=True and stale cache exists -> return stale cache immediately, refresh in background
    if background:
        stale = load_stale_catalog_cache(cache_file, posters_dir=p_dir)
        if stale is not None and len(stale) > 0:
            async def _bg_refresh_series():
                try:
                    p = cinemeta_provider or CinemetaProvider()
                    fresh_items = await (p.popular_series() if hasattr(p, "popular_series") else cinemeta.popular_series())
                    if fresh_items:
                        await _background_enrich_and_save("series", fresh_items, cache_file, p_dir, wikidata_provider)
                except Exception as e:
                    logger.debug("Background refresh failed for series: %s", e)
            if "series" not in _active_background_tasks or _active_background_tasks["series"].done():
                try:
                    loop = asyncio.get_running_loop()
                    _active_background_tasks["series"] = loop.create_task(_bg_refresh_series())
                except RuntimeError:
                    pass
            return stale

    # 2. Fetch from Cinemeta
    fetch_failed = False
    items: list[dict[str, Any]] = []
    try:
        provider = cinemeta_provider or CinemetaProvider()
        if hasattr(provider, "popular_series"):
            items = await provider.popular_series()
        else:
            items = await cinemeta.popular_series()
        if not items:
            fetch_failed = True
    except Exception as e:
        logger.warning("Cinemeta popular series query failed: %s", e)
        fetch_failed = True

    if not fetch_failed and items:
        _resolve_items_posters(items, p_dir)
        if background:
            # Immediate return for instant first paint; background handles RU enrichment & thumb downloads
            schedule_background_enrichment(
                "series",
                items,
                cache_file=cache_file,
                posters_dir=p_dir,
                wikidata_provider=wikidata_provider,
            )
            return items

        # Synchronous execution (background=False)
        try:
            enriched = await enrich_catalog(items, wikidata_provider)
            await download_catalog_posters(enriched, target_dir=p_dir)
            save_catalog_cache(cache_file, enriched)
            return enriched
        except Exception as e:
            logger.error("Enrichment error for popular series: %s", e)
            _resolve_items_posters(items, p_dir)
            return items

    # 3. Cinemeta failed -> serve stale cache if available
    stale = load_stale_catalog_cache(cache_file, posters_dir=p_dir)
    if stale is not None and len(stale) > 0:
        logger.info("Serving stale popular series cache (%d items)", len(stale))
        return stale

    # 4. Hardcoded fallback catalog (like TOP_SERIES)
    logger.warning("Serving hardcoded fallback popular series")
    fallback = [dict(s) for s in FALLBACK_POPULAR_SERIES]
    _resolve_items_posters(fallback, p_dir)
    if background:
        schedule_background_enrichment(
            "series_fallback",
            fallback,
            cache_file=cache_file,
            posters_dir=p_dir,
            wikidata_provider=wikidata_provider,
        )
    else:
        try:
            await download_catalog_posters(fallback, target_dir=p_dir)
        except Exception:
            pass
        _resolve_items_posters(fallback, p_dir)
    return fallback
