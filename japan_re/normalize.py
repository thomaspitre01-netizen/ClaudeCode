"""Turn the Japanese label/value pairs on a listing page into structured fields.

Every portal and agency writes the same facts slightly differently:
'4,980万円' vs '4980万円(税込)', '123.45m²' vs '37.34坪', '昭和50年3月' vs '1975年3月',
'ＪＲ中央線「吉祥寺」歩12分' vs 'JR中央線 吉祥寺駅 徒歩12分'. This module is the one place
that knows those spellings. Text is NFKC-normalised first, which folds full-width
digits and letters to ASCII and turns '㎡' into 'm2'.

Nothing here guesses silently: where a value is inferred from keywords (property
type, condition), the Japanese words that triggered it are returned as evidence so
the dashboard can say *why* a house was tagged 'major renovation'.
"""
from __future__ import annotations

import re
import unicodedata

from . import areas

TSUBO_M2 = 400 / 121  # 1 tsubo = 3.30578... m²

PROPERTY_TYPES = ('detached_house', 'traditional_house', 'kominka', 'machiya', 'apartment',
                  'condominium', 'entire_building', 'land', 'mixed_use', 'commercial', 'other')
CONDITIONS = ('move_in_ready', 'minor_renovation', 'major_renovation', 'full_renovation',
              'derelict_rebuild', 'unknown')


def nfkc(s: str | None) -> str:
    if s is None:
        return ''
    s = unicodedata.normalize('NFKC', str(s))
    s = s.replace('−', '-').replace('～', '~').replace('〜', '~')
    return re.sub(r'\s+', ' ', s).strip()


def _num(s: str) -> float:
    return float(s.replace(',', ''))


# ---------------------------------------------------------------- money

_OKU = re.compile(r'([\d,.]+)\s*億(?:\s*([\d,.]+)\s*万)?')
_MAN = re.compile(r'([\d,.]+)\s*万')
_YEN = re.compile(r'([\d,]{4,})\s*円')


def parse_price(text: str | None) -> tuple[int | None, str | None]:
    """'4,980万円' -> 49,800,000. '1億2,500万円' -> 125,000,000.

    A range ('3,980万円~4,500万円', common on new subdivisions) returns the low end and
    keeps the original in the note. '価格未定' / '応談' return None.
    """
    t = nfkc(text)
    if not t:
        return None, None
    note = None
    if '~' in t or '、' in t:
        note = t
        t = re.split(r'[~、]', t)[0]
    m = _OKU.search(t)
    if m:
        v = _num(m.group(1)) * 1e8 + (_num(m.group(2)) * 1e4 if m.group(2) else 0)
        return int(round(v)), note
    m = _MAN.search(t)
    if m:
        return int(round(_num(m.group(1)) * 1e4)), note
    m = _YEN.search(t)
    if m:
        return int(_num(m.group(1))), note
    return None, t if t else None


def parse_monthly_fee(text: str | None) -> int | None:
    t = nfkc(text)
    m = re.search(r'([\d,]+)\s*円', t)
    if m:
        return int(_num(m.group(1)))
    m = _MAN.search(t)
    return int(_num(m.group(1)) * 1e4) if m else None


# ---------------------------------------------------------------- area

_M2 = re.compile(r'([\d,]+(?:\.\d+)?)\s*(?:m\s?2|m\^2|平米|平方メートル|m²)')
_TSUBO = re.compile(r'([\d,]+(?:\.\d+)?)\s*坪')


def parse_area(text: str | None) -> tuple[float | None, str | None]:
    """First area in the text, in m². Returns (m², note) where note keeps qualifiers
    like 公簿 (registered), 実測 (surveyed) or 私道負担 (share of a private road)."""
    t = nfkc(text)
    if not t:
        return None, None
    note_bits = [w for w in ('公簿', '登記', '実測', '私道負担', '壁芯', '内法', 'セットバック')
                 if w in t]
    note = t if note_bits or '~' in t else None
    m = _M2.search(t)
    if m:
        return round(_num(m.group(1)), 2), note
    m = _TSUBO.search(t)
    if m:
        return round(_num(m.group(1)) * TSUBO_M2, 2), t
    return None, note


def parse_length_m(text: str | None) -> float | None:
    m = re.search(r'([\d.]+)\s*m(?![2²])', nfkc(text))
    return float(m.group(1)) if m else None


def parse_percent(text: str | None) -> float | None:
    m = re.search(r'([\d.]+)\s*%', nfkc(text))
    return float(m.group(1)) if m else None


def parse_coverage_ratios(text: str | None) -> tuple[float | None, float | None]:
    """'建ぺい率60%・容積率200%' or '60%/200%' -> (60, 200)."""
    nums = re.findall(r'([\d.]+)\s*%', nfkc(text))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        return float(nums[0]), None
    return None, None


# ---------------------------------------------------------------- dates

ERAS = {'明治': 1868, '大正': 1912, '昭和': 1926, '平成': 1989, '令和': 2019,
        'M': 1868, 'T': 1912, 'S': 1926, 'H': 1989, 'R': 2019}


def parse_year_month(text: str | None) -> tuple[int | None, int | None]:
    """'1975年3月', '昭和50年3月', 'S50.3', '平成元年' -> (year, month).
    A Western year in brackets wins over the era year when both appear."""
    t = nfkc(text)
    if not t:
        return None, None
    m = re.search(r'((?:19|20)\d{2})\s*年(?:\s*(\d{1,2})\s*月)?', t)
    if m:
        return int(m.group(1)), int(m.group(2)) if m.group(2) else None
    m = re.search(r'(明治|大正|昭和|平成|令和)\s*(元|\d{1,2})\s*年(?:\s*(\d{1,2})\s*月)?', t)
    if m:
        n = 1 if m.group(2) == '元' else int(m.group(2))
        return ERAS[m.group(1)] + n - 1, int(m.group(3)) if m.group(3) else None
    m = re.search(r'\b([MTSHR])\s*(\d{1,2})[./](\d{1,2})\b', t)
    if m:
        return ERAS[m.group(1)] + int(m.group(2)) - 1, int(m.group(3))
    m = re.search(r'((?:19|20)\d{2})[/.-](\d{1,2})', t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def earthquake_standard(year: int | None, month: int | None, text: str = '') -> str:
    """Japan's 'new' seismic standard applies to building permits from 1 June 1981.
    Construction year is a proxy: a 1982 completion was almost always permitted under
    it; 1981 and 1982 are grey, so only 1983+ is called 'new' from the date alone."""
    t = nfkc(text)
    if '新耐震' in t or '耐震基準適合証明' in t:
        return 'new'
    if '旧耐震' in t:
        return 'old'
    if year is None:
        return 'unknown'
    if year >= 1983:
        return 'new'
    if year <= 1980:
        return 'old'
    return 'unknown'


# ---------------------------------------------------------------- stations

LINES_EN = {
    '中央線': 'JR Chuo Line', '中央本線': 'JR Chuo Line', '中央・総武線': 'JR Chuo-Sobu Line',
    '総武線': 'JR Sobu Line', '山手線': 'JR Yamanote Line', '横須賀線': 'JR Yokosuka Line',
    '東海道本線': 'JR Tokaido Line', '湘南新宿ライン': 'JR Shonan-Shinjuku Line',
    '京浜東北線': 'JR Keihin-Tohoku Line', '埼京線': 'JR Saikyo Line', '南武線': 'JR Nambu Line',
    '武蔵野線': 'JR Musashino Line', '青梅線': 'JR Ome Line', '五日市線': 'JR Itsukaichi Line',
    '八高線': 'JR Hachiko Line', '横浜線': 'JR Yokohama Line', '根岸線': 'JR Negishi Line',
    '井の頭線': 'Keio Inokashira Line', '京王線': 'Keio Line', '京王相模原線': 'Keio Sagamihara Line',
    '小田急線': 'Odakyu Line', '小田原線': 'Odakyu Line', '小田急江ノ島線': 'Odakyu Enoshima Line',
    '江ノ島線': 'Odakyu Enoshima Line', '西武新宿線': 'Seibu Shinjuku Line',
    '西武池袋線': 'Seibu Ikebukuro Line', '西武多摩川線': 'Seibu Tamagawa Line',
    '西武国分寺線': 'Seibu Kokubunji Line', '西武拝島線': 'Seibu Haijima Line',
    '東急東横線': 'Tokyu Toyoko Line', '東横線': 'Tokyu Toyoko Line',
    '田園都市線': 'Tokyu Den-en-toshi Line', '東急田園都市線': 'Tokyu Den-en-toshi Line',
    '世田谷線': 'Tokyu Setagaya Line', '大井町線': 'Tokyu Oimachi Line', '目黒線': 'Tokyu Meguro Line',
    '丸ノ内線': 'Tokyo Metro Marunouchi Line', '東西線': 'Tokyo Metro Tozai Line',
    '大江戸線': 'Toei Oedo Line', '都営大江戸線': 'Toei Oedo Line',
    '江ノ島電鉄線': 'Enoden', '江ノ島電鉄': 'Enoden', '江ノ電': 'Enoden',
    '湘南モノレール': 'Shonan Monorail', '京急逗子線': 'Keikyu Zushi Line',
    '京急本線': 'Keikyu Main Line', '京急久里浜線': 'Keikyu Kurihama Line',
    '多摩モノレール': 'Tama Monorail', '都電荒川線': 'Toden Arakawa Line',
}

STATIONS_EN = {
    '中野': 'Nakano', '高円寺': 'Koenji', '阿佐ケ谷': 'Asagaya', '阿佐ヶ谷': 'Asagaya',
    '荻窪': 'Ogikubo', '西荻窪': 'Nishi-Ogikubo', '吉祥寺': 'Kichijoji', '三鷹': 'Mitaka',
    '武蔵境': 'Musashi-Sakai', '東小金井': 'Higashi-Koganei', '武蔵小金井': 'Musashi-Koganei',
    '国分寺': 'Kokubunji', '西国分寺': 'Nishi-Kokubunji', '国立': 'Kunitachi', '立川': 'Tachikawa',
    '井の頭公園': 'Inokashira-koen', '三鷹台': 'Mitakadai', '久我山': 'Kugayama',
    '富士見ケ丘': 'Fujimigaoka', '高井戸': 'Takaido', '浜田山': 'Hamadayama',
    '西永福': 'Nishi-Eifuku', '永福町': 'Eifukucho', '明大前': 'Meidaimae',
    '下北沢': 'Shimokitazawa', '新宿': 'Shinjuku', '東京': 'Tokyo', '渋谷': 'Shibuya',
    '鎌倉': 'Kamakura', '北鎌倉': 'Kita-Kamakura', '大船': 'Ofuna', '逗子': 'Zushi',
    '逗子・葉山': 'Zushi-Hayama', '新逗子': 'Shin-Zushi', '東逗子': 'Higashi-Zushi',
    '由比ヶ浜': 'Yuigahama', '和田塚': 'Wadazuka', '長谷': 'Hase', '極楽寺': 'Gokurakuji',
    '稲村ヶ崎': 'Inamuragasaki', '七里ヶ浜': 'Shichirigahama', '鎌倉高校前': 'Kamakurakokomae',
    '腰越': 'Koshigoe', '江ノ島': 'Enoshima', '藤沢': 'Fujisawa', '湘南江の島': 'Shonan-Enoshima',
    '西鎌倉': 'Nishi-Kamakura', '湘南深沢': 'Shonan-Fukasawa', '湘南町屋': 'Shonan-Machiya',
    '田浦': 'Taura', '横須賀': 'Yokosuka',
}

_STATION_RE = re.compile(
    r'(?P<line>[^\s「」『』()]*?(?:線|ライン|モノレール|電鉄|江ノ電))?\s*'
    r'[/／]?\s*[「『]?(?P<station>[^\s「」『』()/／]+?)[」』]?(?:駅)?\s*'
    r'(?:(?:バス|ﾊﾞｽ)\s*(?P<bus>\d+)\s*分\s*(?:[^\d]*?停)?\s*)?'
    r'(?:徒歩|歩)\s*(?P<walk>\d+)\s*分')


def parse_stations(text: str | None) -> list[dict]:
    """'ＪＲ中央線「吉祥寺」歩12分 京王井の頭線「井の頭公園」歩8分' -> two station dicts.
    Bus legs ('バス10分 停歩3分') are kept separately from the walk."""
    t = nfkc(text)
    out = []
    for m in _STATION_RE.finditer(t):
        line = (m.group('line') or '').strip()
        line = re.sub(r'^(JR|ＪＲ)', 'JR', line)
        station = m.group('station').strip().removesuffix('駅')
        if station in ('停', 'バス停'):
            continue
        key = line.removeprefix('JR').removeprefix('京王').removeprefix('西武') \
            if line.removeprefix('JR') not in LINES_EN else line.removeprefix('JR')
        line_en = LINES_EN.get(line.removeprefix('JR')) or LINES_EN.get(key) or LINES_EN.get(line)
        if not line_en and line:
            line_en = line  # untranslated, kept honest rather than guessed
        out.append({
            'line_ja': line or None, 'line_en': line_en or None,
            'station_ja': station, 'station_en': STATIONS_EN.get(station),
            'walk_min': int(m.group('walk')),
            'bus_min': int(m.group('bus')) if m.group('bus') else None,
            'raw_ja': m.group(0),
        })
    return out


# ---------------------------------------------------------------- building

STRUCTURES = [  # order matters: 鉄骨鉄筋 before 鉄骨 and 鉄筋
    (('SRC', '鉄骨鉄筋コンクリート'), 'src'),
    (('RC', '鉄筋コンクリート'), 'rc'),
    (('軽量鉄骨',), 'light_steel'),
    (('鉄骨', 'S造'), 'steel'),
    (('木造', '木骨'), 'wood'),
    (('ブロック', 'CB造'), 'block'),
]


def parse_structure(text: str | None) -> tuple[str | None, int | None, int | None]:
    """'木造2階建' -> ('wood', 2, None). 'RC造地上3階地下1階建' -> ('rc', 3, 1)."""
    t = nfkc(text)
    if not t:
        return None, None, None
    kind = 'other'
    for keys, k in STRUCTURES:
        if any(key in t for key in keys):
            kind = k
            break
    below = re.search(r'地下\s*(\d+)\s*階', t)
    above = re.search(r'地上\s*(\d+)\s*階', t) or re.search(r'(?<!地下)(?<!\d)(\d+)\s*階建', t)
    if not above and '平屋' in t:
        return kind, 1, int(below.group(1)) if below else None
    return kind, int(above.group(1)) if above else None, int(below.group(1)) if below else None


def parse_layout(text: str | None) -> tuple[str | None, int | None]:
    """'4LDK+S(納戸)' -> ('4LDK+S', 4). 'ワンルーム' -> ('1R', 1)."""
    t = nfkc(text).upper()
    if 'ワンルーム' in t:
        return '1R', 1
    m = re.search(r'(\d+)\s*(S?LDK|SDK|DK|K|R)(\+S)?', t)
    if not m:
        return None, None
    return m.group(0).replace(' ', ''), int(m.group(1))


ZONING_EN = {
    '第一種低層住居専用地域': 'Category 1 low-rise exclusive residential',
    '第二種低層住居専用地域': 'Category 2 low-rise exclusive residential',
    '第一種中高層住居専用地域': 'Category 1 mid/high-rise exclusive residential',
    '第二種中高層住居専用地域': 'Category 2 mid/high-rise exclusive residential',
    '第一種住居地域': 'Category 1 residential',
    '第二種住居地域': 'Category 2 residential',
    '準住居地域': 'Quasi-residential',
    '田園住居地域': 'Rural residential',
    '近隣商業地域': 'Neighbourhood commercial',
    '商業地域': 'Commercial',
    '準工業地域': 'Quasi-industrial',
    '工業地域': 'Industrial',
    '工業専用地域': 'Exclusive industrial',
    '市街化調整区域': 'Urbanization control area',
    '無指定': 'Unzoned',
}
_ZONING_SHORT = {'一低': '第一種低層住居専用地域', '二低': '第二種低層住居専用地域',
                 '一中高': '第一種中高層住居専用地域', '二中高': '第二種中高層住居専用地域',
                 '一住居': '第一種住居地域', '二住居': '第二種住居地域', '1種低層': '第一種低層住居専用地域',
                 '2種低層': '第二種低層住居専用地域', '1種中高層': '第一種中高層住居専用地域',
                 '2種中高層': '第二種中高層住居専用地域', '1種住居': '第一種住居地域',
                 '2種住居': '第二種住居地域'}


def parse_zoning(text: str | None) -> tuple[str | None, str | None]:
    t = nfkc(text)
    if not t:
        return None, None
    t2 = t.replace('1種', '一種').replace('2種', '二種')
    found = [z for z in sorted(ZONING_EN, key=len, reverse=True) if z in t2]
    # 第一種住居地域 is a substring of nothing longer, but 工業地域 is inside 準工業地域
    # and 工業専用地域; drop names that sit inside a longer match.
    found = [z for z in found if not any(z != o and z in o for o in found)]
    if not found:
        for short, full in _ZONING_SHORT.items():
            if short in t:
                found.append(full)
    if not found:
        return t, None
    return t, ' / '.join(ZONING_EN[z] for z in found)


def parse_land_rights(text: str | None) -> tuple[str | None, int | None]:
    t = nfkc(text)
    if not t:
        return None, None
    if '定期借地' in t:
        return 'fixed_term_leasehold', 0
    if '借地' in t or '地上権' in t:
        return 'leasehold', 0
    if '所有権' in t:
        return 'freehold', 1
    return 'other', None


def parse_road(text: str | None) -> tuple[float | None, float | None]:
    """'南側 公道 幅員4.0m 接面9.5m' -> (road width 4.0, frontage 9.5)."""
    t = nfkc(text)
    width = re.search(r'幅員?\s*(?:約)?\s*([\d.]+)\s*m', t)
    front = re.search(r'(?:接面|間口|接道)\s*(?:約)?\s*([\d.]+)\s*m', t)
    if not width and not front:
        ms = re.findall(r'([\d.]+)\s*m(?![2²])', t)
        if ms:
            return float(ms[0]), None
    return (float(width.group(1)) if width else None,
            float(front.group(1)) if front else None)


def parse_occupancy(text: str | None) -> str:
    t = nfkc(text)
    if not t:
        return 'unknown'
    if '空家' in t or '空き家' in t or '空室' in t or '更地' in t:
        return 'vacant'
    if '賃貸中' in t or 'オーナーチェンジ' in t:
        return 'tenanted'
    if '居住中' in t:
        return 'owner_occupied'
    return 'unknown'


# ---------------------------------------------------------------- classification

_TYPE_RULES = [  # (type, keywords) - first match wins, most specific first
    ('kominka', ('古民家',)),
    ('machiya', ('町家', '町屋', '京町家')),
    ('traditional_house', ('日本家屋', '純和風', '数寄屋', '数奇屋', '茶室', '和風建築', '古い日本家屋',
                           '伝統構法', '在来和風', '書院造')),
    ('mixed_use', ('店舗付住宅', '店舗併用', '事務所付住宅', '店舗付き住宅', '併用住宅')),
    ('entire_building', ('一棟', '1棟', '売ビル', '一棟売', 'アパート一棟', 'マンション一棟')),
    ('commercial', ('売店舗', '売事務所', '売倉庫', '売工場', '店舗', '事務所', '倉庫')),
    ('condominium', ('中古マンション', '新築マンション', '区分所有', 'マンション')),
    ('land', ('売地', '土地', '古家付', '古家あり', '上物あり', '建築条件付')),
    ('detached_house', ('中古一戸建', '一戸建', '戸建', '新築一戸建', '平屋', '住宅')),
]


_NOT_MACHIYA = re.compile(r'湘南町屋|町屋駅|「町屋」|町屋\s*(?:駅|徒歩|バス)')


def classify_type(category_hint: str | None, headline: str | None,
                  description: str | None = None) -> tuple[str, str | None]:
    """Property type from the source's own category (the URL section the listing came
    from), the headline (title + the page's own 種目 field) and the description.
    Returns (type, evidence).

    Traditional types (古民家, 町家, 日本家屋...) are looked for everywhere and win over
    the category: a SUUMO 'used house' described as 古民家 becomes 'kominka'.
    Building-use types (一棟, 店舗付住宅) are only read from the headline, because
    descriptions mention nearby shops and condos all the time.
    A 'land' listing with an old house on it (古家付き土地) stays 'land'; the house is
    what the condition field records as derelict_rebuild.
    """
    # 町屋 is also a station name (湘南町屋 in Kamakura, 町屋 in Arakawa): not a townhouse
    head = _NOT_MACHIYA.sub('', nfkc(headline))
    blob = head + ' ' + _NOT_MACHIYA.sub('', nfkc(description))
    for ptype, kws in _TYPE_RULES[:3]:
        for kw in kws:
            if kw in blob:
                return ptype, kw
    for ptype, kws in _TYPE_RULES[3:5]:
        for kw in kws:
            if kw in head:
                return ptype, kw
    if category_hint in PROPERTY_TYPES:
        return category_hint, f'source category: {category_hint}'
    for ptype, kws in _TYPE_RULES[5:]:
        for kw in kws:
            if kw in head:
                return ptype, kw
    return 'other', None


_COND_RULES = [  # (condition, keywords) - checked in this order
    ('derelict_rebuild', ('古家付', '古家あり', '古家有', '上物あり', '解体更地', '廃屋', '建物は価値なし',
                          '建物価値なし', '更地渡し', '解体前提', '取り壊し')),
    ('full_renovation', ('スケルトン', 'フルリノベーション前提', '全面改修が必要', '大規模改修が必要',
                         '雨漏り', '傾き', 'シロアリ', '白蟻', '床下腐食')),
    ('major_renovation', ('要リフォーム', '要改修', '要修繕', 'リフォーム前提', 'リノベーション前提',
                          '現況渡し', '現状渡し', '現状有姿', '手入れが必要', '修繕が必要', '長期空き家',
                          'DIY', 'リフォーム推奨', '改修前提')),
    ('minor_renovation', ('一部リフォーム済', '一部改装', 'クリーニング済', '水回りリフォーム済',
                          '部分リフォーム')),
    ('move_in_ready', ('リノベーション済', 'リフォーム済', '全面リフォーム済', '築浅',
                       'フルリノベーション済', 'すぐに住める', '改装済', '即入居可')),
]


def classify_condition(year_built: int | None, *texts: str | None) -> tuple[str, str | None]:
    """Renovation need from keywords. Treated as an opportunity attribute, never a filter.

    The oldest houses with no keywords at all are left 'unknown' rather than assumed:
    an unrenovated 1970 house is probably major work, but the dashboard should show
    that as an open question, not a fact.
    """
    blob = nfkc(' '.join(t for t in texts if t))
    for cond, kws in _COND_RULES:
        for kw in kws:
            if kw in blob:
                # '一部リフォーム済' contains 'リフォーム済'; the order above handles that,
                # but 'リフォーム済' must not fire on '要リフォーム' text either.
                return cond, kw
    return 'unknown', None


def flags(*texts: str | None) -> dict:
    blob = nfkc(' '.join(t for t in texts if t))
    return {
        'rebuild_prohibited': (0 if re.search(r'再建築不可では(な|あり)', blob) or '再建築可' in blob
                               else 1 if '再建築不可' in blob else None),
        'setback_required': 1 if ('セットバック要' in blob or 'セットバック有' in blob
                                  or '要セットバック' in blob) else None,
        'urbanization_control': 1 if '市街化調整区域' in blob else None,
    }


# ---------------------------------------------------------------- address

def split_address(address_ja: str | None) -> dict:
    muni, rest = areas.match_address(nfkc(address_ja) if address_ja else None)
    if not muni:
        return {'prefecture': None, 'municipality': None, 'municipality_ja': None,
                'neighborhood_ja': None}
    # neighbourhood = town name + chome, without lot numbers
    nb = None
    if rest:
        m = re.match(r'([^\d\-]+?(?:\d+\s*丁目)?)(?:\d|-|$)', rest)
        nb = (m.group(1) if m else rest).strip() or None
    return {'prefecture': muni.pref, 'municipality': muni.name_en,
            'municipality_ja': muni.name_ja, 'neighborhood_ja': nb}
